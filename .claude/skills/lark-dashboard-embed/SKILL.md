---
name: lark-dashboard-embed
description: Build 1 dashboard/báo cáo HTML từ dữ liệu BigQuery thật (project surya-495408) rồi giao cho user kèm hướng dẫn nhúng vào Lark qua tính năng Dashboard Embeds của app ai-dashboard-builder. LUÔN dùng skill này khi user nhờ "làm dashboard", "làm báo cáo", "trực quan hoá số liệu", "vẽ biểu đồ từ bảng X", hoặc nói họ muốn share 1 báo cáo lên Lark/nhúng vào tài liệu Lark — kể cả khi họ chỉ đưa tên bảng và nói chung chung "làm cho tao cái dashboard theo dõi...". Không dùng skill này nếu user chỉ hỏi số liệu để trả lời trực tiếp trong chat (không cần file/link chia sẻ).
---

# Build dashboard BigQuery + nhúng Lark (Dashboard Embeds)

Quy trình đầy đủ mà user đã chọn, gồm 3 việc — chỉ việc 2 và 3 là của Claude:

1. **User tự tư vấn chọn bảng** ở `https://ai-dashboard-builder-2eodhfgo5a-as.a.run.app/` (tab "🗂️ Tư vấn chọn bảng") — việc này KHÔNG cần Claude, user tự làm trước khi nhờ bạn, hoặc họ có thể chỉ thẳng tên bảng cho bạn nếu đã biết.
2. **Claude đọc bảng thật, thiết kế và viết file HTML dashboard** — việc chính của skill này.
3. **User upload file lên `/embeds.html` để lấy link nhúng Lark** — Claude chỉ cần đưa đúng file + đúng hướng dẫn, không tự upload hộ (upload gated theo whitelist email qua Lark OAuth, Claude không có phiên đăng nhập đó).

Đừng bịa số liệu ở bất kỳ bước nào — mọi con số trong dashboard phải đến từ 1 query thật đã chạy, không suy đoán từ tên cột.

## Trước khi bắt đầu — điều kiện cần có

Skill này giả định trước, không tự thiết lập hộ:

- **Đọc BigQuery**: session Claude hiện tại có quyền đọc project `surya-495408` — qua `bq` CLI đã đăng nhập (`gcloud auth`/service account), hoặc qua BigQuery MCP connector đã kết nối. Kiểm tra nhanh bằng `bq ls --project_id=surya-495408 00_serving_inventory`; nếu bị từ chối quyền, báo lại cho user để họ nhờ quản trị GCP của công ty cấp quyền trước, đừng đoán mò tiếp.
- **Tạo view + cấp quyền (chỉ cần khi vào Bước 2 nhánh view mới)**: cần thêm quyền BigQuery Data Editor trên dataset serving đích + quyền cập nhật ACL (`bq update`) trên các dataset nguồn. Nếu tài khoản hiện tại không có quyền này, ĐỪNG cố lách qua cách khác — báo rõ cho user để họ nhờ admin BigQuery thực hiện hộ đoạn cấp quyền, hoặc chọn phương án dùng thẳng view/bảng đã có sẵn trong tầng serving.
- **Upload lên app (Bước 6)**: user cần tài khoản Lark đã được thêm vào whitelist upload của app `ai-dashboard-builder`. Việc này Claude không làm thay được (upload gated qua phiên đăng nhập Lark của chính user) — nếu họ chưa có quyền, họ cần liên hệ admin app trước khi làm tới bước này.

## Bước 1 — Xác nhận & đọc bảng nguồn

Xác định tên bảng đầy đủ dạng `surya-495408.<dataset>.<table>`. Nếu user chỉ nói tên ngắn hoặc mô tả ("bảng tồn kho", "doanh thu theo ngày"), tự tìm bằng cách liệt kê bảng trong dataset liên quan trước khi đoán.

Đọc schema + vài dòng mẫu THẬT trước khi thiết kế bất cứ gì. Có 2 cách, dùng cách nào cũng được — ưu tiên `bq` CLI vì nó dùng được cho cả bước sau (tạo view, cấp quyền), còn BigQuery MCP chỉ đọc:

```bash
bq show --schema --format=prettyjson surya-495408:<dataset>.<table>
bq query --use_legacy_sql=false --project_id=surya-495408 'SELECT * FROM `surya-495408.<dataset>.<table>` LIMIT 20'
```

Luôn truyền `--project_id=surya-495408` (hoặc `<project>:` trước tên dataset) tường minh trong mọi lệnh `bq` — đừng giả định project mặc định của môi trường đang chạy đã trỏ sẵn về đây. Nếu dùng BigQuery MCP thay vì `bq`, tìm và load tool đó trước khi dùng (nó chỉ đọc — không dùng được cho phần tạo view/cấp quyền ở Bước 2).

Đọc luôn `description`/Business Definition của các cột số liệu quan trọng — bảng ở project này hay ghi sẵn sentinel value kiểu `(9999 = không bán được, không tính)` trong mô tả cột; nếu có, PHẢI loại giá trị đó khỏi biểu đồ/trung vị và show riêng thành 1 chỉ số khác, không được vẽ lẫn vào như số liệu thật.

Nếu cần join/so sánh nhiều bảng (VD 1 bảng actual + 1 bảng target), kiểm tra ngay lúc này xem chúng có cùng grain hay không (cùng tổ hợp cột định danh như ngày/brand/channel...). Lệch grain (VD 1 bảng có thêm chiều category mà bảng kia không có) thì chỉ so sánh được ở mức chung của cả hai — đừng suy diễn số liệu ở chiều mà 1 trong 2 bảng không có.

## Bước 2 — Xác định bảng có dùng được cho "dữ liệu sống" không

Đây là ràng buộc cứng của app, enforce ở server (`app/embeds/query_spec.py` + `app/datasource/bq_meta.py::assert_in_scope`), không phải gợi ý: **"dữ liệu sống" (live query khi user mở link) chỉ chạy được trên bảng/view nằm TRỰC TIẾP trong 3 dataset `00_serving_sales`, `00_serving_inventory`, `00_serving_operation` của project `surya-495408`.** Query nhắm bảng ở dataset khác (kể cả `09_logic_serving`, `10_lsr`, hay project khác) sẽ bị app từ chối lúc user upload (lỗi 403 "không thuộc phạm vi dữ liệu Serving").

- Nếu bảng nguồn đã nằm sẵn trong 1 trong 3 dataset đó → dùng thẳng, sang Bước 3.
- Nếu bảng nguồn nằm ở `09_logic_serving` hay `10_lsr` (hoặc cần transform/join trước khi show) → tạo 1 view pass-through mới ở `00_serving_*` tương ứng (đặt tên `vw_...`), rồi cấp authorized-view access cho toàn bộ chuỗi đọc:

  ```bash
  # Tạo view pass-through ở tầng serving (ví dụ dataset inventory)
  bq mk --use_legacy_sql=false --view \
    'SELECT * FROM `surya-495408.09_logic_serving.ten_view_logic`' \
    surya-495408:00_serving_inventory.vw_ten_moi

  # Cấp quyền: đọc access hiện tại của dataset NGUỒN, thêm entry cho view mới,
  # rồi ghi lại — PHẢI làm ở MỌI dataset nằm trong chuỗi đọc, không chỉ dataset
  # ngay sát view mới. Ví dụ nếu 09_logic_serving.ten_view_logic tự đọc từ
  # 10_lsr.fact_xyz, thì CẢ 10_lsr LẪN 09_logic_serving đều cần được cấp quyền
  # cho vw_ten_moi (không chỉ 09_logic_serving) — kinh nghiệm thật đã gặp lỗi
  # "Internal Server Error" vì chỉ cấp quyền có 1 hop.
  bq show --format=prettyjson surya-495408:09_logic_serving > /tmp/access.json
  # sửa /tmp/access.json: thêm vào mảng "access"
  #   {"view": {"projectId": "surya-495408", "datasetId": "00_serving_inventory", "tableId": "vw_ten_moi"}}
  bq update --source=/tmp/access.json surya-495408:09_logic_serving
  # lặp lại cho 10_lsr (và bất kỳ dataset trung gian nào khác trong chuỗi)
  ```

- Nếu chỉ cần dashboard "tĩnh" (số liệu chốt tại lúc build, không cần tự cập nhật) thì bỏ qua toàn bộ ràng buộc này — chỉ cần query 1 lần lấy số thật rồi nhúng cứng vào HTML, không cần `data_query_spec` (xem Bước 5). Đây cũng là lựa chọn hợp lý khi cần JOIN nhiều bảng hoặc logic quá phức tạp cho 1 tầng aggregation.

## Bước 3 — Thiết kế giao diện & cấu trúc dashboard

Đây là phần quyết định dashboard có "ra hồn" hay không. Dùng đúng các giá trị cụ thể (hex màu, size, code mẫu) dưới đây làm mặc định — chỉ đổi khi user nêu rõ brand color/font riêng. Toàn bộ rút từ 2 dashboard đã build thật (Marketing Operations, Supply Chain Management) nên đã proven đẹp và chạy được, không phải nguyên tắc suông.

### 3.1 Bảng màu mặc định (5 role ngữ nghĩa)

Gán 5 chủ đề dữ liệu của dashboard (nhóm metric, kênh, loại chi phí...) vào đúng 5 role màu này theo thứ tự quan trọng giảm dần, dùng lại ĐÚNG role đó ở mọi KPI card/badge/chart liên quan — không tự chọn màu khác cho cùng 1 chủ đề ở 2 chỗ khác nhau:

| Role | Màu đậm (border/text/line) | Tint nhạt (nền badge/icon) | Gợi ý gán |
|---|---|---|---|
| 1 | `#7c3aed` (tím) | `#ede9fe` | Metric tổng quan nhất / chi phí chính |
| 2 | `#0891b2` (xanh lam) | `#e0f2fe` | Metric số lượng / kênh chính |
| 3 | `#059669` (xanh lá) | `#d1fae5` | Tỷ lệ chuyển đổi / tích cực |
| 4 | `#e11d48` (đỏ hồng) | `#ffe4e6` | Chi phí đơn vị / cảnh báo / kém hiệu quả |
| 5 | `#d97706` (cam vàng) | `#fef3c7` | Hiệu suất / lợi nhuận |

Neutral dùng chung: nền trang `#f0f4f8`, card `#ffffff` bo góc `16px` shadow `0 1px 3px rgba(0,0,0,.05)` (hover: `translateY(-2px)` + shadow đậm hơn `0 8px 20px rgba(0,0,0,.08)`), chữ chính `#1e293b`, chữ mờ (muted) `#64748b`, viền `#e2e8f0`.

Nếu dữ liệu chỉ có 1-2 chủ đề (không đủ 5) thì chỉ dùng 1-2 role đầu, đừng ép dùng hết 5 màu. Nếu dashboard cần tông đơn sắc (kiểu SCM — nhiều trang dày đặc số liệu, ít màu cho dễ nhìn) thì dùng 1 accent chính (ví dụ `#2B4EAF` navy) + 3-4 shade nhạt dần của accent đó thay cho bảng 5-role, nền `#EEF2F7`, card `#FFFFFF` bo `10px`.

### 3.2 Typography

Google Fonts: **DM Sans** cho chữ thường, **DM Mono** cho toàn bộ con số (KPI, bảng, tick label) — load qua `<link>` Google Fonts, không self-host. Với dashboard nhiều số liệu dày đặc (nhiều bảng, nhiều trang) có thể dùng `Segoe UI`/system-ui 13px cho gọn thay vì DM Sans. Size mặc định: title lớn `28-32px` bold, chart title `15px` bold, subtitle/label `12-13px` muted, KPI number `28-32px` DM Mono bold, badge `11px` bold uppercase.

### 3.3 State & filter pattern (bắt buộc theo đúng khung này)

```js
var ALL_ROWS = [];        // toàn bộ dữ liệu đã fetch/query, KHÔNG đổi sau khi load
var currentFilters = {};  // state filter hiện tại

function applyFilters() {
  var rows = ALL_ROWS.filter(r => /* so khớp currentFilters */ true);
  renderDashboard(rows);  // 1 điểm vào duy nhất, vẽ lại TOÀN BỘ chart/KPI/table
}

function renderDashboard(rows) {
  renderKPIs(rows);
  renderCharts(rows);   // mỗi hàm con tự gọi dc(id) hoặc Plotly.react() trước khi vẽ
  renderTable(rows);
  if (!window._dashAnimated) { runEntryAnimation(); window._dashAnimated = true; }
}
```

Không patch riêng 1 chart khi filter đổi — luôn đi qua `applyFilters()` → `renderDashboard()`. Nếu dashboard nhiều tab/trang (kiểu SCM), thêm biến `currentTab` global, mỗi tab có hàm render riêng (`renderMfg()`, `renderInv()`...) chỉ gọi khi user bấm vào tab đó, không render sẵn tab ẩn.

### 3.4 KPI card — markup & CSS cụ thể

```html
<div class="kpi-card" style="border-left:4px solid var(--role-color)">
  <svg class="kpi-icon" ...></svg> <!-- icon 20-24px, màu var(--role-color), góc trên phải -->
  <div class="kpi-label">TOTAL SPEND</div>
  <div class="kpi-number">4.3tr</div>
  <div class="kpi-subtitle">All campaigns · all channels</div>
</div>
```
```css
.kpi-card{background:#fff;border-radius:16px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.05);position:relative}
.kpi-card:hover{transform:translateY(-2px);box-shadow:0 8px 20px rgba(0,0,0,.08)}
.kpi-icon{position:absolute;top:16px;right:16px;width:22px;height:22px}
.kpi-label{font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:#64748b}
.kpi-number{font-family:'DM Mono',monospace;font-size:30px;font-weight:700;margin:6px 0}
.kpi-subtitle{font-size:12px;color:#94a3b8}
```
KPI grid: `grid-template-columns:repeat(N,1fr);gap:16px` với N = số KPI (thường 3-5). Mỗi KPI viết công thức cụ thể ngay lúc thiết kế (ví dụ `Spend / Leads`) — không để tự suy diễn khi code.

### 3.5 Chart card & config chart cụ thể

Header mọi chart card:
```html
<div class="chart-card">
  <div class="chart-header">
    <div><div class="chart-title">Spend vs Leads Over Time</div><div class="chart-subtitle">Monthly · dual-axis</div></div>
    <span class="badge" style="color:var(--role-color);background:var(--role-tint)">Monthly Trend</span>
  </div>
  <div id="chartX" style="height:280px"></div>
</div>
```
`.badge{padding:4px 10px;border-radius:20px;font-size:11px;font-weight:700}`

**Nếu dùng Plotly** (cdnjs, mọi chart dùng chung layout nền):
```js
function plotlyLayout(extra) {
  return Object.assign({
    paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
    font: { family: 'DM Sans, sans-serif', color: '#475569', size: 12 },
    margin: { t: 20, r: 20, b: 40, l: 50 },
    xaxis: { gridcolor: '#e2e8f0', zeroline: false },
    yaxis: { gridcolor: '#e2e8f0', zeroline: false },
    legend: { orientation: 'h', y: 1.15 },
  }, extra);
}
Plotly.react('chartX', traces, plotlyLayout({}), { displayModeBar: false, responsive: true });
```
Luôn `Plotly.react()` khi vẽ lại (KHÔNG `newPlot()`), gridcolor cố định `#e2e8f0`, `displayModeBar:false`.

**Nếu dùng Chart.js** (cdnjs 4.4.0, phù hợp dashboard nhiều chart nhỏ/nhiều trang):
```js
var charts = {};
function dc(id) { try { charts[id] && charts[id].destroy(); } catch (e) {} }
function mkBar(id, cfg) {
  dc(id);
  charts[id] = new Chart(document.getElementById(id), Object.assign({}, cfg, {
    options: Object.assign({ responsive: true, maintainAspectRatio: false }, cfg.options || {})
  }));
}
```
Canvas luôn bọc trong wrapper cố định chiều cao:
```html
<div class="ch-wrap" style="height:150px"><canvas id="chartX"></canvas></div>
```
```css
.ch-wrap > canvas { display:block; width:100% !important; height:100% !important; }
```
Gọi `dc(id)` đầu MỌI hàm vẽ chart trước khi tạo mới — thiếu bước này sẽ lỗi "Canvas already in use" khi filter đổi.

Với mỗi chart, ghi rõ ngay lúc thiết kế (đừng để code tự suy diễn): loại chart, cột nguồn, cách aggregate (group theo cột nào, SUM/AVG/COUNT), và ngưỡng màu nếu cần thể hiện hiệu suất — ví dụ chia tercile: 33% thấp nhất → role 3 (xanh, tốt), 33% giữa → role 5 (cam, trung bình), 33% cao nhất → role 4 (đỏ, kém).

### 3.6 Bảng dữ liệu top-N

Rule cố định: aggregate theo cột định danh (SUM các cột số) → tính lại các chỉ số tỷ lệ SAU khi gộp (VD `CPL = Spend/Leads` tính sau khi đã SUM Spend và Leads theo nhóm, không SUM CPL trực tiếp) → sort giảm dần theo cột chính → cắt top N (thường 10-15). Cột số dùng font DM Mono; có thể thêm 1 cột "Progress" là thanh ngang cao ~7px, độ rộng tỉ lệ `value/max(value)`, màu theo role của nhóm dòng đó.

### 3.7 Hàm format số — bắt buộc kiểu Việt Nam

```js
function fmt(n) {
  if (n == null || isNaN(n)) return '—';
  var neg = n < 0; n = Math.abs(n);
  var s;
  if (n >= 1e9) s = (n / 1e9).toLocaleString('vi-VN', { maximumFractionDigits: 1 }) + ' tỷ';
  else if (n >= 1e6) s = (n / 1e6).toLocaleString('vi-VN', { maximumFractionDigits: 1 }) + ' tr';
  else s = Math.round(n).toLocaleString('vi-VN');
  return (neg ? '-' : '') + s;
}
```
`toLocaleString('vi-VN')` tự cho dấu chấm ngăn hàng nghìn + dấu phẩy cho phần thập phân — đúng chuẩn Việt Nam, không tự viết regex thay dấu tay. Dùng 1 hàm `fmt()` này ở MỌI nơi hiển thị số (KPI, bảng, tick label chart) — không viết rule format riêng lẻ ở từng chart.

### 3.8 Animation — code cụ thể

```css
@keyframes fadeUp { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: translateY(0); } }
.fade-up { animation: fadeUp .5s ease both; }
```
```js
function runEntryAnimation() {
  document.querySelectorAll('.kpi-card').forEach(function (el, i) {
    el.classList.add('fade-up'); el.style.animationDelay = (i * 70) + 'ms';
  });
  document.querySelectorAll('.chart-card').forEach(function (el, i) {
    el.classList.add('fade-up'); el.style.animationDelay = (350 + i * 80) + 'ms';
  });
}
```
Chỉ gọi `runEntryAnimation()` 1 lần (xem `window._dashAnimated` ở mục 3.3) — filter đổi thì render lại data nhưng KHÔNG chạy lại animation.

### 3.9 Responsive — breakpoint cụ thể

```css
@media (max-width: 960px) {
  .kpi-grid { grid-template-columns: repeat(2, 1fr); }
  .chart-row-2, .chart-row-3 { grid-template-columns: 1fr; }
  .filter-bar { flex-direction: column; align-items: stretch; }
}
```
Nếu dashboard ưu tiên hiển thị màn hình rộng cho demo/TV (không cần dùng trên điện thoại) thì có thể bỏ qua mục này khi user xác nhận không cần responsive — nhưng mặc định vẫn nên có vì Lark có thể mở trên mobile app.

## Bước 4 — Viết file HTML dashboard

- Viết file HTML **đầy đủ**, tự có `<!doctype html><html><head><meta charset="utf-8">...`. KHÔNG viết theo kiểu fragment (như Claude Artifacts tự động bọc) — route `/d/{embed_id}` của app KHÔNG tự bọc HTML, thiếu phần này từng gây lỗi hiển thị tiếng Việt (mojibake) khi test thật.
- Nếu dashboard chỉ cần 1 grain dữ liệu (1 bảng, 1 cách nhóm) → 1 file, dùng `fetch('data')` trả về `{columns, rows}` (đường dẫn tương đối — app tự chèn `<base href="/d/{embed_id}/">` nên luôn trỏ đúng).
- Nếu cần nhiều grain khác nhau (ví dụ: xu hướng theo ngày + snapshot theo SKU + snapshot theo kho), **tối đa 3 bảng**: 1 embed dùng được `data_query_spec` dạng nhiều bảng (xem Bước 5) — `fetch('data')` lúc đó trả về `{tên_1: {columns, rows}, tên_2: {...}, ...}` (object có key là đúng tên bạn đặt trong spec) thay vì object phẳng, code JS phải đọc theo đúng tên đó.
- Nếu cần HƠN 3 bảng (hiếm, cân nhắc lại xem có nên gộp bớt bằng view trước) mới cần tới workaround "nhiều embed":
  1. Viết thêm các file HTML "headless" tối giản (không cần đẹp, chỉ cần không rỗng) — mỗi file 1 `data_query_spec` riêng.
  2. User upload các file headless này TRƯỚC (xem Bước 6) để có `embed_id` thật cho từng cái.
  3. Trong file HTML chính, hardcode URL tuyệt đối tới các embed đó: `fetch('/d/<embed_id-đã-có>/data')`, cộng với `fetch('data')` cho chính spec của nó (đơn hoặc nhiều bảng, tối đa 3).
  4. Vẫn chỉ có **1 link duy nhất** (file chính) đưa cho người xem — các file headless không ai cần mở trực tiếp.
- Định dạng số kiểu Việt Nam trừ khi user yêu cầu khác: dưới 1 triệu ghi số nguyên đủ có dấu chấm ngăn cách hàng nghìn, từ 1 triệu trở lên rút gọn "X tr", từ 1 tỷ "X tỷ" — không dùng K/M/B kiểu Anh.
- Trước khi coi là xong, tự test cục bộ trong scratchpad: dựng 1 `http.server` giả lập route `/d/{id}` và `/d/{id}/data` (trả JSON mock cùng cấu trúc `{columns, rows}` sẽ nhận từ BigQuery thật), `node --check` soát cú pháp JS, và chụp ảnh bằng headless Chrome (`--headless=new --screenshot`) để xác nhận layout/số liệu hiển thị đúng — đặc biệt nếu có nhiều tab/filter thì dùng 1 đoạn script tự động click qua từng trạng thái trước khi chụp. Dọn hết file test (mock JSON, server.py, ảnh png) sau khi xong, chỉ để lại các file HTML thật sẽ giao cho user.

## Bước 5 — Soạn `data_query_spec` (nếu muốn dữ liệu sống)

Đây là JSON mà server dùng để tự dựng lại 1 câu `SELECT` MỖI LẦN user mở link (không phải SQL tự do — validate chặt ở `app/embeds/query_spec.py`). Cấu trúc:

```json
{
  "table_id": "surya-495408.00_serving_inventory.vw_ten_moi",
  "columns": ["brand_id", "warehouse_code"],
  "aggregations": [
    {"column": "physical_qty", "fn": "SUM", "alias": "physical_qty_sum"}
  ],
  "filters": [
    {"column": "brand_id", "op": "eq", "value": "HPVN", "type": "STRING"}
  ],
  "order_by": [{"column": "physical_qty_sum", "direction": "desc"}],
  "limit": 500
}
```

Ràng buộc phải tôn trọng khi soạn (server sẽ từ chối nếu sai):
- `table_id`: đúng bảng đã xác nhận ở Bước 2 (nằm trong 1 trong 3 dataset serving whitelist).
- `columns` / `aggregations[].column` / `filters[].column`: phải là tên cột THẬT của bảng đó — không suy đoán.
- `aggregations[].fn`: chỉ `SUM | COUNT | AVG | MIN | MAX`. `alias`: chỉ chữ/số/gạch dưới, không bắt đầu bằng số, không trùng tên cột hay alias khác.
- `filters[].op`: chỉ `eq|ne|gt|gte|lt|lte`. `filters[].type`: chỉ `STRING|INT64|FLOAT64|BOOL|DATE|TIMESTAMP` — phải khớp kiểu thật của cột.
- `order_by[].column`: BẮT BUỘC phải là 1 tên nằm trong `columns` hoặc là 1 `alias` của `aggregations` — không sort được theo cột chưa SELECT.
- Có cả `columns` và `aggregations` → tự động `GROUP BY` theo `columns`. Chỉ có `aggregations` (không `columns`) → trả về đúng 1 dòng tổng hợp toàn bảng.
- `limit`: số nguyên dương, tối đa 10000 (mặc định 500 nếu bỏ trống).
- Không hỗ trợ JOIN/subquery/SQL tự do trong spec — logic phức tạp hơn phải giải quyết bằng cách tạo view ở Bước 2, giữ spec ở đây đơn giản (1 bảng, 1 tầng aggregation).

### Nhiều bảng trong 1 embed (tối đa 3)

Nếu dashboard cần nhiều grain/bảng (Bước 4), bọc từng spec đơn ở trên vào 1 object `specs`, mỗi key là 1 tên bạn tự đặt (chỉ chữ/số/gạch dưới, không bắt đầu bằng số — đây cũng là key mà `fetch('data')` trả về):

```json
{
  "specs": {
    "trend_theo_ngay": { "table_id": "...", "columns": ["order_date"], "aggregations": [...] },
    "snapshot_sku":    { "table_id": "...", "columns": ["sku"], "aggregations": [...] }
  }
}
```

Tối đa 3 key trong `specs` — quá số này server từ chối lúc upload. Vượt quá 3 bảng thì dùng pattern nhiều embed ở Bước 4.

Nếu vẫn cần vượt quá 3 bảng (pattern nhiều embed ở Bước 4), soạn 1 khối JSON RIÊNG cho từng file (ghi rõ khối nào ứng với file nào khi giao cho user).

Lưu ý cache: metadata cột của app có TTL cache 10 phút (`app/datasource/bq_meta.py`). Nếu vừa tạo/sửa view ở Bước 2, đợi ít nhất ~10 phút trước khi user upload spec dùng cột mới, nếu không sẽ gặp lỗi "cột không tồn tại" dù cột đã có thật — không phải bug, chỉ cần đợi rồi thử lại.

## Bước 5b — Dữ liệu sống bằng file thay vì BigQuery

Dùng khi dữ liệu KHÔNG nằm trong BigQuery — user tự theo dõi bằng 1 file Excel/CSV riêng
(ngoài phạm vi Serving) và muốn dashboard tự cập nhật số mỗi khi họ tải file mới lên, không
cần đổi link. Đây là lựa chọn thay thế cho `data_query_spec` (Bước 5), KHÔNG dùng chung 1
embed với BigQuery — 1 dashboard chỉ chọn 1 trong 2 nguồn.

Server chỉ lưu/host lại nguyên file, KHÔNG parse gì cả — dashboard tự đọc bằng SheetJS y hệt
cách 2 dashboard mẫu tham khảo (Marketing Operations, Supply Chain Management) đã đọc file
user chọn tay, chỉ khác là fetch từ URL cố định thay vì chờ người xem tự bấm nút Upload:

```js
fetch('data-file')                       // URL tương đối, app tự chèn <base> đúng chỗ
  .then(r => r.arrayBuffer())
  .then(buf => {
    var wb = XLSX.read(buf, { type: 'array' });
    var rows = XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], { raw: true });
    renderDashboard(rows);
  });
```

Nếu muốn giữ luôn màn hình "Upload Excel" thủ công cho lần đầu (chưa có file trên server) thì
gọi `fetch('data-file')` trước, bắt lỗi 404 rồi fallback về UI chọn file tay như bình thường.

Giao cho user: đưa file HTML, dặn khi upload ở `/embeds.html` chọn chế độ dữ liệu sống
**"📄 File Excel/CSV"** (thay vì "🗄️ Bảng BigQuery") và chọn file dữ liệu mẫu cùng lúc. Sau
này cần cập nhật số liệu, họ chỉ cần bấm "✏️ Sửa" → chọn lại file dữ liệu mới ở đúng ô đó →
Lưu — link không đổi.

## Bước 6 — Giao sản phẩm cho user

Trả lời user gồm:

1. **File HTML** — họ mở xem được ngay bằng trình duyệt (không cần upload gì cả nếu chỉ cần xem, không cần realtime).
2. **(Nếu có dữ liệu sống)** khối JSON `data_query_spec` tương ứng, và hướng dẫn cụ thể:
   - Vào `https://ai-dashboard-builder-2eodhfgo5a-as.a.run.app/embeds.html` (tab "📊 Nhúng dashboard vào Lark"), cần đăng nhập Lark trước; chỉ user đã được thêm vào whitelist upload mới thấy được form.
   - Nhập **Tên dashboard**, chọn **File HTML**.
   - Nếu muốn dữ liệu tự cập nhật: bật toggle **"Bật dữ liệu sống"** → chọn chế độ **"📝 Nhập JSON trực tiếp"** → dán đúng khối JSON bạn đưa (hoặc chọn **"🖱️ Chọn bằng dropdown"** để tự bấm chọn bảng/cột/hàm tương đương nếu họ muốn tự chỉnh tay — dropdown chỉ chọn được 1 bảng, spec nhiều bảng (`{"specs": {...}}`) BẮT BUỘC dùng chế độ JSON).
   - Bấm **Upload** → nhận link `/d/{embed_id}` → copy link đó dán thẳng vào Lark (nhúng dạng iframe/embed bình thường, không cần cấu hình gì thêm — đã test thật, hoạt động).
   - Nếu dùng pattern nhiều file (Bước 4): nhắc user upload các file **headless trước**, lấy `embed_id` thật của từng cái, rồi báo lại cho Claude để sửa URL cứng trong file chính trước khi họ upload file chính (hoặc Claude tự đoán trước 1 placeholder rõ ràng và dặn user tìm-thay bằng embed_id thật).
   - Sau này muốn đổi tên hoặc đổi `data_query_spec` (không đổi giao diện/logic HTML): bấm **"✏️ Sửa"** trong danh sách embed — KHÔNG đổi link. Muốn đổi nội dung/logic file HTML thì phải **"Thu hồi"** rồi upload lại — link sẽ đổi (embed_id mới), nhớ nhắc user cập nhật lại chỗ đã nhúng trong Lark nếu link đổi.

Nếu tóm tắt lại toàn bộ hướng dẫn trên thành 1 dòng ngắn gọn kiểu "Cách nhúng: ..." ở cuối câu trả lời, LUÔN viết đầy đủ URL tuyệt đối `https://ai-dashboard-builder-2eodhfgo5a-as.a.run.app/embeds.html` ngay ở bước đầu tiên — TUYỆT ĐỐI không rút gọn thành đường dẫn tương đối kiểu `/embeds.html`, vì user đọc dòng tóm tắt đó cần bấm/copy thẳng được, không tự suy ra domain từ ngữ cảnh. Mẫu:

> **Cách nhúng:** truy cập https://ai-dashboard-builder-2eodhfgo5a-as.a.run.app/embeds.html → tab "📊 Nhúng dashboard vào Lark" → nhập tên, chọn file HTML trên → bật "Dữ liệu sống" → "📝 Nhập JSON trực tiếp" → dán JSON trên → Upload → copy link `/d/{id}` dán vào Lark.

## Việc không được làm

- Không bịa số liệu hoặc suy đoán tên cột — mọi thứ trong dashboard và trong `data_query_spec` phải đối chiếu với schema/dữ liệu thật đã đọc ở Bước 1.
- Không tự ý mở rộng phạm vi bảng ra ngoài whitelist Serving để "cho tiện" — nếu bảng cần thiết nằm ngoài whitelist, phải tạo view pass-through (Bước 2), không có cách nào khác.
- Không quên authorized-view access ở TOÀN BỘ chuỗi dataset khi tạo view mới — thiếu 1 hop sẽ ra lỗi 500 khó chẩn đoán từ log, không phải lỗi spec.
- Không so sánh/suy diễn số liệu ở 1 chiều dữ liệu mà 1 trong các bảng nguồn không có (lệch grain) — chỉ so sánh ở mức chung mà cả hai bảng đều có.
