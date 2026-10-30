"""Compare saved Office files using bounded text views and OOXML parts."""
import difflib
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import officecli_backend


def part_hashes(file):
    with zipfile.ZipFile(file) as archive:
        parts = [entry for entry in archive.infolist() if not entry.is_dir()]
        names = [entry.filename for entry in parts]
        if len(parts) > 5000 or sum(entry.file_size for entry in parts) > 128 * 1024 * 1024:
            raise ValueError('Office package exceeds the review limit of 5,000 parts or 128 MiB uncompressed')
        if len(names) != len(set(names)):
            raise ValueError('Office package contains duplicate part names')
        hashes = {}
        for entry in parts:
            digest = hashlib.sha256()
            with archive.open(entry) as part:
                for chunk in iter(lambda: part.read(1024 * 1024), b''):
                    digest.update(chunk)
            hashes[entry.filename] = digest.hexdigest()
        return hashes


def compare(before, after):
    before, after = Path(before).resolve(strict=True), Path(after).resolve(strict=True)
    suffix = before.suffix.lower()
    if suffix not in ('.docx', '.xlsx', '.pptx') or after.suffix.lower() != suffix:
        raise ValueError('Both files must have the same supported Office format')
    with tempfile.TemporaryDirectory(prefix='office-review-') as tmp:
        left, right = Path(tmp) / ('before' + suffix), Path(tmp) / ('after' + suffix)
        shutil.copyfile(before, left)
        shutil.copyfile(after, right)
        try:
            left_parts, right_parts = part_hashes(left), part_hashes(right)
        except zipfile.BadZipFile as exc:
            raise ValueError('Invalid Office package') from exc
        before_view = officecli_backend.call('view', left, 'text', '--max-lines', '2000')
        after_view = officecli_backend.call('view', right, 'text', '--max-lines', '2000')
    before_text = json.dumps(before_view, ensure_ascii=False, sort_keys=True, indent=2)
    after_text = json.dumps(after_view, ensure_ascii=False, sort_keys=True, indent=2)
    # shortcut: views beyond 100,000 characters are clipped, use range-specific comparison for large files.
    view_clipped = len(before_text) > 100000 or len(after_text) > 100000
    lines = difflib.unified_diff(before_text[:100000].splitlines(), after_text[:100000].splitlines(),
                                 fromfile='before', tofile='after', lineterm='')
    diff = []
    for line in lines:
        if len(diff) == 500:
            break
        diff.append(line)
    else:
        return {'parts': changes(left_parts, right_parts), 'text_diff': diff,
                'text_diff_truncated': view_clipped, 'text_view_max_lines': 2000,
                'text_view_may_be_truncated': True}
    return {'parts': changes(left_parts, right_parts), 'text_diff': diff,
            'text_diff_truncated': True, 'text_view_max_lines': 2000,
            'text_view_may_be_truncated': True}


def changes(before, after):
    return {'added': sorted(after.keys() - before.keys()),
            'removed': sorted(before.keys() - after.keys()),
            'modified': sorted(name for name in before.keys() & after.keys() if before[name] != after[name])}
