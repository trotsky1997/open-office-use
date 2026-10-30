"""Create editable PowerPoint charts with matching embedded data."""
import io
import copy
import tempfile
import zipfile
import subprocess
import sys
from pathlib import Path
from openpyxl import load_workbook
from pptx import Presentation
from pptx.enum.chart import XL_CHART_TYPE
import open_office_use
import officecli_backend
import slide_charts
import session

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); out = root/'charts.pptx'
    charts = [{'type':'chart','chart_type':'column','x':1,'y':1,'width':5,'height':3,'title':'Revenue','x_axis_title':'Quarter','y_axis_title':'USD','categories':['Q1','Q2','Q3'],'series':[{'name':'Revenue','values':[100,120,135],'color':'236B8E'},{'name':'Target','values':[90,110,130],'color':'62A894'}]},
              {'type':'chart','chart_type':'line','x':1,'y':4.5,'width':5,'height':2,'categories':['Q1','Q2','Q3'],'series':[{'name':'Growth','values':[0.1,None,0.2],'number_format':'0.0%','color':'BA5A32'}]}]
    charts[0]['value_axis_min'] = 0; charts[0]['value_axis_max'] = 150; charts[1]['value_axis_min'] = -0.1; charts[0]['description'] = 'Revenue compared with target'; charts[0]['show_values'] = True; charts[1]['show_values'] = False
    charts.append(dict(charts[0], chart_type='bar', x_axis_title='USD', y_axis_title='Quarter', show_values=True))
    pie = {'type':'chart','chart_type':'pie','x':1,'y':1,'width':5,'height':4,'title':'Mix','categories':['A','B','C'],'series':[{'name':'Share','values':[25,35,40]}],'point_colors':['236B8E','62A894','BA5A32'],'show_percent':True}
    open_office_use.author({'slides':[{'layout':'blank','elements':charts},{'layout':'blank','elements':[pie]}]},out)
    code, validation, _ = officecli_backend.invoke('validate',out); assert code==0 and validation['success'],validation
    deck = Presentation(out); first = deck.slides[0].shapes[0].chart; second = deck.slides[0].shapes[1].chart
    assert first.value_axis.minimum_scale == 0 and first.value_axis.maximum_scale == 150 and second.value_axis.minimum_scale == -0.1
    assert first.plots[0].data_labels.show_value is True and not second.plots[0].has_data_labels
    assert first.has_title and first.chart_title.text_frame.text == 'Revenue' and first.has_legend
    assert first.category_axis.axis_title.text_frame.text == 'Quarter' and first.value_axis.axis_title.text_frame.text == 'USD'
    assert tuple(first.series[0].values) == (100,120,135) and tuple(second.series[0].values) == (0.1,None,0.2)
    bar = deck.slides[0].shapes[2].chart
    assert bar.value_axis.minimum_scale == 0 and bar.value_axis.maximum_scale == 150
    assert bar.plots[0].data_labels.show_value is True
    assert bar.chart_type == XL_CHART_TYPE.BAR_CLUSTERED and tuple(bar.series[0].values) == (100,120,135)
    assert bar.value_axis.axis_title.text_frame.text == 'USD' and bar.category_axis.axis_title.text_frame.text == 'Quarter'
    assert bar.series[0].format.fill.fore_color.rgb == (0x23,0x6b,0x8e)
    bar_book = load_workbook(io.BytesIO(bar.part.chart_workbook.xlsx_part.blob)); assert bar_book.active['B2'].value == 100; bar_book.close()
    pie_chart = deck.slides[1].shapes[0].chart
    assert pie_chart.chart_type == XL_CHART_TYPE.PIE and pie_chart.has_legend
    assert pie_chart.plots[0].data_labels.show_percentage and not pie_chart.plots[0].data_labels.show_value
    assert pie_chart.series[0].points[1].format.fill.fore_color.rgb == (0x62,0xa8,0x94)
    inventory = slide_charts.inspect(out); assert inventory['charts'][3]['reconciliation']['status'] == 'match', inventory
    column_axis = inventory['charts'][0]['axis_inventory']; bar_axis = inventory['charts'][2]['axis_inventory']; pie_axis = inventory['charts'][3]['axis_inventory']
    assert column_axis['complete'] and next(axis for axis in column_axis['axes'] if axis['type'] == 'valAx')['minimum'] == 0
    assert next(axis for axis in column_axis['axes'] if axis['type'] == 'valAx')['maximum'] == 150
    assert bar_axis['complete'] and next(axis for axis in bar_axis['axes'] if axis['type'] == 'valAx')['position'] == 'b'
    assert pie_axis['complete'] and pie_axis['axes'] == []
    line_axis = next(axis for axis in inventory['charts'][1]['axis_inventory']['axes'] if axis['type'] == 'valAx')
    assert line_axis['minimum'] == -0.1 and line_axis['maximum'] is None
    scale = first.value_axis._element.find('{http://schemas.openxmlformats.org/drawingml/2006/chart}scaling')
    scale.find('{http://schemas.openxmlformats.org/drawingml/2006/chart}max').set('val', 'NaN')
    broken_axis = slide_charts.axis_inventory(first)
    assert not broken_axis['complete'] and 'invalid_axis_maximum' in broken_axis['issues'], broken_axis
    malformed = root/'malformed-axis.pptx'; deck.save(malformed)
    malformed_report = slide_charts.inspect(malformed)
    assert not malformed_report['complete'] and 'invalid_axis_maximum' in malformed_report['charts'][0]['axis_inventory']['issues']
    assert inventory['charts'][0]['description'] == 'Revenue compared with target' and not inventory['charts'][0]['description_truncated']
    axis_draft = root/'axis-draft'; session.start(axis_draft,source=out)
    chart_info = inventory['charts'][0]; axis_id = next(axis['id'] for axis in column_axis['axes'] if axis['type'] == 'valAx')
    for minimum, maximum in [(True,150), (0,float('inf')), (100,100), (200,100)]:
        try: session.set_slide_chart_axis_bounds(axis_draft,0,chart_info['chart_part'],axis_id,minimum,maximum)
        except ValueError: pass
        else: raise AssertionError('Invalid axis bounds accepted')
    try: session.set_slide_chart_axis_bounds(axis_draft,0,chart_info['chart_part'],axis_id,0,200,'0'*64)
    except ValueError: pass
    else: raise AssertionError('Stale axis snapshot accepted')
    assert session.info(axis_draft)['latest_revision'] == 0
    edited = session.set_slide_chart_axis_bounds(axis_draft,0,chart_info['chart_part'],axis_id,0,200,inventory['snapshot_sha256'])
    current = session.inspect_slide_charts(axis_draft,1); changed_axis = next(axis for axis in current['charts'][0]['axis_inventory']['axes'] if axis['id'] == axis_id)
    assert changed_axis['minimum'] == 0 and changed_axis['maximum'] == 200 and edited['affected_paths'] == [chart_info['path']]
    assert current['charts'][0]['reconciliation']['status'] == 'match'
    with zipfile.ZipFile(out) as before, zipfile.ZipFile(edited['output']) as after:
        assert all(before.read(name) == after.read(name) for name in before.namelist() if name != chart_info['chart_part'].lstrip('/'))
    code, validation, _ = officecli_backend.invoke('validate',edited['output']); assert code == 0 and validation['success'], validation
    cli = Path(open_office_use.__file__); subprocess.run([sys.executable,str(cli),'session','set-slide-chart-axis-bounds',str(axis_draft),'--base','1','--part',chart_info['chart_part'],'--axis-id',axis_id,'--minimum','auto','--maximum','auto'],capture_output=True,text=True,check=True)
    cleared = session.inspect_slide_charts(axis_draft,2); cleared_axis = next(axis for axis in cleared['charts'][0]['axis_inventory']['axes'] if axis['id'] == axis_id)
    assert cleared_axis['minimum'] is None and cleared_axis['maximum'] is None
    shared_source = root/'shared-axis.pptx'; shared_deck = Presentation(out); original = shared_deck.slides[0].shapes[0]
    duplicate = copy.deepcopy(original._element); duplicate.nvGraphicFramePr.cNvPr.set('id','1000'); original._element.addnext(duplicate); shared_deck.save(shared_source)
    shared_inventory = slide_charts.inspect(shared_source); shared_charts = [item for item in shared_inventory['charts'] if item.get('chart_part') == chart_info['chart_part']]
    assert len(shared_charts) == 2
    shared_draft = root/'shared-axis-draft'; session.start(shared_draft,source=shared_source)
    shared_edit = session.set_slide_chart_axis_bounds(shared_draft,0,chart_info['chart_part'],axis_id,0,175,shared_inventory['snapshot_sha256'])
    assert len(shared_edit['affected_paths']) == 2 and shared_edit['affected_paths_complete']
    log_source = root/'log-axis.pptx'; log_deck = Presentation(out); scaling = log_deck.slides[0].shapes[0].chart.value_axis._element.find('{http://schemas.openxmlformats.org/drawingml/2006/chart}scaling')
    from lxml import etree
    scaling.insert(0,etree.Element('{http://schemas.openxmlformats.org/drawingml/2006/chart}logBase',val='10'))
    scaling.find('{http://schemas.openxmlformats.org/drawingml/2006/chart}min').set('val','1'); log_deck.save(log_source)
    log_draft = root/'log-axis-draft'; session.start(log_draft,source=log_source)
    try: session.set_slide_chart_axis_bounds(log_draft,0,chart_info['chart_part'],axis_id,0,100)
    except ValueError: pass
    else: raise AssertionError('Nonpositive logarithmic bound accepted')
    assert session.info(log_draft)['latest_revision'] == 0
    chart_draft = root/'chart-description'; session.start(chart_draft,source=out)
    chart_target = inventory['charts'][0]
    result = session.set_slide_description(chart_draft,0,chart_target['path'],'Updated chart',inventory['snapshot_sha256'])
    updated_inventory = slide_charts.inspect(result['file'])
    assert updated_inventory['charts'][0]['description'] == 'Updated chart' and updated_inventory['charts'][0]['reconciliation']['status'] == 'match', updated_inventory
    code, validation, _ = officecli_backend.invoke('validate',result['file']); assert code == 0 and validation['success'], validation
    book = load_workbook(io.BytesIO(first.part.chart_workbook.xlsx_part.blob)); ws = book.active
    assert [ws.cell(i,1).value for i in range(2,5)] == ['Q1','Q2','Q3'] and [ws.cell(i,2).value for i in range(2,5)] == [100,120,135]
    assert first.series[0].format.fill.fore_color.rgb == (0x23,0x6b,0x8e)
    assert Path(open_office_use.render(out,root/'render')).read_bytes().startswith(b'%PDF')
    bad_cases = [dict(charts[0],value_axis_min=True),dict(charts[0],value_axis_max=float('inf')),dict(charts[0],value_axis_min=150),dict(charts[0],value_axis_min=200,value_axis_max=100),dict(pie,value_axis_min=0),dict(charts[0],description=42),dict(charts[0],description='x'*1001),dict(charts[0],show_values='yes'),dict(charts[0],categories=['Q1']),dict(pie,series=[{'name':'X','values':[0,0,0]}]),dict(pie,series=[{'name':'X','values':[-1,2,3]}]),dict(pie,point_colors=['236B8E']),dict(pie,x_axis_title='X'),dict(pie,show_percent='yes'),dict(charts[0],show_percent=True),dict(charts[0],series=[{'name':'Revenue','values':[1,float('nan'),3]}]),dict(charts[0],categories=['=1+1','Q2','Q3']),dict(charts[0],categories=['https://example.com','Q2','Q3'])]
    for index, chart in enumerate(bad_cases):
        bad = root/f'bad{index}.pptx'
        try: open_office_use.author({'slides':[{'layout':'blank','elements':[chart]}]},bad)
        except ValueError: pass
        else: raise AssertionError('Invalid chart data accepted')
        assert not bad.exists()
print('Slide chart author passed: editable data, cache, render and invalid input')
