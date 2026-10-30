"""Create a related report, workbook and presentation from one sample dataset."""
import argparse
from pathlib import Path

from open_office_use import author, render

parser = argparse.ArgumentParser()
parser.add_argument('output', type=Path, help='new output directory')
args = parser.parse_args()
root = args.output.resolve()
root.mkdir(parents=True, exist_ok=False)

quarters = [('Q1', 100), ('Q2', 108), ('Q3', 115), ('Q4', 118)]
growth = (quarters[-1][1] / quarters[0][1] - 1) * 100
trend = f'{growth:.0f}%'
colors = {'ink': '183048', 'accent': '236B8E', 'muted': '526B7E'}

report = {'page_setup': {'size': 'a4', 'margins': {'top': 0.8, 'bottom': 0.8, 'left': 0.9, 'right': 0.9},
          'header': {'text': 'Example company | annual review'}, 'footer': {'text': 'Example data | page', 'page_number': True}},
          'blocks': [{'type': 'heading', 'text': 'Annual performance review', 'level': 1},
                     {'type': 'paragraph', 'runs': [{'text': 'Revenue rose '}, {'text': trend, 'bold': True, 'color': colors['accent']}, {'text': ' from Q1 to Q4. All values are illustrative and shown in $m.'}]},
                     {'type': 'heading', 'text': 'Quarterly revenue', 'level': 2},
                     {'type': 'table', 'header': True, 'header_fill': colors['accent'], 'header_color': 'FFFFFF', 'column_weights': [2, 1], 'rows': [['Quarter', 'Revenue ($m)']] + [[q, str(value)] for q, value in quarters]},
                     {'type': 'heading', 'text': 'Next steps', 'level': 2},
                     {'type': 'bullet', 'text': 'Review the drivers behind the second-half trend.'},
                     {'type': 'bullet', 'text': 'Confirm the next-quarter plan with the finance team.'}]}

workbook = {'ranges': {'Revenue': [{'start': 'A1', 'values': [['Quarter', 'Revenue ($m)']] + [[q, value] for q, value in quarters]}]},
            'sheet_options': {'Revenue': {'column_widths': {'A': 18, 'B': 20}, 'row_heights': {'1': 25}, 'freeze_panes': 'B2',
                'formats': [{'range': 'A1:B1', 'bold': True, 'fill': colors['accent'], 'font_color': 'FFFFFF'}, {'range': 'B2:B5', 'number_format': '#,##0'}],
                'fit_to_page': True, 'print_options': {'paper': 'a4', 'orientation': 'landscape', 'area': 'A1:O20'},
                'charts': [{'type': 'column', 'data': 'B1:B5', 'categories': 'A2:A5', 'anchor': 'D2', 'title': 'Quarterly revenue ($m)', 'width': 15, 'height': 8, 'series_colors': [colors['accent']], 'legend': False, 'y_min': 0}]}}}

def box(text, x, y, w, h, size, color, bold=False):
    return {'type': 'textbox', 'x': x, 'y': y, 'width': w, 'height': h, 'text': text, 'font': 'Arial', 'font_size': size, 'color': color, 'bold': bold}

slides = {'slide_size': {'width': 13.333, 'height': 7.5}, 'slides': [
    {'layout': 'blank', 'background': 'F5F8FC', 'notes': 'All figures are illustrative. Revenue is in millions of dollars.', 'elements': [
        box('Annual performance review', 0.8, 0.7, 11, 0.8, 32, colors['ink'], True),
        box('Quarterly revenue and priorities', 0.8, 1.6, 11, 0.6, 20, colors['muted']),
        box(trend, 0.8, 2.8, 3.5, 1, 48, colors['accent'], True),
        box('Q1 to Q4 revenue growth', 0.8, 3.9, 5, 0.6, 19, colors['ink']),
        {'type': 'chart', 'chart_type': 'line', 'x': 6, 'y': 2.2, 'width': 6, 'height': 4, 'title': 'Revenue ($m)', 'categories': [q for q, _ in quarters], 'series': [{'name': 'Revenue', 'values': [v for _, v in quarters], 'color': colors['accent']}], 'legend': False}]},
    {'layout': 'blank', 'background': 'FFFFFF', 'notes': 'Discuss the causes of growth and align on the next-quarter plan.', 'elements': [
        box('Next steps', 0.8, 0.7, 11, 0.8, 32, colors['ink'], True),
        box('1. Review the drivers behind the second-half trend.', 1, 2, 11, 0.8, 22, colors['ink']),
        box('2. Confirm the next-quarter plan with finance.', 1, 3.1, 11, 0.8, 22, colors['ink'])]}]}

for name, spec in [('report.docx', report), ('revenue.xlsx', workbook), ('review.pptx', slides)]:
    path = root / name
    author(spec, path)
    print(f'{path}: {render(path, root / (path.stem + "-preview"))}')
