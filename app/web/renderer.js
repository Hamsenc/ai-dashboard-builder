/* Renderer dashboard — dùng chung bởi app thật (index.html) và preview harness
   (preview/index.html). Thuần hàm vẽ: nhận {blueprint, results} rồi dựng DOM, KHÔNG
   fetch, KHÔNG đụng tới state của app. Bản đóng băng trước Phase 0 nằm ở
   preview/renderer-baseline.js để so sánh trước/sau. */
window.DashboardRenderer = (function () {
'use strict';

const SERIES_COLOR_COUNT = 12;   // phải khớp số biến --series-N trong theme.css
const DEFAULT_TOP_N = 6;
const ROLLUP_LABEL = 'Khác';
const EMPTY_SERIES_LABEL = '(không xác định)';

/* ============================ Format ============================

Đơn vị đọc theo tiếng Việt (triệu/tỷ) thay vì M/B — người dùng là nhân viên kinh
doanh, không phải dân BI. KHÔNG gắn ký hiệu tiền tệ ở đây: renderer không có cách nào
biết chắc 1 cột là VND hay số lượng, gắn bừa "₫" vào số đơn hàng là nói sai. Đơn vị
thật do Planner khai báo ở Phase 2 (kpi.format). */

function formatNumber(n) {
  return n.toLocaleString('vi-VN', { maximumFractionDigits: Math.abs(n) < 10 ? 2 : 0 });
}

function scaled(abs, div, unit) {
  const v = abs / div;
  return v.toLocaleString('vi-VN', { maximumFractionDigits: v < 10 ? 1 : 0 }) + ' ' + unit;
}

function formatCompact(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  const sign = n < 0 ? '-' : '';
  const abs = Math.abs(n);
  // Dưới 1 triệu thì hiện đủ số: rút gọn "19.955 đơn" thành "20 nghìn" là mất thông tin
  // mà chẳng tiết kiệm được bao nhiêu chỗ.
  if (abs < 1e6) return sign + formatNumber(abs);
  if (abs < 1e9) return sign + scaled(abs, 1e6, 'triệu');
  return sign + scaled(abs, 1e9, 'tỷ');
}

/* Đơn vị lấy từ kpi.format do Planner khai (Phase 2). Blueprint cũ không có field này
   -> 'number', tức giữ nguyên hành vi trước đây, không tự suy ra tiền tệ. Ký hiệu ₫
   chỉ gắn ở con số lớn trên thẻ, không gắn vào nhãn trục — thẻ đã nói rõ đơn vị rồi,
   nhắc lại ở mỗi vạch trục chỉ làm chật chart. */
function formatValue(n, fmt, opts) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  if (fmt === 'percent') return n.toLocaleString('vi-VN', { maximumFractionDigits: 1 }) + '%';
  const base = formatCompact(n);
  return (fmt === 'currency_vnd' && !(opts && opts.axis)) ? base + ' ₫' : base;
}

const AGG_LABEL = { sum: 'Tổng', avg: 'Trung bình', last: 'Mới nhất' };

/* Cộng phần trăm của 14 ngày lại là vô nghĩa — nếu Planner lỡ khai percent+sum thì đổi
   sang trung bình. KHÔNG phải đổi ngầm: nhãn dưới con số luôn ghi rõ phép gộp đang
   dùng, nên user vẫn thấy đúng thứ đã được tính. */
function resolveDisplay(kpiSpec) {
  const fmt = (kpiSpec && kpiSpec.format) || 'number';
  let agg = (kpiSpec && kpiSpec.tile_agg) || 'sum';
  if (fmt === 'percent' && agg === 'sum') agg = 'avg';
  return { fmt, agg };
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/* Giá trị series rỗng/null vẫn là 1 nhóm có thật trong dữ liệu (vd channel_key = '')
   — phải hiện thành nhãn đọc được, không để legend ra 1 chấm màu không có chữ. */
function seriesLabel(v) {
  const s = (v === null || v === undefined) ? '' : String(v);
  return s.trim() === '' ? EMPTY_SERIES_LABEL : s;
}

function numericRows(r) {
  return r.rows.map(row => ({ x: row[r.x_field], y: Number(row[r.y_field]) }));
}

/* ====================== Bảng màu ổn định toàn dashboard ======================

Màu PHẢI gắn với TÊN series, không gắn với thứ tự xuất hiện trong rows: SQL sinh ra
chỉ `ORDER BY date`, nên thứ tự channel bên trong mỗi ngày là tuỳ ý và khác nhau giữa
các KPI. Cách cũ (seriesColor theo index) làm cùng 1 kênh ra màu khác nhau ở 2 chart
cạnh nhau — người xem đối chiếu sẽ đọc sai hoàn toàn.

Xếp hạng theo TỈ TRỌNG trong từng KPI rồi mới cộng lại, để KPI đơn vị lớn (VND) không
nuốt hết thứ hạng của KPI đơn vị nhỏ (số đơn). */
function buildColorRegistry(results) {
  const score = new Map();
  for (const r of results) {
    if (!r.series_field) continue;
    const per = new Map();
    let total = 0;
    for (const row of r.rows) {
      const name = seriesLabel(row[r.series_field]);
      const y = Math.abs(Number(row[r.y_field])) || 0;
      per.set(name, (per.get(name) || 0) + y);
      total += y;
    }
    for (const [name, v] of per) {
      score.set(name, (score.get(name) || 0) + (total ? v / total : 0));
    }
  }
  const ordered = Array.from(score.entries())
    .sort((a, b) => (b[1] - a[1]) || a[0].localeCompare(b[0], 'vi'))
    .map(e => e[0]);

  const tokenByName = new Map();
  ordered.forEach((name, i) => tokenByName.set(name, '--series-' + ((i % SERIES_COLOR_COUNT) + 1)));
  return {
    colorOf(name) {
      if (name === ROLLUP_LABEL) return cssVar('--series-rollup');
      return cssVar(tokenByName.get(name) || '--series-1');
    },
  };
}

/* ================== Dựng dataset: top-N + gộp phần còn lại ==================

Gộp "Khác" tính TRỰC TIẾP từ rows đã có ở client nên chính xác tuyệt đối — không cần
đổi SQL, không cần rebuild dashboard cũ. */
function buildSeries(r, colors, topN) {
  if (!r.series_field) {
    // Không có series_field KHÔNG có nghĩa là mỗi mốc x chỉ có 1 dòng: blueprint có thể
    // khai dimensions (brand × kênh) mà Builder vẫn để series_field rỗng. Vẽ thẳng từng
    // dòng theo thứ tự trả về sẽ ra đường răng cưa do nhiều dòng cùng 1 ngày bị nối
    // với nhau — phải cộng gộp theo x, đúng bằng con số mà tile phía trên đang hiện.
    const pts = totalsByX(r);
    return {
      labels: pts.map(p => String(p.x)),
      datasets: [{ label: r.kpi_name, data: pts.map(p => p.y), color: colors.colorOf(r.kpi_name) }],
      rolledUpCount: 0, rolledUpShare: 0, totalSeries: 1,
      collapsedRows: r.rows.length - pts.length,
    };
  }

  const groups = new Map();   // seriesName -> Map(x -> y)
  const totals = new Map();   // seriesName -> tổng |y|
  const xSet = new Set();
  for (const row of r.rows) {
    const x = String(row[r.x_field]);
    const name = seriesLabel(row[r.series_field]);
    const y = Number(row[r.y_field]);
    xSet.add(x);
    if (!groups.has(name)) groups.set(name, new Map());
    groups.get(name).set(x, y);
    totals.set(name, (totals.get(name) || 0) + (Math.abs(y) || 0));
  }

  const labels = Array.from(xSet).sort();
  const ranked = Array.from(totals.entries())
    .sort((a, b) => (b[1] - a[1]) || a[0].localeCompare(b[0], 'vi'))
    .map(e => e[0]);

  const keep = ranked.slice(0, topN);
  const rolled = ranked.slice(topN);

  const datasets = keep.map(name => ({
    label: name,
    data: labels.map(x => (groups.get(name).has(x) ? groups.get(name).get(x) : null)),
    color: colors.colorOf(name),
  }));

  let rolledUpShare = 0;
  if (rolled.length) {
    const data = labels.map(x => {
      let sum = null;
      for (const name of rolled) {
        const v = groups.get(name).get(x);
        if (v !== undefined && v !== null) sum = (sum || 0) + Number(v);
      }
      return sum;
    });
    datasets.push({ label: ROLLUP_LABEL, data, color: colors.colorOf(ROLLUP_LABEL) });
    const grand = Array.from(totals.values()).reduce((a, b) => a + b, 0);
    const rolledTotal = rolled.reduce((a, n) => a + totals.get(n), 0);
    rolledUpShare = grand ? rolledTotal / grand : 0;
  }

  return { labels, datasets, rolledUpCount: rolled.length, rolledUpShare, totalSeries: ranked.length };
}

/* ============================ Legend + ghi chú ============================

Tự vẽ legend bằng HTML thay vì dùng legend của Chart.js: legend Chart.js nằm TRONG
canvas nên ăn vào chiều cao vùng vẽ (chart-wrap cao cố định), và có trạng thái
ẩn/gạch ngang riêng dễ gây hiểu nhầm. */
function renderLegend(container, datasets) {
  const legend = document.createElement('div');
  legend.className = 'chart-legend';
  for (const d of datasets) {
    const item = document.createElement('span');
    item.className = 'legend-item';
    const swatch = document.createElement('i');
    swatch.style.background = d.color;
    item.appendChild(swatch);
    item.appendChild(document.createTextNode(d.label));
    legend.appendChild(item);
  }
  container.appendChild(legend);
}

/* Nói thẳng phần dữ liệu đã bị gộp — không im lặng giấu series khỏi người xem. */
function renderCollapseNote(container, series, points) {
  if (!series.collapsedRows) return;
  const note = document.createElement('p');
  note.className = 'chart-note';
  note.textContent = `Dữ liệu có nhiều dòng trên cùng 1 mốc thời gian (${series.collapsedRows + points} dòng / `
    + `${points} mốc) — chart cộng gộp lại, khớp với con số ở thẻ phía trên.`;
  container.appendChild(note);
}

function renderRollupNote(container, series) {
  if (!series.rolledUpCount) return;
  const note = document.createElement('p');
  note.className = 'chart-note';
  const pct = (series.rolledUpShare * 100);
  note.textContent = `${series.rolledUpCount} nhóm nhỏ nhất (${pct < 0.1 ? '<0.1' : pct.toFixed(1)}% tổng) đã gộp vào "${ROLLUP_LABEL}" — tổng số vẫn đủ, không bị bỏ sót.`;
  container.appendChild(note);
}

/* ============================== Stat tile ==============================

Tile là con số headline của 1 KPI trên cả kỳ đang xem. GIẢ ĐỊNH: mọi KPI trong app
hiện đều là đại lượng CỘNG ĐƯỢC theo thời gian (Builder luôn sinh SQL dạng
SUM(...) GROUP BY ngày), nên tổng cả kỳ là con số đúng. Đại lượng dạng TỒN (tồn kho,
số ngày bán hết hàng) thì cộng lại là vô nghĩa — khi Planner khai báo được
kpi.tile_agg ở Phase 2 thì đổi sang dùng khai báo đó thay cho giả định này.

Luôn ghi rõ phép gộp + khoảng dữ liệu ngay dưới con số. Một con số trần không nói nó
là tổng hay giá trị ngày cuối là kiểu dễ bị đọc sai nhất. */

const GRANULARITY_NOUN = { hour: 'giờ', day: 'ngày', week: 'tuần', month: 'tháng' };

function isDateLike(v) { return /^\d{4}-\d{2}-\d{2}/.test(String(v)); }

function vnDate(iso) {
  const p = String(iso).slice(0, 10).split('-');
  return p.length === 3 ? `${p[2]}/${p[1]}` : String(iso);
}

/* Tổng theo từng mốc x (gộp hết mọi series) — nền cho cả con số tile lẫn sparkline. */
function totalsByX(r) {
  const byX = new Map();
  for (const row of r.rows) {
    const x = String(row[r.x_field]);
    const y = Number(row[r.y_field]);
    if (!Number.isFinite(y)) continue;
    byX.set(x, (byX.get(x) || 0) + y);
  }
  return Array.from(byX.entries()).sort((a, b) => a[0].localeCompare(b[0]))
    .map(([x, y]) => ({ x, y }));
}

/* So nửa sau với nửa đầu của CHÍNH kỳ đang xem. Không gọi là "so với kỳ trước" vì
   renderer không có dữ liệu kỳ trước — muốn thế phải query thêm 1 khoảng nữa. */
function halfOverHalf(pts) {
  if (pts.length < 4) return null;
  const half = Math.floor(pts.length / 2);
  const sum = (arr) => arr.reduce((a, p) => a + p.y, 0);
  const first = sum(pts.slice(0, half));
  const last = sum(pts.slice(pts.length - half));
  if (!first) return null;
  return { pct: ((last - first) / Math.abs(first)) * 100, n: half };
}

function firstToLast(pts) {
  if (pts.length < 2 || !pts[0].y) return null;
  return { pct: ((pts[pts.length - 1].y - pts[0].y) / Math.abs(pts[0].y)) * 100, n: 0 };
}

function renderTile(container, r, kpiSpec, blueprint, opts) {
  const { fmt, agg } = resolveDisplay(kpiSpec);
  const pts = totalsByX(r);
  const dated = pts.length > 0 && isDateLike(pts[0].x);
  // Chỉ được gọi là "ngày/tuần/tháng" khi trục x THẬT SỰ là thời gian. KPI trả về đúng
  // 1 dòng tổng hợp (x = 'metric' chẳng hạn) mà ghi "Tổng 1 ngày" là nói sai.
  const noun = dated ? (GRANULARITY_NOUN[blueprint && blueprint.granularity] || 'mốc') : 'nhóm';

  const tile = document.createElement('div');
  tile.className = 'tile';

  const head = document.createElement('div');
  head.className = 'tile-head';
  const name = document.createElement('span');
  name.className = 'tile-name';
  name.textContent = r.kpi_name;
  head.appendChild(name);
  if (kpiSpec && kpiSpec.status === 'Draft') head.appendChild(draftBadge());
  tile.appendChild(head);

  const total = pts.reduce((a, p) => a + p.y, 0);
  let headline = null;
  if (pts.length) {
    if (agg === 'last') headline = pts[pts.length - 1].y;
    else if (agg === 'avg') headline = total / pts.length;
    else headline = total;
  }
  const value = document.createElement('div');
  value.className = 'tile-value';
  value.textContent = headline === null ? '—' : formatValue(headline, fmt);
  tile.appendChild(value);

  let captionText = '';
  const lastX = pts.length ? pts[pts.length - 1].x : null;
  if (!pts.length) captionText = 'Không có dữ liệu';
  else if (agg === 'last') captionText = 'Mới nhất' + (dated ? ` · ${vnDate(lastX)}` : '');
  else if (pts.length > 1) {
    captionText = `${AGG_LABEL[agg]} ${pts.length} ${noun}`
      + (dated ? ` · ${vnDate(pts[0].x)}–${vnDate(lastX)}` : '');
  } else if (dated) captionText = `Ngày ${vnDate(pts[0].x)}`;
  // 1 dòng không theo thời gian: đó chính là số tổng hợp SQL trả về, không thêm nhãn
  // phỏng đoán về phạm vi.
  if (captionText) {
    const caption = document.createElement('div');
    caption.className = 'tile-caption';
    caption.textContent = captionText;
    tile.appendChild(caption);
  }

  // Đại lượng dạng tồn (agg='last') thì so mốc cuối với mốc đầu mới có nghĩa; đại lượng
  // cộng được thì so nửa cuối với nửa đầu kỳ (tổng 1 ngày lẻ dao động quá mạnh).
  const delta = (agg === 'last') ? firstToLast(pts) : halfOverHalf(pts);
  if (delta) {
    const d = document.createElement('div');
    d.className = 'tile-delta ' + (delta.pct >= 0 ? 'up' : 'down');
    const pct = Math.abs(delta.pct).toLocaleString('vi-VN', { maximumFractionDigits: 1 });
    d.textContent = `${delta.pct >= 0 ? '▲' : '▼'} ${pct}% · ` + (delta.n
      ? `${delta.n} ${noun} cuối so với ${delta.n} ${noun} đầu kỳ`
      : `so với ${dated ? vnDate(pts[0].x) : pts[0].x}`);
    tile.appendChild(d);
  }

  // Sparkline chỉ thêm khi KPI này KHÔNG có chart riêng bên dưới — nếu có thì nó chỉ
  // lặp lại thông tin của chart, làm tile rối thêm mà không nói gì mới.
  if (opts && opts.withSparkline && pts.length > 1) {
    const spark = document.createElement('div');
    spark.className = 'stat-sparkline';
    tile.appendChild(spark);
    renderSparkline(spark, pts);
  }

  container.appendChild(tile);
}

function draftBadge() {
  const badge = document.createElement('span');
  badge.className = 'draft-badge';
  badge.textContent = '⚠ Draft — chưa xác nhận';
  return badge;
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

/* ============================== Chart.js ============================== */

function baseChartOptions(stacked, fmt) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { display: false },   // legend tự vẽ bằng HTML, xem renderLegend
      tooltip: {
        backgroundColor: cssVar('--ink-primary'),
        titleColor: cssVar('--surface'),
        bodyColor: cssVar('--surface'),
        padding: 8,
        cornerRadius: 6,
        itemSort: (a, b) => b.parsed.y - a.parsed.y,
        callbacks: { label: (ctx) => `${ctx.dataset.label}: ${formatValue(ctx.parsed.y, fmt)}` },
      },
    },
    scales: {
      x: {
        stacked: !!stacked,
        grid: { display: false },
        ticks: {
          color: cssVar('--ink-muted'), font: { size: 10.5 },
          maxRotation: 0, autoSkip: true, maxTicksLimit: 7,
          // function thường (không arrow) để có `this` là scale -> đọc được nhãn gốc
          callback: function (value) {
            const raw = this.getLabelForValue(value);
            return isDateLike(raw) ? vnDate(raw) : raw;
          },
        },
      },
      y: {
        stacked: !!stacked,
        grid: { color: cssVar('--gridline') },
        border: { display: false },
        ticks: { color: cssVar('--ink-muted'), font: { size: 10.5 }, callback: (v) => formatValue(v, fmt, { axis: true }) },
      },
    },
  };
}

function chartCanvas(container) {
  const wrap = document.createElement('div');
  wrap.className = 'chart-wrap';
  const canvas = document.createElement('canvas');
  wrap.appendChild(canvas);
  container.appendChild(wrap);
  return canvas;
}

function renderLineChart(container, r, colors, topN, fmt) {
  if (!r.rows || r.rows.length === 0) { renderEmpty(container); return; }
  if (r.rows.length === 1 && !r.series_field) { renderEmpty(container, 'Chỉ có 1 mốc dữ liệu — xem con số ở thẻ phía trên.'); return; }

  const series = buildSeries(r, colors, topN);
  const multi = series.datasets.length > 1;
  if (multi) renderLegend(container, series.datasets);

  new Chart(chartCanvas(container), {
    type: 'line',
    data: {
      labels: series.labels,
      datasets: series.datasets.map(d => ({
        label: d.label,
        data: d.data,
        borderColor: d.color,
        backgroundColor: multi ? d.color : cssVar('--series-1-wash'),
        fill: !multi,
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 5,
        pointHitRadius: 12,
        tension: 0.25,
        spanGaps: true,
      })),
    },
    options: (() => {
      const o = baseChartOptions(false, fmt);
      // Không để trục Y thò xuống âm khi mọi giá trị đều không âm — vùng trống dưới 0
      // làm chart trông như có giá trị âm.
      if (series.datasets.every(d => d.data.every(v => v === null || v >= 0))) o.scales.y.beginAtZero = true;
      return o;
    })(),
  });
  renderCollapseNote(container, series, series.labels.length);
  renderRollupNote(container, series);
}

function renderBarChart(container, r, colors, topN, fmt) {
  if (!r.rows || r.rows.length === 0) { renderEmpty(container); return; }

  const series = buildSeries(r, colors, topN);
  const multi = series.datasets.length > 1;
  // Nhiều nhóm trên cùng 1 trục thời gian: xếp chồng thay vì đứng cạnh nhau —
  // grouped bar với 7 nhóm × 14 ngày ra gần 100 cột răng lược, không đọc được.
  const stacked = multi;
  if (multi) renderLegend(container, series.datasets);

  new Chart(chartCanvas(container), {
    type: 'bar',
    data: {
      labels: series.labels,
      datasets: series.datasets.map(d => ({
        label: d.label,
        data: d.data,
        backgroundColor: d.color,
        borderRadius: stacked ? 0 : 4,
        maxBarThickness: stacked ? 56 : 28,
      })),
    },
    options: (() => {
      const o = baseChartOptions(stacked, fmt);
      o.scales.y.beginAtZero = true;
      return o;
    })(),
  });
  renderCollapseNote(container, series, series.labels.length);
  renderRollupNote(container, series);
}

function renderTableView(container, r, fmt) {
  const scroll = document.createElement('div');
  scroll.className = 'kpi-table-scroll';
  const table = document.createElement('table');
  table.className = 'kpi-table';
  const cols = r.series_field ? [r.x_field, r.series_field, r.y_field] : [r.x_field, r.y_field];
  const thead = document.createElement('tr');
  cols.forEach(f => {
    const th = document.createElement('th');
    th.textContent = f;
    thead.appendChild(th);
  });
  table.appendChild(thead);
  for (const row of r.rows) {
    const tr = document.createElement('tr');
    cols.forEach(f => {
      const td = document.createElement('td');
      const v = row[f];
      td.textContent = typeof v === 'number' ? formatValue(v, fmt)
                     : (f === r.series_field ? seriesLabel(v) : String(v));
      tr.appendChild(td);
    });
    table.appendChild(tr);
  }
  scroll.appendChild(table);
  container.appendChild(scroll);
}

function renderEmpty(container, msg) {
  const p = document.createElement('p');
  p.className = 'chart-note';
  p.textContent = msg || 'Không có dữ liệu trong khoảng thời gian đang chọn.';
  container.appendChild(p);
}

/* ====================== Điểm vào: bố cục + vẽ ======================

Bố cục suy TỰ ĐỘNG từ blueprint.kpis, không cần blueprint khai báo gì thêm — nhờ vậy
31 dashboard đã build từ trước cũng đẹp lên ngay mà không phải rebuild hay gọi lại LLM.
Phase 2 sẽ cho Planner ghi đè bằng field layout tuỳ chọn; thiếu field thì rơi về đúng
hàm này.

Quy tắc:
- Hàng trên: 1 tile/KPI (trừ KPI dạng bảng) — trả lời "bao nhiêu" trước khi hỏi
  "diễn biến thế nào". Đây là thứ dashboard cũ thiếu hẳn.
- Hàng dưới: chart xếp lưới 12 cột, mặc định nửa hàng. Chart lẻ cuối cùng và bảng thì
  chiếm trọn hàng — không để 1 card mồ côi rộng bằng nửa màn hình.
*/

function chartTypeOf(kpiSpec, r) {
  if (kpiSpec && kpiSpec.chart_type) return kpiSpec.chart_type;
  return r.rows.length <= 1 ? 'number' : 'line';
}

function renderKpiGrid(gridEl, blueprint, results, opts) {
  const topN = (opts && opts.topN) || DEFAULT_TOP_N;
  const colors = buildColorRegistry(results);

  gridEl.innerHTML = '';
  const root = document.createElement('div');
  root.className = 'dash';
  gridEl.appendChild(root);

  // Ghép result với spec KPI: khớp theo tên nhưng mỗi spec chỉ dùng 1 lần. Có
  // blueprint cũ chứa 2 KPI TRÙNG TÊN (vd cùng "GMV (Success)", một dạng số một dạng
  // đường) — khớp theo tên thuần sẽ cho cả hai lấy chung spec đầu tiên rồi vẽ thành 2
  // cái giống hệt nhau. Không khớp được thì rơi về đúng vị trí thứ tự.
  const pool = blueprint && blueprint.kpis ? blueprint.kpis.slice() : [];
  const used = new Set();
  const items = results.map((r, i) => {
    let idx = pool.findIndex((k, j) => !used.has(j) && k.name === r.kpi_name);
    if (idx === -1 && !used.has(i) && i < pool.length) idx = i;
    const kpiSpec = idx === -1 ? null : pool[idx];
    if (idx !== -1) used.add(idx);
    const type = chartTypeOf(kpiSpec, r);
    return { r, kpiSpec, type, hasChart: type !== 'number' };
  });

  // ---- Hàng tile
  const tileItems = items.filter(it => it.type !== 'table');
  if (tileItems.length) {
    const tiles = document.createElement('div');
    tiles.className = 'dash-tiles';
    for (const it of tileItems) {
      renderTile(tiles, it.r, it.kpiSpec, blueprint, { withSparkline: !it.hasChart });
    }
    root.appendChild(tiles);
  }

  // ---- Khu chart
  const chartItems = items.filter(it => it.hasChart);
  if (!chartItems.length) return;

  const anyDated = chartItems.some(it => it.r.rows.length && isDateLike(it.r.rows[0][it.r.x_field]));
  const section = document.createElement('h3');
  section.className = 'dash-section';
  section.textContent = anyDated ? 'Diễn biến theo thời gian' : 'Chi tiết';
  root.appendChild(section);

  const charts = document.createElement('div');
  charts.className = 'dash-charts';
  root.appendChild(charts);

  // Bề rộng: ưu tiên kpi.col_span nếu Planner đã khai (6/12), còn lại tự xếp nửa hàng.
  // Bảng luôn trọn hàng. Sau đó chart CUỐI CÙNG mà để trống nửa hàng thì giãn ra cho
  // hết — không để 1 card mồ côi cạnh khoảng trắng.
  const spans = chartItems.map(it => {
    if (it.type === 'table') return { span: 12, explicit: true };
    // Chỉ nhận đúng 6 hoặc 12 — giá trị lạ (blueprint sửa tay, phiên bản schema cũ)
    // thì bỏ qua và tự xếp, không đẩy thẳng vào grid-column.
    const declared = it.kpiSpec && it.kpiSpec.col_span;
    return (declared === 6 || declared === 12)
      ? { span: declared, explicit: true }
      : { span: 6, explicit: false };
  });
  let cols = 0;
  spans.forEach((sp, i) => {
    const isLast = i === spans.length - 1;
    if (isLast && !sp.explicit && (cols + sp.span) % 12 !== 0) sp.span = 12 - (cols % 12);
    cols += sp.span;
  });

  chartItems.forEach((it, i) => {
    const { r, kpiSpec, type } = it;
    const { fmt } = resolveDisplay(kpiSpec);
    const kpiTopN = (kpiSpec && kpiSpec.top_n > 0) ? kpiSpec.top_n : topN;
    const card = document.createElement('div');
    card.className = 'kpi-card';

    const span = spans[i].span;
    card.style.gridColumn = 'span ' + span;
    if (span === 12) card.classList.add('card-wide');

    const head = document.createElement('div');
    head.className = 'kpi-card-head';
    const nameEl = document.createElement('span');
    nameEl.className = 'kpi-name';
    nameEl.textContent = r.kpi_name;
    head.appendChild(nameEl);
    if (kpiSpec && kpiSpec.status === 'Draft') head.appendChild(draftBadge());
    card.appendChild(head);

    const body = document.createElement('div');
    if (type === 'bar') renderBarChart(body, r, colors, kpiTopN, fmt);
    else if (type === 'table') renderTableView(body, r, fmt);
    else renderLineChart(body, r, colors, kpiTopN, fmt);
    card.appendChild(body);

    // Định nghĩa KPI đóng mở được, giữ NGUYÊN VĂN như blueprint đã duyệt (luật cứng
    // #2: không âm thầm đổi định nghĩa) mà không chiếm chỗ khi không ai cần đọc.
    if (kpiSpec && kpiSpec.definition) card.appendChild(definitionBlock(kpiSpec));

    charts.appendChild(card);
  });
}

function definitionBlock(kpiSpec) {
  const details = document.createElement('details');
  details.className = 'kpi-def';
  const summary = document.createElement('summary');
  summary.textContent = 'Định nghĩa chỉ số'
    + (kpiSpec.status === 'custom' ? ' (tự tổng hợp, không phải KPI chuẩn hoá)' : '');
  details.appendChild(summary);
  const p = document.createElement('p');
  p.textContent = kpiSpec.definition;   // untrusted -> textContent, không innerHTML
  details.appendChild(p);
  return details;
}

return { renderKpiGrid, formatCompact, buildColorRegistry, buildSeries };
})();
