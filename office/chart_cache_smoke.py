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
    def no_render(*_): raise RuntimeError('preview unavailable')
    bundle=review_bundle.create(changed['file'],root/'review',no_render,1)
    assert 'chart_cache_mismatch' in bundle['flags'] and 'render_pdf' in bundle['check_errors'],bundle
    report=json.loads(Path(bundle['report']).read_text()); assert report['checks']['chart_cache_scan']['result']['mismatch_references']==1
    cli=Path(__file__).with_name('open_office_use.py'); output=subprocess.run([sys.executable,str(cli),'session','scan-chart-caches',str(draft),'--revision','1'],capture_output=True,text=True,check=True)
    assert json.loads(output.stdout)['mismatch_references']==1
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
    def extension(tree): etree.SubElement(tree,C+'extLst')
    extension_result=chart_cache.scan(rewrite('extension.xlsx',extension)); assert extension_result['charts'][0]['extensions_present'] and not extension_result['complete']
    assert chart_cache.parse_reference("'O''Brien!Data'!$A$1:$A$2")[0]=="O'Brien!Data"
    assert chart_cache.parse_reference('Sheet!A1:B2') is None
print('Chart cache smoke passed: mismatch, baseline, revision, unsupported sources and review bundle')
