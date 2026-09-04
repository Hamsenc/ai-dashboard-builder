/* BẢN GỐC ĐÓNG BĂNG của renderer trước Phase 0 — CHỈ dùng cho preview harness để so
   sánh "trước / sau". KHÔNG sửa file này và KHÔNG bao giờ load nó trong app thật;
   mọi thay đổi đi vào app/web/renderer.js. */
window.DashboardRendererBaseline = (function () {
'use strict';
function formatCompact(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  const sign = n < 0 ? '-' : '';
  const abs = Math.abs(n);
  if (abs >= 1e12) return sign + trimZero((abs/1e12).toFixed(1)) + 'T';
  if (abs >= 1e9)  return sign + trimZero((abs/1e9).toFixed(1)) + 'B';
  if (abs >= 1e6)  return sign + trimZero((abs/1e6).toFixed(1)) + 'M';
  if (abs >= 1e3)  return sign + trimZero((abs/1e3).toFixed(1)) + 'K';
  return sign + abs.toLocaleString('en-US', {maximumFractionDigits: abs < 10 ? 2 : 0});
}
function trimZero(s) { return s.replace(/\.0$/, ''); }

function numericRows(r) {
  return r.rows.map(row => ({ x: row[r.x_field], y: Number(row[r.y_field]) }));
}

/* ---------- Stat tile ---------- */
function renderStatTile(container, r) {
  const pts = numericRows(r);
  const last = pts[pts.length - 1];
  const value = document.createElement('div');
  value.className = 'stat-value';
  value.textContent = last ? formatCompact(last.y) : '—';
  container.appendChild(value);

  if (pts.length > 1) {
    const first = pts[0];
    const delta = first.y !== 0 ? ((last.y - first.y) / Math.abs(first.y)) * 100 : null;
    if (delta !== null && Number.isFinite(delta)) {
      const deltaEl = document.createElement('div');
      deltaEl.className = 'stat-delta ' + (delta >= 0 ? 'up' : 'down');
      deltaEl.textContent = (delta >= 0 ? '▲ ' : '▼ ') + Math.abs(delta).toFixed(1) + '% so với ' + first.x;
      container.appendChild(deltaEl);
    }
    const spark = document.createElement('div');
    spark.className = 'stat-sparkline';
    container.appendChild(spark);
    renderSparkline(spark, pts);
  }
}

function renderSparkline(container, pts) {
  const w = 240, h = 40, pad = 3;
  const ys = pts.map(p => p.y);
  const min = Math.min(...ys), max = Math.max(...ys);
  const span = (max - min) || 1;
  const stepX = (w - pad * 2) / (pts.length - 1 || 1);
  const coords = pts.map((p, i) => [pad + i * stepX, h - pad - ((p.y - min) / span) * (h - pad * 2)]);
  const d = coords.map((c, i) => (i === 0 ? 'M' : 'L') + c[0].toFixed(1) + ',' + c[1].toFixed(1)).join(' ');

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.setAttribute('class', 'chart-svg');
  svg.style.height = h + 'px';

  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', d);
  path.setAttribute('fill', 'none');
  path.setAttribute('stroke', 'var(--series-1)');
  path.setAttribute('stroke-width', '2');
  path.setAttribute('stroke-linecap', 'round');
  path.setAttribute('stroke-linejoin', 'round');
  svg.appendChild(path);

  const last = coords[coords.length - 1];
  const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
  dot.setAttribute('cx', last[0]); dot.setAttribute('cy', last[1]); dot.setAttribute('r', 3);
  dot.setAttribute('fill', 'var(--series-1)');
  svg.appendChild(dot);

  container.appendChild(svg);
}

/* ---------- Chart.js: dựng dataset (gộp theo series_field nếu có) ---------- */
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
function seriesColor(i) {
  return cssVar(`--series-${(i % 8) + 1}`);
}

function buildSeries(r) {
  const seriesField = r.series_field;
  if (!seriesField) {
    const pts = numericRows(r);
    return {
      labels: pts.map(p => String(p.x)),
      datasets: [{ label: r.kpi_name, data: pts.map(p => p.y) }],
    };
  }

  // Nhiều series: gộp theo giá trị series_field, căn chung 1 trục X (labels) —
  // đúng nguyên nhân bug trước đó (nhiều dòng/1 mốc x bị nối lẫn khi coi là 1 series).
  const groups = new Map(); // seriesName -> Map(x -> y)
  const xSet = new Set();
  for (const row of r.rows) {
    const x = String(row[r.x_field]);
    const seriesName = String(row[seriesField]);
    const y = Number(row[r.y_field]);
    xSet.add(x);
    if (!groups.has(seriesName)) groups.set(seriesName, new Map());
    groups.get(seriesName).set(x, y);
  }
  const labels = Array.from(xSet).sort();
  const datasets = Array.from(groups.entries()).map(([name, m]) => ({
    label: name,
    data: labels.map(x => (m.has(x) ? m.get(x) : null)),
  }));
  return { labels, datasets };
}

function baseChartOptions(multiSeries) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: multiSeries ? 'index' : 'nearest', intersect: false },
    plugins: {
      legend: {
        display: multiSeries,
        position: 'top',
        align: 'start',
        labels: { color: cssVar('--ink-secondary'), boxWidth: 12, boxHeight: 12, usePointStyle: true, font: { size: 11.5 } },
      },
      tooltip: {
        backgroundColor: cssVar('--ink-primary'),
        titleColor: cssVar('--surface'),
        bodyColor: cssVar('--surface'),
        padding: 8,
        cornerRadius: 6,
        callbacks: { label: (ctx) => `${ctx.dataset.label}: ${formatCompact(ctx.parsed.y)}` },
      },
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: { color: cssVar('--ink-muted'), font: { size: 10.5 }, maxRotation: 0, autoSkip: true, maxTicksLimit: 6 },
      },
      y: {
        grid: { color: cssVar('--gridline') },
        border: { display: false },
        ticks: { color: cssVar('--ink-muted'), font: { size: 10.5 }, callback: (v) => formatCompact(v) },
      },
    },
  };
}

/* ---------- Line chart (trend over time) ---------- */
function renderLineChart(container, r) {
  if (!r.rows || r.rows.length === 0) { container.textContent = 'Không có dữ liệu.'; return; }
  if (r.rows.length === 1 && !r.series_field) { renderStatTile(container, r); return; }

  const { labels, datasets } = buildSeries(r);
  const multiSeries = datasets.length > 1;

  const wrap = document.createElement('div');
  wrap.className = 'chart-wrap';
  const canvas = document.createElement('canvas');
  wrap.appendChild(canvas);
  container.appendChild(wrap);

  new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: datasets.map((d, i) => ({
        ...d,
        borderColor: seriesColor(i),
        backgroundColor: multiSeries ? seriesColor(i) : cssVar('--series-1-wash'),
        fill: !multiSeries,
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 5,
        pointHitRadius: 12,
        tension: 0.25,
        spanGaps: true,
      })),
    },
    options: baseChartOptions(multiSeries),
  });
}

/* ---------- Bar chart (comparison) ---------- */
function renderBarChart(container, r) {
  if (!r.rows || r.rows.length === 0) { container.textContent = 'Không có dữ liệu.'; return; }

  const { labels, datasets } = buildSeries(r);
  const multiSeries = datasets.length > 1;

  const wrap = document.createElement('div');
  wrap.className = 'chart-wrap';
  const canvas = document.createElement('canvas');
  wrap.appendChild(canvas);
  container.appendChild(wrap);

  new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: datasets.map((d, i) => ({
        ...d,
        backgroundColor: seriesColor(i),
        borderRadius: 4,
        maxBarThickness: 28,
      })),
    },
    options: {
      ...baseChartOptions(multiSeries),
      scales: {
        ...baseChartOptions(multiSeries).scales,
        y: { ...baseChartOptions(multiSeries).scales.y, beginAtZero: true },
      },
    },
  });
}

/* ---------- Table ---------- */
function renderTableView(container, r) {
  const scroll = document.createElement('div');
  scroll.className = 'kpi-table-scroll';
  const table = document.createElement('table');
  table.className = 'kpi-table';
  const thead = document.createElement('tr');
  [r.x_field, r.y_field].forEach(f => {
    const th = document.createElement('th');
    th.textContent = f;
    thead.appendChild(th);
  });
  table.appendChild(thead);
  for (const row of r.rows) {
    const tr = document.createElement('tr');
    [r.x_field, r.y_field].forEach(f => {
      const td = document.createElement('td');
      const v = row[f];
      td.textContent = typeof v === 'number' ? formatCompact(v) : String(v);
      tr.appendChild(td);
    });
    table.appendChild(tr);
  }
  scroll.appendChild(table);
  container.appendChild(scroll);
}

/* ---------- Điểm vào: vẽ toàn bộ lưới KPI ---------- */
function renderKpiGrid(gridEl, blueprint, results) {
  gridEl.innerHTML = '';
  for (const r of results) {
    const kpiSpec = blueprint ? blueprint.kpis.find(k => k.name === r.kpi_name) : null;
    const card = document.createElement('div');
    card.className = 'kpi-card';

    const head = document.createElement('div');
    head.className = 'kpi-card-head';
    const nameEl = document.createElement('span');
    nameEl.className = 'kpi-name';
    nameEl.textContent = r.kpi_name;
    head.appendChild(nameEl);
    if (kpiSpec && kpiSpec.status === 'Draft') {
      const badge = document.createElement('span');
      badge.className = 'draft-badge';
      badge.textContent = '\u26a0 Draft \u2014 chưa xác nhận';
      head.appendChild(badge);
    }
    card.appendChild(head);

    const chartType = kpiSpec ? kpiSpec.chart_type : (r.rows.length <= 1 ? 'number' : 'line');
    const cardBody = document.createElement('div');
    if (chartType === 'number') renderStatTile(cardBody, r);
    else if (chartType === 'bar') renderBarChart(cardBody, r);
    else if (chartType === 'table') renderTableView(cardBody, r);
    else renderLineChart(cardBody, r);
    card.appendChild(cardBody);

    gridEl.appendChild(card);
  }
}

return { renderKpiGrid, formatCompact };
})();
