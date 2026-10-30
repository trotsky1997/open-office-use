"""Verify versioned, run-preserving PowerPoint text replacement."""
import copy
import tempfile
import zipfile
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches
from lxml import etree

import session
import slides

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); source = root / 'source.pptx'; draft = root / 'draft'
    image = root / 'image.png'; Image.new('RGB', (10, 10), 'red').save(image)
    presentation = Presentation(); first = presentation.slides.add_slide(presentation.slide_layouts[6]); first.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1)).text = 'Wrong slide'
    target = presentation.slides.add_slide(presentation.slide_layouts[6]); target.shapes.add_picture(str(image), Inches(1), Inches(1))
    group = target.shapes.add_group_shape(); group_id = group.shape_id
    inner = group.shapes.add_textbox(Inches(1), Inches(2), Inches(4), Inches(1)); inner.text = 'Grouped'; inner_id = inner.shape_id
    box = target.shapes.add_textbox(Inches(1), Inches(3), Inches(4), Inches(1)); paragraph = box.text_frame.paragraphs[0]
    first_run = paragraph.add_run(); first_run.text = 'Hello '; first_run.font.bold = True
    second_run = paragraph.add_run(); second_run.text = 'world!'; second_run.font.italic = True
    multi = target.shapes.add_textbox(Inches(1), Inches(4), Inches(4), Inches(1)); multi.text = 'first\nsecond'
    broken = target.shapes.add_textbox(Inches(1), Inches(5), Inches(4), Inches(1)); broken.text = 'before'; broken.text_frame.paragraphs[0]._p.append(OxmlElement('a:br'))
    linked = target.shapes.add_textbox(Inches(1), Inches(6), Inches(4), Inches(1)); link_run = linked.text_frame.paragraphs[0].add_run(); link_run.text = 'Link'; link_run.hyperlink.address = 'https://example.com'
    base = root / 'base.pptx'; presentation.save(base)
    with zipfile.ZipFile(base) as original_zip, zipfile.ZipFile(source, 'w') as reordered:
        for entry in original_zip.infolist():
            data = original_zip.read(entry)
            if entry.filename == 'ppt/presentation.xml':
                tree = etree.fromstring(data); ns = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main'}
                ids = tree.find('p:sldIdLst', ns); ids.insert(0, ids[1]); data = etree.tostring(tree, encoding='UTF-8', xml_declaration=True, standalone=True)
            reordered.writestr(entry, data)
    original = source.read_bytes()
    part = slides.slide_part(source, 0)
    assert part.endswith('slide2.xml')
    session.start(draft, source=source)
    target_info = session.edit_target(draft, 0, '/slide[1]/shape[1]')
    assert target_info['replace_text_path_supported'] and target_info['value'] == 'Hello world!'
    for path, find in [('/slide[1]/shape[2]', 'first'), ('/slide[1]/shape[3]/paragraph[1]', 'before'), ('/slide[1]/shape[4]/paragraph[1]', 'Link'), ('/slide[1]/shape[1]', 'missing')]:
        try:
            session.replace_text(draft, 0, path, find, 'bad')
            raise AssertionError('Unsafe replacement succeeded')
        except ValueError:
            pass
    assert session.info(draft)['latest_revision'] == 0
    result = session.replace_text(draft, 0, '/slide[1]/shape[1]/paragraph[1]', 'llo wor', 'i earth')
    assert result['revision'] == 1 and source.read_bytes() == original
    updated = Presentation(result['file']); shape = next(shape for shape in updated.slides[0].shapes if shape.shape_id == box.shape_id)
    runs = shape.text_frame.paragraphs[0].runs
    assert shape.text == 'Hei earthld!' and runs[0].font.bold and runs[1].font.italic
    assert updated.slides[1].shapes[0].text == 'Wrong slide'
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(result['file']) as after:
        assert set(before.namelist()) == set(after.namelist())
        assert all(before.read(name) == after.read(name) for name in before.namelist() if name != part)
        old = etree.fromstring(before.read(part)); new = etree.fromstring(after.read(part))
        ns = {'p':'http://schemas.openxmlformats.org/presentationml/2006/main', 'a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
        for tree in (old, new):
            for node in tree.xpath(f'.//p:sp[p:nvSpPr/p:cNvPr[@id="{box.shape_id}"]]/p:txBody/a:p/a:r/a:t', namespaces=ns): node.text = 'MATCH'
        assert etree.tostring(old, method='c14n') == etree.tostring(new, method='c14n')
    grouped = session.replace_text(draft, 1, f'/slide[1]/group[@id={group_id}]/shape[@id={inner_id}]/paragraph[1]', 'Grouped', 'Inside')
    updated_group = next(shape for shape in Presentation(grouped['file']).slides[0].shapes if shape.shape_id == group_id)
    assert updated_group.shapes[0].text == 'Inside'
    try:
        session.replace_text(draft, 0, '/slide[1]/shape[1]', 'Hello', 'stale')
        raise AssertionError('Stale replacement succeeded')
    except ValueError as error:
        assert 'conflict' in str(error)
    assert session.info(draft)['latest_revision'] == 2
    duplicate = root / 'duplicate.pptx'
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(duplicate, 'w') as dst:
        for entry in src.infolist():
            data = src.read(entry)
            if entry.filename == part:
                tree = etree.fromstring(data); ns = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main'}
                shape_tree = tree.find('p:cSld/p:spTree', ns)
                matching = shape_tree.xpath(f'p:sp[p:nvSpPr/p:cNvPr[@id="{box.shape_id}"]]', namespaces=ns)
                shape_tree.append(copy.deepcopy(matching[0])); data = etree.tostring(tree, encoding='UTF-8', xml_declaration=True, standalone=True)
            dst.writestr(entry, data)
    duplicate_draft = root / 'duplicate-draft'; session.start(duplicate_draft, source=duplicate)
    try:
        session.replace_text(duplicate_draft, 0, f'/slide[1]/shape[@id={box.shape_id}]/paragraph[1]', 'Hello', 'bad')
        raise AssertionError('Duplicate shape ID accepted')
    except ValueError as error:
        assert 'exactly one' in str(error)
    assert session.info(duplicate_draft)['latest_revision'] == 0
    shared = root / 'shared.pptx'
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(shared, 'w') as dst:
        for entry in src.infolist():
            data = src.read(entry)
            if entry.filename == 'ppt/presentation.xml':
                tree = etree.fromstring(data); ns = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main'}
                items = tree.find('p:sldIdLst', ns); rid = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
                items[1].set(rid, items[0].get(rid)); data = etree.tostring(tree, encoding='UTF-8', xml_declaration=True, standalone=True)
            dst.writestr(entry, data)
    shared_draft = root / 'shared-draft'; session.start(shared_draft, source=shared)
    try:
        session.replace_text(shared_draft, 0, '/slide[1]/shape[1]/paragraph[1]', 'Hello', 'bad')
        raise AssertionError('Shared slide part accepted')
    except ValueError as error:
        assert 'multiple slides' in str(error)
    assert session.info(shared_draft)['latest_revision'] == 0
    alternate = root / 'alternate.pptx'
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(alternate, 'w') as dst:
        for entry in src.infolist():
            data = src.read(entry)
            if entry.filename == part:
                tree = etree.fromstring(data); ns = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main'}
                shape_tree = tree.find('p:cSld/p:spTree', ns)
                shape_tree.append(etree.Element('{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent'))
                data = etree.tostring(tree, encoding='UTF-8', xml_declaration=True, standalone=True)
            dst.writestr(entry, data)
    alternate_draft = root / 'alternate-draft'; session.start(alternate_draft, source=alternate)
    try:
        session.replace_text(alternate_draft, 0, '/slide[1]/shape[1]/paragraph[1]', 'Hello', 'bad')
        raise AssertionError('Alternate content accepted')
    except ValueError as error:
        assert 'alternate content' in str(error)
    assert session.info(alternate_draft)['latest_revision'] == 0
print('Slides replacement smoke passed: reordered slides, groups, run formatting and protected content')
