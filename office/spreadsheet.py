"""Bounded worksheet inspection and explicit LibreOffice recalculation."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries


def read_range(file, sheet, cell_range):
    if Path(file).suffix.lower() != '.xlsx':
        raise ValueError('Worksheet reading requires an .xlsx file')
    try:
        min_col, min_row, max_col, max_row = range_boundaries(cell_range)
        if min_col is None or min_row is None or max_col is None or max_row is None:
            raise ValueError
        if (min_col < 1 or min_row < 1
                or max_col > 16384 or max_row > 1048576 or min_col > max_col or min_row > max_row
                or (max_col - min_col + 1) * (max_row - min_row + 1) > 10000):
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError('Specify a valid rectangular cell range of at most 10,000 cells') from None
    formulas = load_workbook(file, read_only=True, data_only=False)
    values = None
    try:
        values = load_workbook(file, read_only=True, data_only=True)
        if sheet not in formulas.sheetnames:
            raise ValueError(f'Worksheet not found: {sheet}')
        f_rows = formulas[sheet].iter_rows(min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col)
        v_rows = values[sheet].iter_rows(min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col)
        rows = []
        for _ in range(max_row - min_row + 1):
            f_row = next(f_rows, ())
            v_row = next(v_rows, ())
            row = []
            for col in range(max_col - min_col + 1):
                f = f_row[col] if col < len(f_row) else None
                v = v_row[col] if col < len(v_row) else None
                if f is not None and f.data_type == 'f':
                    formula = f.value
                    if not isinstance(formula, str):
                        formula = {'text': getattr(formula, 'text', None), 'ref': getattr(formula, 'ref', None)}
                    row.append({'formula': formula, 'value': v.value if v else None, 'type': v.data_type if v else 'n'})
                else:
                    row.append({'value': f.value if f else None, 'type': f.data_type if f else 'n'})
            rows.append(row)
        return {'sheet': sheet, 'range': cell_range, 'rows': rows, 'cache_freshness': 'unknown'}
    finally:
        formulas.close()
        if values:
            values.close()


def recalculate(source, output):
    source = Path(source).resolve(strict=True)
    output = Path(output).absolute()
    if source.suffix.lower() != '.xlsx' or output.suffix.lower() != '.xlsx':
        raise ValueError('Recalculation requires .xlsx input and output')
    if output.exists() or output.is_symlink():
        raise FileExistsError(f'Output already exists: {output}')
    executable = shutil.which('soffice') or shutil.which('libreoffice')
    if not executable:
        raise RuntimeError('LibreOffice (soffice) is required for recalculation')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.office-calc-') as tmp:
        root = Path(tmp)
        inputs = root / 'input'; inputs.mkdir()
        results = root / 'result'; results.mkdir()
        copy = inputs / 'workbook.xlsx'
        shutil.copyfile(source, copy)
        profile = (root / 'profile').as_uri()
        result = subprocess.run([executable, '-env:UserInstallation=' + profile, '--headless',
                                 '--convert-to', 'xlsx', '--outdir', str(results), str(copy)],
                                capture_output=True, text=True, timeout=120, check=False)
        candidate = results / copy.name
        if result.returncode or not candidate.is_file():
            raise RuntimeError(f'LibreOffice recalculation failed: {result.stderr or result.stdout}')
        check = load_workbook(candidate, read_only=True, data_only=False)
        check.close()
        os.link(candidate, output)
    return str(output)


def protected_formula_ranges(file, sheet):
    """Find multi-cell formula ranges in the saved worksheet without rewriting it."""
    import xml.etree.ElementTree as ET
    import zipfile

    workbook = load_workbook(file, read_only=True, data_only=False)
    try:
        if sheet not in workbook.sheetnames:
            raise ValueError(f'Worksheet not found: {sheet}')
        # openpyxl resolves workbook relationships to this package-relative path.
        path = getattr(workbook[sheet], '_worksheet_path', None)
        if not isinstance(path, str):
            raise RuntimeError('Cannot locate worksheet XML for formula protection')
    finally:
        workbook.close()
    ranges = []
    shared_ranges, shared_uses = {}, set()
    with zipfile.ZipFile(file) as archive, archive.open(path) as stream:
        for _, element in ET.iterparse(stream, events=('end',)):
            if element.tag.rsplit('}', 1)[-1] == 'f':
                kind, ref, shared_id = element.get('t'), element.get('ref'), element.get('si')
                if kind == 'shared':
                    if shared_id is None:
                        raise ValueError('Shared formula has no identifier')
                    shared_uses.add(shared_id)
                if kind in ('array', 'dataTable', 'shared') and ref:
                    try:
                        bounds = range_boundaries(ref)
                        if any(value is None for value in bounds):
                            raise ValueError
                    except (TypeError, ValueError):
                        raise ValueError('Invalid multi-cell formula range') from None
                    if kind == 'shared':
                        assert shared_id is not None
                        if shared_id in shared_ranges and shared_ranges[shared_id] != bounds:
                            raise ValueError('Conflicting shared formula ranges')
                        shared_ranges[shared_id] = bounds
                    ranges.append(bounds)
                elif kind in ('array', 'dataTable') and not ref:
                    raise ValueError('Multi-cell formula has no protected range')
            element.clear()
    if shared_uses - shared_ranges.keys():
        raise ValueError('Shared formula has no protected range')
    return ranges
