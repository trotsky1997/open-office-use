"""Create a review bundle from one immutable local Office snapshot."""
import json
import os
import tempfile
import snapshot as snapshots
from pathlib import Path

import layout
import notes
import chart_cache
import officecli_backend
import spreadsheet
import slide_text_check
import visual
import word


def create(source, destination, render, revision=None):
    source = Path(source).resolve(strict=True); destination = Path(destination).absolute()
    if source.suffix.lower() not in ('.docx', '.xlsx', '.pptx'):
        raise ValueError('Review requires a DOCX, XLSX or PPTX file')
    if source.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('Document exceeds the 128 MiB size limit')
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f'Output already exists: {destination}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix='.office-review-') as tmp:
        root = Path(tmp); snapshot, digest = snapshots.copy(source, root)
        report = {'format': source.suffix.lower()[1:], 'source_name': source.name, 'snapshot_sha256': digest,
                  'snapshot_size': snapshot.stat().st_size, 'revision': revision, 'checks': {},
                  'notes': ['Checks describe their covered scope and are not a substitute for visual review.',
                            'Rendering uses LibreOffice and may differ from Microsoft Office.']}
        def check(name, action):
            try:
                result = action(); report['checks'][name] = {'status': 'completed', 'result': result}; return result
            except Exception as exc:
                report['checks'][name] = {'status': 'error', 'error_type': type(exc).__name__, 'error': str(exc)[:2000]}; return None
        audit = check('officecli_audit', lambda: officecli_backend.audit(snapshot))
        flags = []
        if audit is not None:
            if audit['validation']['exit_code'] != 0 or audit['validation']['result'].get('success') is not True:
                flags.append('schema_validation_failed')
            if audit['issues_error'] is not None:
                flags.append('issues_scan_failed')
            elif isinstance(audit.get('issues'), dict) and audit['issues'].get('count', 0):
                flags.append('officecli_issues_reported')
        if source.suffix.lower() == '.docx':
            comments = check('word_comments', lambda: word.list_comments(snapshot))
            if comments is not None:
                if comments['total_comments']: flags.append('word_comments_present')
                if comments['truncated']: flags.append('comments_truncated')
                if not comments['anchor_scan_complete']: flags.append('comment_anchor_scan_incomplete')
            changes = check('word_tracked_changes', lambda: word.tracked_changes(snapshot))
            if changes is not None:
                if changes['records_scanned']: flags.append('word_tracked_changes_present')
                if changes['records_truncated'] or not changes['scan_complete']: flags.append('word_tracked_changes_incomplete')
        elif source.suffix.lower() == '.xlsx':
            formulas = check('formula_scan', lambda: spreadsheet.scan_formulas(snapshot))
            if formulas is not None:
                if not formulas['complete']: flags.append('formula_scan_incomplete')
                if formulas['dynamic_array_metadata']: flags.append('dynamic_array_metadata_present')
                if formulas['dynamic_array_metadata'] is None: flags.append('dynamic_array_metadata_unknown')
                if formulas['formula_errors'] or formulas['literal_errors']: flags.append('formula_or_cell_errors')
                if formulas['empty_or_missing_cache']: flags.append('formula_cache_missing')
                if formulas['recalculation_requests']: flags.append('sheet_recalculation_requested')
                if not formulas['calculation_metadata_complete']: flags.append('sheet_calculation_metadata_incomplete')
            chart_results = check('chart_cache_scan', lambda: chart_cache.scan(snapshot))
            if chart_results is not None:
                if not chart_results['complete']: flags.append('chart_cache_scan_incomplete')
                if chart_results['mismatch_references']: flags.append('chart_cache_mismatch')
                if chart_results['missing_caches']: flags.append('chart_cache_missing')
        else:
            geometry = check('slide_layout', lambda: layout.inspect(snapshot))
            if geometry is not None:
                if geometry['hidden_slides']: flags.append('hidden_slides_present')
                if not geometry['visibility_known']: flags.append('slide_visibility_unknown')
                if not geometry['complete']: flags.append('slide_layout_incomplete')
                if geometry['off_slide_count'] or geometry['overlap_count']: flags.append('slide_layout_candidates')
            note_inventory = check('speaker_notes', lambda: notes.inventory(snapshot))
            if note_inventory is not None:
                if note_inventory['notes_slides']: flags.append('speaker_notes_parts_present')
                if any(item['body_text_present'] for item in note_inventory['notes_slides']): flags.append('speaker_notes_text_present')
                if not note_inventory['complete']: flags.append('speaker_notes_scan_incomplete')
        pdf = check('render_pdf', lambda: render(snapshot, root / 'render'))
        if source.suffix.lower() == '.pptx':
            if pdf is not None:
                text_check = check('slide_text', lambda: slide_text_check.inspect(snapshot, pdf))
                if text_check is not None:
                    if not text_check['complete']: flags.append('slide_text_scan_incomplete')
                    if text_check['candidate_count']: flags.append('slide_text_candidates')
            else:
                report['checks']['slide_text'] = {'status': 'skipped', 'reason': 'PDF rendering failed'}
        files = {}
        if pdf is not None:
            files['preview.pdf'] = Path(pdf)
            def overview():
                data, details = visual.contact_sheet(snapshot, 1, 12, lambda _source, _destination: pdf)
                path = root / 'overview.png'; path.write_bytes(data); files['overview.png'] = path
                return {**details, 'file': 'overview.png', 'pdf': 'preview.pdf'}
            check('overview', overview)
        else:
            report['checks']['overview'] = {'status': 'skipped', 'reason': 'PDF rendering failed'}
        # Store bundle-relative artifact paths rather than paths to the temporary workspace.
        if pdf is not None: report['checks']['render_pdf']['result'] = {'file': 'preview.pdf'}
        report['check_errors'] = [name for name, item in report['checks'].items() if item['status'] == 'error']
        report['flags'] = flags
        report_path = root / 'report.json'; report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        files['report.json'] = report_path
        destination.mkdir()
        published = []
        try:
            for name, path in files.items():
                target = destination / name; os.link(path, target); published.append(target)
        except BaseException:
            for path in published: path.unlink(missing_ok=True)
            destination.rmdir(); raise
    return {'output_dir': str(destination), 'report': str(destination / 'report.json'),
            'artifacts': {name: str(destination / name) for name in files}, 'snapshot_sha256': report['snapshot_sha256'],
            'revision': revision, 'check_errors': report['check_errors'], 'flags': report['flags']}
