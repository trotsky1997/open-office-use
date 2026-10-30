"""Inspect PowerPoint chart caches, revisions and bounded failure modes."""
import hashlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from lxml import etree
from openpyxl import load_workbook
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.util import Inches
import open_office_use
import officecli_backend
import session
import slide_charts
import review_bundle

with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp); source=root/'chart.pptx'
    spec={'slides':[{'layout':'blank','elements':[{'type':'chart','chart_type':'column','x':1,'y':1,'width':6,'height':3,'categories':['Q1','Q2'],'series':[{'name':'Revenue','values':[100,120]}]}]}]}
    open_office_use.author(spec,source); result=slide_charts.inspect(source); chart=result['charts'][0]
    assert result['complete'] and result['snapshot_sha256']==hashlib.sha256(source.read_bytes()).hexdigest()
    assert chart['categories']==['Q1','Q2'] and chart['series'][0]['name']=='Revenue' and chart['series'][0]['values']==[100,120]
    assert chart['series'][0]['references']['val']['formula']=='Sheet1!$B$2:$B$3' and chart['workbook']['status']=='embedded'
    assert chart['reconciliation']['status']=='match' and chart['reconciliation']['complete']
    assert chart['reconciliation']['formula_freshness']=='unknown'
    literal = root/'literal-chart.pptx'
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(literal,'w') as dst:
        for entry in src.infolist():
            data=src.read(entry.filename)
            if entry.filename == chart['chart_part'].lstrip('/'):
                tree=etree.fromstring(data); ser=tree.find('.//'+slide_charts.C+'ser')
                tx=ser.find(slide_charts.C+'tx'); tx.clear(); etree.SubElement(tx,slide_charts.C+'v').text='Revenue'
                for role, ref_tag, cache_tag, literal_tag in [('cat','strRef','strCache','strLit'),('val','numRef','numCache','numLit')]:
                    parent=ser.find(slide_charts.C+role); reference=parent.find(slide_charts.C+ref_tag); cache=reference.find(slide_charts.C+cache_tag)
                    reference.remove(cache); cache.tag=slide_charts.C+literal_tag; parent.replace(reference,cache)
                external=tree.find(slide_charts.C+'externalData')
                if external is not None: tree.remove(external)
                data=etree.tostring(tree)
            dst.writestr(entry,data)
    literal_report=slide_charts.inspect(literal); literal_chart=literal_report['charts'][0]
    assert literal_report['complete'] and literal_chart['workbook']['status']=='absent' and literal_chart['series'][0]['values']==[100,120]
    assert literal_chart['categories']==['Q1','Q2'] and all(literal_chart['series'][0]['references'][role]['status']=='literal' for role in ('tx','cat','val'))
    text_draft=root/'literal-text-draft'; session.start(text_draft,source=literal)
    assert literal_chart['series'][0]['name']=='Revenue'
    for text in ('', 'x'*256, 'bad\x01', 'bad\nline'):
        try: session.set_slide_chart_literal_text(text_draft,0,literal_chart['chart_part'],'series_name',text,series=1)
        except ValueError: pass
        else: raise AssertionError('Invalid literal chart text accepted')
    try: session.set_slide_chart_literal_text(text_draft,0,literal_chart['chart_part'],'category','New',point=1,expected_sha256='0'*64)
    except ValueError: pass
    else: raise AssertionError('Stale chart text snapshot accepted')
    changed_name=session.set_slide_chart_literal_text(text_draft,0,literal_chart['chart_part'],'series_name','Sales',series=1,expected_sha256=literal_report['snapshot_sha256'])
    assert session.inspect_slide_charts(text_draft,1)['charts'][0]['series'][0]['name']=='Sales'
    with zipfile.ZipFile(literal) as before, zipfile.ZipFile(changed_name['output']) as after:
        assert all(before.read(name)==after.read(name) for name in before.namelist() if name != literal_chart['chart_part'].lstrip('/'))
    cli=Path(__file__).with_name('open_office_use.py')
    command=[sys.executable,str(cli),'session','set-slide-chart-literal-text',str(text_draft),'--base','1','--part',literal_chart['chart_part'],'--kind','category','--point','1','--text','North & East']
    assert json.loads(subprocess.run(command,capture_output=True,text=True,check=True).stdout)['revision']==2
    assert session.inspect_slide_charts(text_draft,2)['charts'][0]['categories']==['North & East','Q2']
    multi=root/'literal-multi.pptx'
    with zipfile.ZipFile(literal) as src,zipfile.ZipFile(multi,'w') as dst:
        for entry in src.infolist():
            data=src.read(entry.filename)
            if entry.filename==literal_chart['chart_part'].lstrip('/'):
                tree=etree.fromstring(data); ser=tree.find('.//'+slide_charts.C+'ser'); duplicate=copy.deepcopy(ser)
                duplicate.find(slide_charts.C+'idx').set('val','1'); duplicate.find(slide_charts.C+'order').set('val','1'); ser.addnext(duplicate); data=etree.tostring(tree)
            dst.writestr(entry,data)
    multi_draft=root/'literal-multi-draft'; session.start(multi_draft,source=multi)
    session.set_slide_chart_literal_text(multi_draft,0,literal_chart['chart_part'],'category','Revised',point=2)
    with zipfile.ZipFile(multi_draft/'revision-000001.pptx') as archive:
        tree=etree.fromstring(archive.read(literal_chart['chart_part'].lstrip('/')))
        labels=tree.findall('.//'+slide_charts.C+'cat/'+slide_charts.C+'strLit/'+slide_charts.C+'pt[@idx="1"]/'+slide_charts.C+'v')
        assert len(labels)==2 and all(node.text=='Revised' for node in labels)
    mismatch=root/'literal-mismatch.pptx'
    with zipfile.ZipFile(multi) as src,zipfile.ZipFile(mismatch,'w') as dst:
        for entry in src.infolist():
            data=src.read(entry.filename)
            if entry.filename==literal_chart['chart_part'].lstrip('/'):
                tree=etree.fromstring(data); nodes=tree.findall('.//'+slide_charts.C+'cat/'+slide_charts.C+'strLit/'+slide_charts.C+'pt[@idx="1"]/'+slide_charts.C+'v'); nodes[-1].text='Different'; data=etree.tostring(tree)
            dst.writestr(entry,data)
    mismatch_draft=root/'literal-text-mismatch'; session.start(mismatch_draft,source=mismatch)
    try: session.set_slide_chart_literal_text(mismatch_draft,0,literal_chart['chart_part'],'category','Revised',point=2)
    except ValueError: pass
    else: raise AssertionError('Divergent literal categories accepted')
    assert session.info(mismatch_draft)['latest_revision']==0
    literal_draft=root/'literal-draft'; session.start(literal_draft,source=literal)
    axis_id=next(item['id'] for item in literal_chart['axis_inventory']['axes'] if item['type']=='valAx')
    session.set_slide_chart_axis_bounds(literal_draft,0,literal_chart['chart_part'],axis_id,0,110,literal_report['snapshot_sha256'])
    assert session.inspect_slide_charts(literal_draft,1)['charts'][0]['axis_range_candidates']['count']==1
    point_draft=root/'literal-point-draft'; session.start(point_draft,source=literal)
    for bad in [(0,1,2),(1,3,2),(1,1,True),(1,1,float('inf'))]:
        try: session.set_slide_chart_literal_value(point_draft,0,literal_chart['chart_part'],*bad)
        except ValueError: pass
        else: raise AssertionError('Invalid literal point edit accepted')
    try: session.set_slide_chart_literal_value(point_draft,0,literal_chart['chart_part'],1,1,130,'0'*64)
    except ValueError: pass
    else: raise AssertionError('Stale literal chart snapshot accepted')
    assert session.info(point_draft)['latest_revision']==0
    point_edit=session.set_slide_chart_literal_value(point_draft,0,literal_chart['chart_part'],1,1,130,literal_report['snapshot_sha256'])
    assert point_edit['old_value']==100 and point_edit['affected_paths']==[literal_chart['path']]
    assert session.inspect_slide_charts(point_draft,1)['charts'][0]['series'][0]['values']==[130,120]
    with zipfile.ZipFile(literal) as before,zipfile.ZipFile(point_edit['output']) as after:
        assert all(before.read(name)==after.read(name) for name in before.namelist() if name != literal_chart['chart_part'].lstrip('/'))
    cli=Path(__file__).with_name('open_office_use.py')
    command=[sys.executable,str(cli),'session','set-slide-chart-literal-value',str(point_draft),'--base','1','--part',literal_chart['chart_part'],'--series','1','--point','2','--value','140']
    assert json.loads(subprocess.run(command,capture_output=True,text=True,check=True).stdout)['revision']==2
    assert session.inspect_slide_charts(point_draft,2)['charts'][0]['series'][0]['values']==[130,140]
    shared_literal=root/'shared-literal.pptx'; deck=Presentation(literal); shape=next(item for item in deck.slides[0].shapes if item.has_chart)
    duplicate=copy.deepcopy(shape._element); duplicate.nvGraphicFramePr.cNvPr.set('id','1000'); shape._element.addnext(duplicate); deck.save(shared_literal)
    shared_report=slide_charts.inspect(shared_literal); shared_draft=root/'shared-literal-draft'; session.start(shared_draft,source=shared_literal)
    shared_change=session.set_slide_chart_literal_value(shared_draft,0,literal_chart['chart_part'],1,1,145,shared_report['snapshot_sha256'])
    assert len(shared_change['affected_paths'])==2 and shared_change['affected_paths_complete']
    assert all(item['series'][0]['values'][0]==145 for item in session.inspect_slide_charts(shared_draft,1)['charts'])
    referenced_draft=root/'reference-point-draft'; session.start(referenced_draft,source=source)
    try: session.set_slide_chart_literal_value(referenced_draft,0,chart['chart_part'],1,1,130)
    except ValueError: pass
    else: raise AssertionError('Referenced chart value accepted')
    assert session.info(referenced_draft)['latest_revision']==0
    grid_draft=root/'grid-draft';session.start(grid_draft,source=source)
    grid=session.read_slide_chart_grid(grid_draft,0,chart['chart_part'],'Sheet1','B2:B3')
    assert grid['rows'][0][0]['value']==100 and grid['rows'][0][0]['editable']
    edited=session.edit_slide_chart_grid(grid_draft,0,chart['chart_part'],'Sheet1','B2:B3',[{'cell':'B2','value':'125'}])
    assert edited['revision']==1 and edited['chart_cache_effect']=='may_be_stale'
    assert session.read_slide_chart_grid(grid_draft,1,chart['chart_part'],'Sheet1','B2:B3')['rows'][0][0]['value']==125
    changed=session.inspect_slide_charts(grid_draft,1)['charts'][0]['reconciliation']
    changed_ref=next(item['index'] for item in changed['references'] if item['status']=='mismatch')
    session.sync_slide_chart_cache(grid_draft,1,chart['chart_part'],changed_ref)
    assert session.inspect_slide_charts(grid_draft,2)['charts'][0]['reconciliation']['status']=='match'
    assert session.read_slide_chart_grid(grid_draft,0,chart['chart_part'],'Sheet1','B2')['rows'][0][0]['value']==100
    try: session.edit_slide_chart_grid(grid_draft,0,chart['chart_part'],'Sheet1','B2',[{'cell':'B2','value':'200'}])
    except ValueError as exc: assert 'Revision conflict' in str(exc)
    else: raise AssertionError('Stale chart grid revision accepted')
    try: session.edit_slide_chart_grid(grid_draft,2,chart['chart_part'],'Sheet1','B2',[{'cell':'C2','value':'200'}])
    except ValueError: pass
    else: raise AssertionError('Out-of-range chart grid edit accepted')
    assert session.info(grid_draft)['latest_revision']==2
    grid_cli=root/'grid-cli'; session.start(grid_cli,source=source)
    cli=Path(__file__).with_name('open_office_use.py')
    cmd=[sys.executable,str(cli),'session','edit-slide-chart-grid',str(grid_cli),'--base','0','--part',chart['chart_part'],'--sheet','Sheet1','--range','B2','--changes',json.dumps([{'cell':'B2','value':'130'}]),'--sync-caches']
    assert json.loads(subprocess.run(cmd,capture_output=True,text=True,check=True).stdout)['chart_cache_effect']=='matched_saved_values'
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(edited['file']) as after:
        changed_parts={name for name in before.namelist() if before.read(name)!=after.read(name)}
        assert changed_parts <= {chart['chart_part'].lstrip('/'), chart['workbook']['part'].lstrip('/')}
        assert chart['workbook']['part'].lstrip('/') in changed_parts
    atomic_draft=root/'atomic-draft'; session.start(atomic_draft,source=source)
    atomic=session.edit_slide_chart_grid(atomic_draft,0,chart['chart_part'],'Sheet1','B2',[{'cell':'B2','value':'125'}],True)
    assert atomic['revision']==1 and atomic['chart_cache_effect']=='matched_saved_values' and len(atomic['synchronized_references'])==1
    assert session.inspect_slide_charts(atomic_draft,1)['charts'][0]['reconciliation']['status']=='match'
    try: session.edit_slide_chart_grid(atomic_draft,1,chart['chart_part'],'Sheet1','B2',[{'cell':'B2','value':'=1+1'}],True)
    except ValueError: pass
    else: raise AssertionError('Unverifiable formula cache accepted')
    assert session.info(atomic_draft)['latest_revision']==1
    shared_source=root/'shared-original.pptx'; shared=root/'shared.pptx'
    shared_spec={'slides':[{'layout':'blank','elements':[dict(spec['slides'][0]['elements'][0]),dict(spec['slides'][0]['elements'][0])]}]}
    open_office_use.author(shared_spec,shared_source)
    with zipfile.ZipFile(shared_source) as src, zipfile.ZipFile(shared,'w') as dst:
        for entry in src.infolist():
            data=src.read(entry.filename)
            if entry.filename=='ppt/charts/_rels/chart2.xml.rels':
                tree=etree.fromstring(data); tree[0].set('Target','../embeddings/Microsoft_Excel_Sheet1.xlsx'); data=etree.tostring(tree)
            dst.writestr(entry,data)
    shared_draft=root/'shared-draft';session.start(shared_draft,source=shared)
    shared_before=session.inspect_slide_charts(shared_draft,0)['charts']
    assert len(shared_before)==2 and shared_before[0]['workbook']['part']==shared_before[1]['workbook']['part']
    shared_edit=session.edit_slide_chart_grid(shared_draft,0,shared_before[0]['chart_part'],'Sheet1','B2',[{'cell':'B2','value':'135'}],True)
    assert len(shared_edit['synchronized_references'])==2
    assert all(c['reconciliation']['status']=='match' and c['series'][0]['values'][0]==135 for c in session.inspect_slide_charts(shared_draft,1)['charts'])
    root_link=root/'root-link.pptx'
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(root_link,'w') as dst:
        for entry in src.infolist():
            data=src.read(entry.filename)
            if entry.filename=='_rels/.rels':
                tree=etree.fromstring(data); rel=etree.SubElement(tree,'{http://schemas.openxmlformats.org/package/2006/relationships}Relationship')
                rel.set('Id','rIdChartWorkbook'); rel.set('Type','http://schemas.openxmlformats.org/officeDocument/2006/relationships/package'); rel.set('Target',chart['workbook']['part']); data=etree.tostring(tree)
            dst.writestr(entry,data)
    root_draft=root/'root-draft'; session.start(root_draft,source=root_link)
    try: session.edit_slide_chart_grid(root_draft,0,chart['chart_part'],'Sheet1','B2',[{'cell':'B2','value':'130'}],True)
    except ValueError as exc: assert 'outside the inspected charts' in str(exc)
    else: raise AssertionError('Uninspected workbook relationship accepted')
    assert session.info(root_draft)['latest_revision']==0
    blank_spec={'slides':[{'layout':'blank','elements':[dict(spec['slides'][0]['elements'][0],series=[{'name':'Revenue','values':[100,None]}])]}]}
    blank_source=root/'blank-chart.pptx'; open_office_use.author(blank_spec,blank_source)
    blank_draft=root/'blank-chart-draft'; session.start(blank_draft,source=blank_source)
    blank_chart=session.inspect_slide_charts(blank_draft,0)['charts'][0]
    assert blank_chart['reconciliation']['status']=='match' and blank_chart['reconciliation']['complete']
    filled=session.edit_slide_chart_grid(blank_draft,0,blank_chart['chart_part'],'Sheet1','B3',[{'cell':'B3','value':'125'}],True)
    assert len(filled['synchronized_references'])==1 and session.inspect_slide_charts(blank_draft,1)['charts'][0]['series'][0]['values']==[100,125]
    cleared=session.edit_slide_chart_grid(blank_draft,1,blank_chart['chart_part'],'Sheet1','B2',[{'cell':'B2','value':''}],True)
    cleared_chart=session.inspect_slide_charts(blank_draft,2)['charts'][0]
    assert len(cleared['synchronized_references'])==1 and cleared_chart['reconciliation']['status']=='match' and cleared_chart['series'][0]['values']==[None,125]
    code, validation, _=officecli_backend.invoke('validate',cleared['file']); assert code==0 and validation['success'],validation
    merged_blank=root/'merged-blank.pptx'
    with zipfile.ZipFile(blank_source) as src, zipfile.ZipFile(merged_blank,'w') as dst:
        for entry in src.infolist():
            data=src.read(entry.filename)
            if entry.filename.startswith('ppt/embeddings/') and entry.filename.endswith('.xlsx'):
                book=load_workbook(io.BytesIO(data)); book.active.merge_cells('B2:B3')
                buffer=io.BytesIO();book.save(buffer);data=buffer.getvalue()
            dst.writestr(entry,data)
    merged_report=slide_charts.inspect(merged_blank)['charts'][0]['reconciliation']
    assert not merged_report['complete'] and any(ref.get('unverified_points',0)>0 for ref in merged_report['references'])
    mismatch=root/'mismatch.pptx'
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(mismatch,'w') as dst:
        for entry in src.infolist():
            data=src.read(entry.filename)
            if entry.filename.startswith('ppt/embeddings/') and entry.filename.endswith('.xlsx'):
                workbook=load_workbook(io.BytesIO(data)); workbook.active['B2']=999
                buffer=io.BytesIO(); workbook.save(buffer); data=buffer.getvalue()
            dst.writestr(entry,data)
    gap=root/'missing-point.pptx'
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(gap,'w') as dst:
        for entry in src.infolist():
            data=src.read(entry.filename)
            if entry.filename=='ppt/charts/chart1.xml':
                tree=etree.fromstring(data); cache=tree.find('.//'+slide_charts.C+'val/'+slide_charts.C+'numRef/'+slide_charts.C+'numCache'); cache.remove(cache.find(slide_charts.C+'pt')); data=etree.tostring(tree)
            dst.writestr(entry,data)
    gap_draft=root/'gap-draft';session.start(gap_draft,source=gap)
    gap_chart=session.inspect_slide_charts(gap_draft,0)['charts'][0]
    gap_ref=next(ref for ref in gap_chart['reconciliation']['references'] if ref['status']=='mismatch')
    assert gap_ref['mismatches'][0]['reason']=='missing_point'
    fixed=session.sync_slide_chart_cache(gap_draft,0,gap_chart['chart_part'],gap_ref['index'])
    assert fixed['updated_points']==1 and session.inspect_slide_charts(gap_draft,1)['charts'][0]['reconciliation']['status']=='match'
    code, validation, _=officecli_backend.invoke('validate',fixed['output']); assert code==0 and validation['success'],validation
    with zipfile.ZipFile(gap) as before,zipfile.ZipFile(fixed['output']) as after:
        assert {name for name in before.namelist() if before.read(name)!=after.read(name)}=={gap_chart['chart_part'].lstrip('/')}
    mixed=root/'mixed-unverified.pptx'
    with zipfile.ZipFile(mismatch) as src, zipfile.ZipFile(mixed,'w') as dst:
        for entry in src.infolist():
            data=src.read(entry.filename)
            if entry.filename.startswith('ppt/embeddings/') and entry.filename.endswith('.xlsx'):
                book=load_workbook(io.BytesIO(data)); book.active['B3']='=1+1'
                buffer=io.BytesIO(); book.save(buffer); data=buffer.getvalue()
            dst.writestr(entry,data)
    mixed_chart=slide_charts.inspect(mixed)['charts'][0]['reconciliation']
    assert mixed_chart['status']=='mismatch' and not mixed_chart['complete']
    mixed_reference=next(ref['index'] for ref in mixed_chart['references'] if ref.get('mismatch_count',0)>0 and ref.get('unverified_points',0)>0)
    mixed_draft=root/'mixed-draft'; session.start(mixed_draft,source=mixed)
    try: session.sync_slide_chart_cache(mixed_draft,0,chart['chart_part'],mixed_reference)
    except ValueError: pass
    else: raise AssertionError('Unverified cache reference accepted')
    assert session.info(mixed_draft)['latest_revision']==0
    def no_render(_source, _output): raise RuntimeError('render unavailable')
    mixed_review=review_bundle.create(mixed,root/'mixed-review',no_render)
    assert {'slide_chart_cache_mismatch','slide_chart_cache_unverified'} <= set(mixed_review['flags'])
    mismatch_atomic=root/'mismatch-atomic';session.start(mismatch_atomic,source=mismatch)
    try: session.edit_slide_chart_grid(mismatch_atomic,0,chart['chart_part'],'Sheet1','B2',[{'cell':'B2','value':'200'}],True)
    except ValueError: pass
    else: raise AssertionError('Pre-existing chart mismatch accepted')
    assert session.info(mismatch_atomic)['latest_revision']==0
    mismatch_report=slide_charts.inspect(mismatch)['charts'][0]['reconciliation']
    assert mismatch_report['status']=='mismatch' and mismatch_report['mismatch_count']>=1
    changed_reference=next(item['index'] for item in mismatch_report['references'] if item['status']=='mismatch')
    sync_draft=root/'sync-draft';session.start(sync_draft,source=mismatch)
    before_sync=session.inspect_slide_charts(sync_draft,0)
    try: session.sync_slide_chart_cache(sync_draft,0,chart['chart_part'],changed_reference,expected_sha256='0'*64)
    except ValueError as exc: assert 'snapshot changed' in str(exc)
    else: raise AssertionError('Wrong presentation chart snapshot accepted')
    assert session.info(sync_draft)['latest_revision']==0
    synced=session.sync_slide_chart_cache(sync_draft,0,chart['chart_part'],changed_reference,expected_sha256=before_sync['snapshot_sha256'])
    assert synced['updated_points']==1 and synced['revision']==1
    assert session.inspect_slide_charts(sync_draft,1)['charts'][0]['reconciliation']['status']=='match'
    with zipfile.ZipFile(mismatch) as before, zipfile.ZipFile(synced['output']) as after:
        assert {name for name in before.namelist() if before.read(name)!=after.read(name)} == {chart['chart_part'].lstrip('/')}
    cli_draft=root/'sync-cli'; session.start(cli_draft,source=mismatch)
    cli=Path(__file__).with_name('open_office_use.py'); call=subprocess.run([sys.executable,str(cli),'session','sync-slide-chart-cache',str(cli_draft),'--base','0','--part',chart['chart_part'],'--reference',str(changed_reference)],capture_output=True,text=True,check=True)
    assert json.loads(call.stdout)['updated_points']==1
    try: session.sync_slide_chart_cache(sync_draft,0,chart['chart_part'],changed_reference)
    except ValueError as exc: assert 'Revision conflict' in str(exc)
    else: raise AssertionError('Stale revision accepted')
    def failed_render(_snapshot, _out): raise RuntimeError('render unavailable')
    review=review_bundle.create(mismatch,root/'chart-review',failed_render)
    assert 'slide_chart_cache_mismatch' in review['flags']
    draft=root/'draft';session.start(draft,source=source);assert session.inspect_slide_charts(draft,0)['snapshot_sha256']==result['snapshot_sha256']
    cli=Path(__file__).with_name('open_office_use.py');call=subprocess.run([sys.executable,str(cli),'session','inspect-slide-charts',str(draft),'--revision','0'],capture_output=True,text=True,check=True)
    assert json.loads(call.stdout)['charts'][0]['series'][0]['values']==[100,120]
    external=root/'external.pptx'
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(external,'w') as dst:
        for entry in src.infolist():
            data=src.read(entry.filename)
            if entry.filename=='ppt/charts/_rels/chart1.xml.rels':
                tree=etree.fromstring(data); rel=tree[0]; rel.set('TargetMode','External'); rel.set('Target','https://example.invalid/workbook.xlsx'); data=etree.tostring(tree)
            dst.writestr(entry,data)
    external_report=slide_charts.inspect(external)
    assert not external_report['complete'] and external_report['charts'][0]['workbook']['status']=='external'
    missing=root/'missing.pptx'
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(missing,'w') as dst:
        for entry in src.infolist():
            data=src.read(entry.filename)
            if entry.filename=='ppt/charts/chart1.xml':
                tree=etree.fromstring(data); ref=tree.find('.//'+slide_charts.C+'val/'+slide_charts.C+'numRef'); ref.remove(ref.find(slide_charts.C+'numCache'));data=etree.tostring(tree)
            dst.writestr(entry,data)
    absent=slide_charts.inspect(missing);assert not absent['complete'] and any(item['reason']=='unsupported_or_missing_cache' for item in absent['issues'])
    assert not absent['charts'][0]['reconciliation']['complete']
    missing_draft=root/'missing-draft'; session.start(missing_draft,source=missing)
    try: session.sync_slide_chart_cache(missing_draft,0,chart['chart_part'],changed_reference)
    except ValueError: pass
    else: raise AssertionError('Missing cache accepted')
    assert session.info(missing_draft)['latest_revision']==0
    huge=root/'huge.pptx'
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(huge,'w') as dst:
        for entry in src.infolist():
            data=src.read(entry.filename)
            if entry.filename=='ppt/charts/chart1.xml':
                tree=etree.fromstring(data); tree.find('.//'+slide_charts.C+'val/'+slide_charts.C+'numRef/'+slide_charts.C+'numCache/'+slide_charts.C+'ptCount').set('val','99999999'); data=etree.tostring(tree)
            dst.writestr(entry,data)
    capped=slide_charts.inspect(huge);assert not capped['complete'] and capped['charts'][0]['series'][0]['values']==[] and capped['charts'][0]['series'][0]['values_truncated']
    many=root/'many.pptx'; deck=Presentation();slide=deck.slides.add_slide(deck.slide_layouts[6]);data=CategoryChartData();data.categories=[str(i) for i in range(201)];data.add_series('Values',list(range(201)));slide.shapes.add_chart(XL_CHART_TYPE.LINE,Inches(1),Inches(1),Inches(6),Inches(4),data);deck.save(many)
    bounded=slide_charts.inspect(many); assert not bounded['complete'] and bounded['charts'][0]['series'][0]['values_total']==201 and not bounded['charts'][0]['series'][0]['values']
print('Slide charts smoke passed: cached data, revision, missing and bounded caches')
