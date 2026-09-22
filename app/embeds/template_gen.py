"""Sinh sẵn 1 file HTML dashboard từ danh sách widget (KPI/Bar/Line/Table) + 1
data_query_spec — cho user KHÔNG biết code vẫn tạo được dashboard, thay vì phải tự
viết HTML rồi upload (xem app/api/embeds.py::generate_embed). Trang sinh ra gọi
fetch('data') giống hệt dashboard tự viết tay (app/api/embed_view.py không phân
biệt nguồn gốc file HTML), nên toàn bộ hạ tầng data_query_spec/cache/cost-guard có
sẵn dùng lại nguyên vẹn — module này chỉ lo phần HTML/JS hiển thị.

KHÔNG hỗ trợ sửa lại widget sau khi tạo (giống hệt quy ước đã có: sửa
data_query_spec không đổi file HTML, muốn đổi nội dung phải revoke + tạo lại)."""

from __future__ import annotations

import html
import json
from typing import Any

_WIDGET_TYPES = {"kpi", "bar", "line", "table"}
_KPI_AGG = {"sum", "count", "avg"}
_MAX_WIDGETS = 12


class InvalidWidgetError(ValueError):
    """Widget sai cấu trúc, hoặc tham chiếu cột không có trong data_query_spec — lỗi 400."""


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise InvalidWidgetError(message)


def validate_widgets(widgets: Any, available_fields: set[str]) -> None:
    """available_fields = columns ∪ aggregations[].alias của data_query_spec đã chọn
    — mọi cột widget tham chiếu phải nằm trong tập này (đúng những gì /d/{id}/data
    sẽ trả về), không suy đoán tên cột khác."""
    _require(isinstance(widgets, list) and widgets, "Cần ít nhất 1 biểu đồ/widget.")
    _require(len(widgets) <= _MAX_WIDGETS, f"Tối đa {_MAX_WIDGETS} widget cho 1 dashboard.")
    for w in widgets:
        _require(isinstance(w, dict), "Mỗi widget phải là 1 object.")
        wtype = w.get("type")
        _require(wtype in _WIDGET_TYPES, f"Loại widget không hợp lệ: {wtype!r}.")
        _require(isinstance(w.get("title"), str) and w["title"].strip(), "Mỗi widget cần có tiêu đề.")

        if wtype == "kpi":
            _require(w.get("value_column") in available_fields, f"Cột giá trị KPI không hợp lệ: {w.get('value_column')!r}.")
            _require(w.get("agg", "sum") in _KPI_AGG, f"agg không hợp lệ: {w.get('agg')!r}.")
        elif wtype in ("bar", "line"):
            _require(w.get("label_column") in available_fields, f"Cột nhãn không hợp lệ: {w.get('label_column')!r}.")
            _require(w.get("value_column") in available_fields, f"Cột giá trị không hợp lệ: {w.get('value_column')!r}.")
        # table: không cần cột riêng, tự hiển thị mọi cột trả về từ data_query_spec.


_HTML_TEMPLATE = """<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>%%TITLE%%</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=DM+Mono:wght@500;600&display=swap" rel="stylesheet" />
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; font-family: 'DM Sans', sans-serif; background: #f0f4f8; color: #1e293b; padding: 28px 32px; }
  h1 { font-size: 26px; font-weight: 700; margin: 0 0 20px; }
  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 20px; }
  .kpi-grid:empty { display: none; }
  .kpi-card { background: #fff; border-radius: 16px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,.05); }
  .kpi-label { font-size: 11px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; color: #64748b; }
  .kpi-number { font-family: 'DM Mono', monospace; font-size: 30px; font-weight: 700; margin-top: 6px; }
  .chart-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 16px; }
  .chart-card { background: #fff; border-radius: 16px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,.05); }
  .chart-header { margin-bottom: 14px; }
  .chart-title { font-size: 15px; font-weight: 700; }
  .ch-wrap canvas { width: 100% !important; }
  .data-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  .data-table th, .data-table td { padding: 6px 10px; border-bottom: 1px solid #e2e8f0; text-align: left; }
  .data-table th { font-weight: 700; color: #64748b; font-size: 11px; text-transform: uppercase; }
  .data-table td { font-family: 'DM Mono', monospace; }
  #loading { color: #64748b; font-size: 13px; }
  @keyframes fadeUp { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
  .fade-up { animation: fadeUp .4s ease both; }
  @media (max-width: 720px) { body { padding: 18px; } .kpi-grid, .chart-grid { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<h1>%%TITLE%%</h1>
<p id="loading">Đang tải dữ liệu...</p>
<div class="kpi-grid" id="kpi-grid"></div>
<div class="chart-grid" id="chart-grid"></div>
<script>
var WIDGETS = %%WIDGETS_JSON%%;
var COLORS = ['#7c3aed', '#0891b2', '#059669', '#e11d48', '#d97706'];

function fmt(n) {
  if (n === null || n === undefined || isNaN(n)) return '—';
  var neg = n < 0; n = Math.abs(n);
  var s;
  if (n >= 1e9) s = (n / 1e9).toLocaleString('vi-VN', { maximumFractionDigits: 1 }) + ' tỷ';
  else if (n >= 1e6) s = (n / 1e6).toLocaleString('vi-VN', { maximumFractionDigits: 1 }) + ' tr';
  else s = Math.round(n).toLocaleString('vi-VN');
  return (neg ? '-' : '') + s;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

function computeKpiValue(rows, col, agg) {
  var vals = rows.map(function (r) { return Number(r[col]); }).filter(function (v) { return !isNaN(v); });
  if (!vals.length) return 0;
  if (agg === 'count') return vals.length;
  var sum = vals.reduce(function (a, b) { return a + b; }, 0);
  return agg === 'avg' ? sum / vals.length : sum;
}

function renderKpi(w, rows, color) {
  var card = document.createElement('div');
  card.className = 'kpi-card fade-up';
  card.style.borderLeft = '4px solid ' + color;
  var value = computeKpiValue(rows, w.value_column, w.agg || 'sum');
  card.innerHTML = '<div class="kpi-label">' + escapeHtml(w.title) + '</div>'
    + '<div class="kpi-number">' + fmt(value) + '</div>';
  document.getElementById('kpi-grid').appendChild(card);
}

function renderChart(w, rows, color) {
  var card = document.createElement('div');
  card.className = 'chart-card fade-up';
  card.innerHTML = '<div class="chart-header"><div class="chart-title">' + escapeHtml(w.title) + '</div></div>'
    + '<div class="ch-wrap" style="height:280px"><canvas></canvas></div>';
  document.getElementById('chart-grid').appendChild(card);
  var labels = rows.map(function (r) { return r[w.label_column]; });
  var values = rows.map(function (r) { return Number(r[w.value_column]) || 0; });
  new Chart(card.querySelector('canvas'), {
    type: w.type,
    data: { labels: labels, datasets: [{ label: escapeHtml(w.title), data: values,
      backgroundColor: w.type === 'bar' ? color : 'transparent', borderColor: color, borderWidth: 2, fill: false, tension: 0.3,
      pointRadius: w.type === 'line' ? 0 : undefined, pointHoverRadius: w.type === 'line' ? 3 : undefined }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { autoSkip: true, maxTicksLimit: 10, maxRotation: 45, minRotation: 0 } },
        y: { ticks: { callback: function (v) { return fmt(v); } } },
      } },
  });
}

function renderTable(w, rows, columns) {
  var card = document.createElement('div');
  card.className = 'chart-card fade-up';
  var thead = '<tr>' + columns.map(function (c) { return '<th>' + escapeHtml(c) + '</th>'; }).join('') + '</tr>';
  var tbody = rows.slice(0, 50).map(function (r) {
    return '<tr>' + columns.map(function (c) {
      var v = r[c];
      return '<td>' + (typeof v === 'number' ? fmt(v) : escapeHtml(v == null ? '' : String(v))) + '</td>';
    }).join('') + '</tr>';
  }).join('');
  card.innerHTML = '<div class="chart-header"><div class="chart-title">' + escapeHtml(w.title) + '</div></div>'
    + '<div style="overflow:auto"><table class="data-table"><thead>' + thead + '</thead><tbody>' + tbody + '</tbody></table></div>';
  document.getElementById('chart-grid').appendChild(card);
}

function render(payload) {
  document.getElementById('loading').hidden = true;
  var rows = payload.rows || [];
  var columns = payload.columns || [];
  WIDGETS.forEach(function (w, i) {
    var color = COLORS[i % COLORS.length];
    if (w.type === 'kpi') renderKpi(w, rows, color);
    else if (w.type === 'table') renderTable(w, rows, columns);
    else renderChart(w, rows, color);
  });
}

fetch('data').then(function (r) {
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}).then(render).catch(function (err) {
  document.getElementById('loading').textContent = 'Lỗi tải dữ liệu: ' + err.message;
});
</script>
</body>
</html>
"""


def render_dashboard_html(title: str, widgets: list[dict[str, Any]]) -> str:
    widgets_json = json.dumps(widgets, ensure_ascii=False).replace("</", "<\\/")
    return _HTML_TEMPLATE.replace("%%TITLE%%", html.escape(title)).replace("%%WIDGETS_JSON%%", widgets_json)
