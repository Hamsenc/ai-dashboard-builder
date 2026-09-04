"""Fixture kiểm thử các field trình bày Phase 2 (tile_agg/format/top_n/col_span).
Số liệu vẫn là số THẬT của dashboard doanh_thu, chỉ ghép lại và khai thêm field."""
import json, collections

src = json.load(open('preview/fixtures/doanh_thu.json', encoding='utf-8'))
by_name = {r['kpi_name']: r for r in src['results']}
gmv, profit, orders = by_name['GMV (Success)'], by_name['Lợi nhuận gộp'], by_name['Số lượng đơn hàng thành công']

def per_date(r):
    d = collections.defaultdict(float)
    for row in r['rows']:
        d[row[r['x_field']]] += float(row[r['y_field']] or 0)
    return d

g, p = per_date(gmv), per_date(profit)
margin_rows = [{'date': dt, 'margin_pct': round(p[dt] / g[dt] * 100, 2)}
               for dt in sorted(g) if g[dt]]

results = [
    dict(gmv),
    {'kpi_name': 'Biên lợi nhuận gộp', 'x_field': 'date', 'y_field': 'margin_pct',
     'series_field': '', 'rows': margin_rows},
    dict(orders),
    {**orders, 'kpi_name': 'Số đơn ngày gần nhất'},
]

kpis = [
    {'name': 'GMV (Success)', 'definition': by_name['GMV (Success)']['kpi_name'], 'status': 'Draft',
     'chart_type': 'line', 'tile_agg': 'sum', 'format': 'currency_vnd', 'top_n': 3, 'col_span': 12},
    {'name': 'Biên lợi nhuận gộp', 'definition': 'Lợi nhuận gộp / GMV theo ngày.', 'status': 'custom',
     'chart_type': 'line', 'tile_agg': 'sum', 'format': 'percent', 'top_n': 0, 'col_span': 6},
    {'name': 'Số lượng đơn hàng thành công', 'definition': 'SUM(count_order_success).', 'status': 'custom',
     'chart_type': 'bar', 'tile_agg': 'sum', 'format': 'number', 'top_n': 0, 'col_span': 6},
    {'name': 'Số đơn ngày gần nhất', 'definition': 'Số đơn thành công của mốc mới nhất.', 'status': 'custom',
     'chart_type': 'number', 'tile_agg': 'last', 'format': 'number', 'top_n': 0, 'col_span': 0},
]

out = {'blueprint': {**src['blueprint'], 'title': 'Kiểm thử trình bày Phase 2', 'kpis': kpis},
       'results': results,
       'default_start_date': src['default_start_date'], 'default_end_date': src['default_end_date']}
json.dump(out, open('preview/fixtures/phase2_demo.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('KPI:', [k['name'] for k in kpis])
print('margin sample:', margin_rows[:2])
