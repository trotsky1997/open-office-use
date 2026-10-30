"""Exercise chart cache comparisons against a real workbook and revisions."""
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from lxml import etree
from openpyxl import load_workbook
import xlsxwriter
import chart_cache
import officecli_backend
import review_bundle
import session

C=chart_cache.C
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp); source=root/'chart.xlsx'; draft=root/'draft'
    book=xlsxwriter.Workbook(str(source)); sheet=book.add_worksheet("Sales Data")
    sheet.write_column('A1',['Month','Jan','Feb']); sheet.write_column('B1',['Revenue',10,20])
    chart=book.add_chart({'type':'column'}); chart.set_title({'name':'Revenue'}); chart.add_series({'name':"='Sales Data'!$B$1",'categories':"='Sales Data'!$A$2:$A$3",'values':"='Sales Data'!$B$2:$B$3"}); sheet.insert_chart('D2',chart); book.close()
    baseline=chart_cache.scan(source); assert baseline['chart_parts_total']==1 and baseline['complete'] and baseline['mismatch_references']==0,baseline
    session.start(draft,source=source); changed=session.replace_text(draft,0,'/Sales Data/A2','Jan','March')
    result=session.scan_chart_caches(draft,1); assert result['mismatch_references']==1 and result['complete'],result
    mismatch=next(r for r in result['charts'][0]['references'] if r['status']=='mismatch')
    assert mismatch['role']=='cat' and mismatch['mismatches'][0]['cell']=='A2' and mismatch['mismatches'][0]['stored_value']=='March' and mismatch['mismatches'][0]['cached_value']=='Jan'
    assert session.scan_chart_caches(draft,0)['mismatch_references']==0
    assert load_workbook(changed['file'])['Sales Data']['A2'].value=='March'
    synced=session.sync_chart_cache(draft,1,result['charts'][0]['part'],mismatch['index'])
    assert synced['revision']==2 and synced['updated_points']==1 and synced['source_formula_cells']==0
    assert session.scan_chart_caches(draft,2)['mismatch_references']==0
    with zipfile.ZipFile(changed['file']) as before,zipfile.ZipFile(synced['output']) as after:
        changed_parts={name for name in before.namelist() if before.read(name)!=after.read(name)}
        assert changed_parts=={'xl/charts/chart1.xml'},changed_parts
    validation_code, validation, _=officecli_backend.invoke('validate',synced['output']); assert validation_code==0 and validation['success'],validation
    try: session.sync_chart_cache(draft,1,result['charts'][0]['part'],mismatch['index'])
    except ValueError as exc: assert 'conflict' in str(exc)
    else: raise AssertionError('Stale sync accepted')
    signed=root/'signed.xlsx'
    with zipfile.ZipFile(changed['file']) as before,zipfile.ZipFile(signed,'w') as after:
        for entry in before.infolist(): after.writestr(entry,before.read(entry))
        after.writestr('_xmlsignatures/sig1.xml','<Signature/>')
    try: chart_cache.sync(signed,root/'signed-output.xlsx',result['charts'][0]['part'],mismatch['index'])
    except ValueError as exc: assert 'signed' in str(exc)
    else: raise AssertionError('Signed workbook sync accepted')
    assert not (root/'signed-output.xlsx').exists()
    def no_render(*_): raise RuntimeError('preview unavailable')
    bundle=review_bundle.create(changed['file'],root/'review',no_render,1)
    assert 'chart_cache_mismatch' in bundle['flags'] and 'render_pdf' in bundle['check_errors'],bundle
    report=json.loads(Path(bundle['report']).read_text()); assert report['checks']['chart_cache_scan']['result']['mismatch_references']==1
    cli=Path(__file__).with_name('open_office_use.py'); output=subprocess.run([sys.executable,str(cli),'session','scan-chart-caches',str(draft),'--revision','1'],capture_output=True,text=True,check=True)
    assert json.loads(output.stdout)['mismatch_references']==1
    cli_draft=root/'cli-draft'; session.start(cli_draft,source=changed['file'])
    cli_result=subprocess.run([sys.executable,str(cli),'session','sync-chart-cache',str(cli_draft),'--base','0','--part',result['charts'][0]['part'],'--reference',str(mismatch['index'])],capture_output=True,text=True,check=True)
    assert json.loads(cli_result.stdout)['updated_points']==1
    # Missing caches and unsupported external references must be visible as incomplete coverage.
    def rewrite(name, mutate):
        target=root/name
        with zipfile.ZipFile(source) as before,zipfile.ZipFile(target,'w') as after:
            for entry in before.infolist():
                data=before.read(entry)
                if entry.filename=='xl/charts/chart1.xml':
                    tree=etree.fromstring(data); mutate(tree); data=etree.tostring(tree,encoding='utf-8',xml_declaration=True)
                after.writestr(entry,data)
        return target
    def missing(tree):
        ref=tree.find('.//'+C+'cat/'+C+'strRef'); ref.remove(ref.find(C+'strCache'))
    missing_result=chart_cache.scan(rewrite('missing.xlsx',missing)); assert missing_result['missing_caches']==1 and not missing_result['complete']
    def external(tree): tree.find('.//'+C+'val/'+C+'numRef/'+C+'f').text="'[other.xlsx]Data'!$B$2:$B$3"
    external_result=chart_cache.scan(rewrite('external.xlsx',external)); assert external_result['unverified_references']>=1 and not external_result['complete']
    def escaped(tree): tree.find('.//'+C+'cat/'+C+'strRef/'+C+'strCache/'+C+'pt/'+C+'v').text='_x0041_'
    escape_result=chart_cache.scan(rewrite('escaped.xlsx',escaped)); assert not escape_result['complete'] and escape_result['unverified_references']>=1
    def missing_point(tree):
        cache=tree.find('.//'+C+'cat/'+C+'strRef/'+C+'strCache'); cache.remove(cache.find(C+'pt'))
    gap_source=rewrite('missing-point.xlsx',missing_point); gap=chart_cache.scan(gap_source); gap_ref=next(x for x in gap['charts'][0]['references'] if x['status']=='mismatch')
    try: chart_cache.sync(gap_source,root/'gap-output.xlsx',gap['charts'][0]['part'],gap_ref['index'])
    except ValueError as exc: assert 'missing points' in str(exc)
    else: raise AssertionError('Missing cache point accepted')
    assert not (root/'gap-output.xlsx').exists()
    def extension(tree): etree.SubElement(tree,C+'extLst')
    extension_result=chart_cache.scan(rewrite('extension.xlsx',extension)); assert extension_result['charts'][0]['extensions_present'] and not extension_result['complete']
    def extended_mismatch(tree):
        extension(tree); tree.find('.//'+C+'cat/'+C+'strRef/'+C+'strCache/'+C+'pt/'+C+'v').text='Wrong'
    extended_draft=root/'extension-draft'; session.start(extended_draft,source=rewrite('extended-mismatch.xlsx',extended_mismatch))
    extended=session.scan_chart_caches(extended_draft,0); extended_ref=next(r for r in extended['charts'][0]['references'] if r['status']=='mismatch')
    try: session.sync_chart_cache(extended_draft,0,extended['charts'][0]['part'],extended_ref['index'])
    except ValueError as exc: assert 'extensions' in str(exc)
    else: raise AssertionError('Extended chart sync accepted')
    assert chart_cache.parse_reference("'O''Brien!Data'!$A$1:$A$2")[0]=="O'Brien!Data"
    assert chart_cache.parse_reference('Sheet!A1:B2') is None
    formula_source=root/'formula.xlsx'; book=xlsxwriter.Workbook(str(formula_source)); sheet=book.add_worksheet('Calc'); sheet.write_formula('A1','=5+5',None,10); sheet.write_number('A2',20)
    chart=book.add_chart({'type':'column'}); chart.add_series({'values':'=Calc!$A$1:$A$2'}); sheet.insert_chart('D2',chart); book.close()
    stale=root/'formula-stale.xlsx'
    with zipfile.ZipFile(formula_source) as before,zipfile.ZipFile(stale,'w') as after:
        for entry in before.infolist():
            data=before.read(entry)
            if entry.filename=='xl/charts/chart1.xml':
                tree=etree.fromstring(data); tree.find('.//'+C+'numRef/'+C+'numCache/'+C+'pt/'+C+'v').text='7'; data=etree.tostring(tree,encoding='utf-8',xml_declaration=True)
            after.writestr(entry,data)
    formula_draft=root/'formula-draft'; session.start(formula_draft,source=stale); view=session.scan_chart_caches(formula_draft,0); ref=next(x for x in view['charts'][0]['references'] if x['status']=='mismatch')
    try: session.sync_chart_cache(formula_draft,0,view['charts'][0]['part'],ref['index'])
    except ValueError as exc: assert 'formula' in str(exc).lower()
    else: raise AssertionError('Formula cache sync without opt-in accepted')
    formula_result=session.sync_chart_cache(formula_draft,0,view['charts'][0]['part'],ref['index'],allow_formula_caches=True)
    assert formula_result['source_formula_cells']==1 and formula_result['updated_points']==1 and session.scan_chart_caches(formula_draft,1)['mismatch_references']==0
print('Chart cache smoke passed: mismatch, baseline, revision, unsupported sources and review bundle')
