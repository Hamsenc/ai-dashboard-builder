---
name: lark-dashboard-embed
description: Build 1 dashboard/báo cáo HTML từ dữ liệu BigQuery thật (project surya-495408) rồi giao cho user kèm hướng dẫn nhúng vào Lark qua tính năng Dashboard Embeds của app ai-dashboard-builder. LUÔN dùng skill này khi user nhờ "làm dashboard", "làm báo cáo", "trực quan hoá số liệu", "vẽ biểu đồ từ bảng X", hoặc nói họ muốn share 1 báo cáo lên Lark/nhúng vào tài liệu Lark — kể cả khi họ chỉ đưa tên bảng và nói chung chung "làm cho tao cái dashboard theo dõi...". Không dùng skill này nếu user chỉ hỏi số liệu để trả lời trực tiếp trong chat (không cần file/link chia sẻ).
---

# Build dashboard BigQuery + nhúng Lark (Dashboard Embeds)

Quy trình đầy đủ mà user đã chọn, gồm 3 việc — chỉ việc 2 và 3 là của Claude:

1. **User tự tư vấn chọn bảng** ở `https://ai-dashboard-builder-2eodhfgo5a-as.a.run.app/` (tab "🗂️ Tư vấn chọn bảng") — việc này KHÔNG cần Claude, user tự làm trước khi nhờ bạn, hoặc họ có thể chỉ thẳng tên bảng cho bạn nếu đã biết.
2. **Claude đọc bảng thật, viết file HTML dashboard** — việc chính của skill này.
3. **User upload file lên `/embeds.html` để lấy link nhúng Lark** — Claude chỉ cần đưa đúng file + đúng hướng dẫn, không tự upload hộ (upload gated theo whitelist email qua Lark OAuth, Claude không có phiên đăng nhập đó).

Đừng bịa số liệu ở bất kỳ bước nào — mọi con số trong dashboard phải đến từ 1 query thật đã chạy, không suy đoán từ tên cột.

## Trước khi bắt đầu — điều kiện cần có

Skill này giả định trước, không tự thiết lập hộ:

- **Đọc BigQuery**: session Claude hiện tại có quyền đọc project `surya-495408` — qua `bq` CLI đã đăng nhập (`gcloud auth`/service account), hoặc qua BigQuery MCP connector đã kết nối. Kiểm tra nhanh bằng `bq ls --project_id=surya-495408 00_serving_inventory`; nếu bị từ chối quyền, báo lại cho user để họ nhờ quản trị GCP của công ty cấp quyền trước, đừng đoán mò tiếp.
- **Tạo view + cấp quyền (chỉ cần khi vào Bước 2 nhánh view mới)**: cần thêm quyền BigQuery Data Editor trên dataset serving đích + quyền cập nhật ACL (`bq update`) trên các dataset nguồn. Nếu tài khoản hiện tại không có quyền này, ĐỪNG cố lách qua cách khác — báo rõ cho user để họ nhờ admin BigQuery thực hiện hộ đoạn cấp quyền, hoặc chọn phương án dùng thẳng view/bảng đã có sẵn trong tầng serving.
- **Upload lên app (Bước 5)**: user cần tài khoản Lark đã được thêm vào whitelist upload của app `ai-dashboard-builder`. Việc này Claude không làm thay được (upload gated qua phiên đăng nhập Lark của chính user) — nếu họ chưa có quyền, họ cần liên hệ admin app trước khi làm tới bước này.

## Bước 1 — Xác nhận & đọc bảng nguồn

Xác định tên bảng đầy đủ dạng `surya-495408.<dataset>.<table>`. Nếu user chỉ nói tên ngắn hoặc mô tả ("bảng tồn kho", "doanh thu theo ngày"), tự tìm bằng cách liệt kê bảng trong dataset liên quan trước khi đoán.

Đọc schema + vài dòng mẫu THẬT trước khi thiết kế bất cứ gì. Có 2 cách, dùng cách nào cũng được — ưu tiên `bq` CLI vì nó dùng được cho cả bước sau (tạo view, cấp quyền), còn BigQuery MCP chỉ đọc:

```bash
bq show --schema --format=prettyjson surya-495408:<dataset>.<table>
bq query --use_legacy_sql=false --project_id=surya-495408 'SELECT * FROM `surya-495408.<dataset>.<table>` LIMIT 20'
```

Luôn truyền `--project_id=surya-495408` (hoặc `<project>:` trước tên dataset) tường minh trong mọi lệnh `bq` — đừng giả định project mặc định của môi trường đang chạy đã trỏ sẵn về đây. Nếu dùng BigQuery MCP thay vì `bq`, tìm và load tool đó trước khi dùng (nó chỉ đọc — không dùng được cho phần tạo view/cấp quyền ở Bước 2).

Đọc luôn `description`/Business Definition của các cột số liệu quan trọng — bảng ở project này hay ghi sẵn sentinel value kiểu `(9999 = không bán được, không tính)` trong mô tả cột; nếu có, PHẢI loại giá trị đó khỏi biểu đồ/trung vị và show riêng thành 1 chỉ số khác, không được vẽ lẫn vào như số liệu thật.

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

- Nếu chỉ cần dashboard "tĩnh" (số liệu chốt tại lúc build, không cần tự cập nhật) thì bỏ qua toàn bộ ràng buộc này — chỉ cần query 1 lần lấy số thật rồi nhúng cứng vào HTML, không cần `data_query_spec` (xem Bước 4).

## Bước 3 — Viết file HTML dashboard

- Viết file HTML **đầy đủ**, tự có `<!doctype html><html><head><meta charset="utf-8">...`. KHÔNG viết theo kiểu fragment (như Claude Artifacts tự động bọc) — route `/d/{embed_id}` của app KHÔNG tự bọc HTML, thiếu phần này từng gây lỗi hiển thị tiếng Việt (mojibake) khi test thật.
- Nếu dashboard chỉ cần 1 grain dữ liệu (1 bảng, 1 cách nhóm) → 1 file, dùng `fetch('data')` (đường dẫn tương đối — app tự chèn `<base href="/d/{embed_id}/">` nên luôn trỏ đúng).
- Nếu cần nhiều grain khác nhau (ví dụ: xu hướng theo ngày + snapshot theo SKU + snapshot theo kho) — 1 embed chỉ chạy được ĐÚNG 1 spec, nên:
  1. Viết thêm các file HTML "headless" tối giản (không cần đẹp, chỉ cần không rỗng) — mỗi file 1 `data_query_spec` riêng cho 1 grain phụ.
  2. User upload các file headless này TRƯỚC (xem Bước 5) để có `embed_id` thật cho từng cái.
  3. Trong file HTML chính, hardcode URL tuyệt đối tới các embed đó: `fetch('/d/<embed_id-đã-có>/data')`, cộng với `fetch('data')` cho chính spec của nó.
  4. Vẫn chỉ có **1 link duy nhất** (file chính) đưa cho người xem — các file headless không ai cần mở trực tiếp.
- Định dạng số kiểu Việt Nam trừ khi user yêu cầu khác: dưới 1 triệu ghi số nguyên đủ có dấu chấm ngăn cách hàng nghìn, từ 1 triệu trở lên rút gọn "X tr", từ 1 tỷ "X tỷ" — không dùng K/M/B kiểu Anh.
- Trước khi coi là xong, tự test cục bộ trong scratchpad: dựng 1 `http.server` giả lập route `/d/{id}` và `/d/{id}/data` (trả JSON mock cùng cấu trúc `{columns, rows}` sẽ nhận từ BigQuery thật), `node --check` soát cú pháp JS, và chụp ảnh bằng headless Chrome (`--headless=new --screenshot`) để xác nhận layout/số liệu hiển thị đúng — đặc biệt nếu có nhiều tab/filter thì dùng 1 đoạn script tự động click qua từng trạng thái trước khi chụp. Dọn hết file test (mock JSON, server.py, ảnh png) sau khi xong, chỉ để lại các file HTML thật sẽ giao cho user.

## Bước 4 — Soạn `data_query_spec` (nếu muốn dữ liệu sống)

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
- `limit`: số nguyên dương, tối đa 1000 (mặc định 500 nếu bỏ trống).
- Không hỗ trợ JOIN/subquery/SQL tự do trong spec — logic phức tạp hơn phải giải quyết bằng cách tạo view ở Bước 2, giữ spec ở đây đơn giản (1 bảng, 1 tầng aggregation).

Nếu dashboard dùng pattern nhiều embed (Bước 3), soạn 1 khối JSON RIÊNG cho từng file (ghi rõ khối nào ứng với file nào khi giao cho user).

Lưu ý cache: metadata cột của app có TTL cache 10 phút (`app/datasource/bq_meta.py`). Nếu vừa tạo/sửa view ở Bước 2, đợi ít nhất ~10 phút trước khi user upload spec dùng cột mới, nếu không sẽ gặp lỗi "cột không tồn tại" dù cột đã có thật — không phải bug, chỉ cần đợi rồi thử lại.

## Bước 5 — Giao sản phẩm cho user

Trả lời user gồm:

1. **File HTML** — họ mở xem được ngay bằng trình duyệt (không cần upload gì cả nếu chỉ cần xem, không cần realtime).
2. **(Nếu có dữ liệu sống)** khối JSON `data_query_spec` tương ứng, và hướng dẫn cụ thể:
   - Vào `https://ai-dashboard-builder-2eodhfgo5a-as.a.run.app/embeds.html` (tab "📊 Nhúng dashboard vào Lark"), cần đăng nhập Lark trước; chỉ user đã được thêm vào whitelist upload mới thấy được form.
   - Nhập **Tên dashboard**, chọn **File HTML**.
   - Nếu muốn dữ liệu tự cập nhật: bật toggle **"Bật dữ liệu sống"** → chọn chế độ **"📝 Nhập JSON trực tiếp"** → dán đúng khối JSON bạn đưa (hoặc chọn **"🖱️ Chọn bằng dropdown"** để tự bấm chọn bảng/cột/hàm tương đương nếu họ muốn tự chỉnh tay).
   - Bấm **Upload** → nhận link `/d/{embed_id}` → copy link đó dán thẳng vào Lark (nhúng dạng iframe/embed bình thường, không cần cấu hình gì thêm — đã test thật, hoạt động).
   - Nếu dùng pattern nhiều file (Bước 3): nhắc user upload các file **headless trước**, lấy `embed_id` thật của từng cái, rồi báo lại cho Claude để sửa URL cứng trong file chính trước khi họ upload file chính (hoặc Claude tự đoán trước 1 placeholder rõ ràng và dặn user tìm-thay bằng embed_id thật).
   - Sau này muốn đổi tên hoặc đổi `data_query_spec` (không đổi giao diện/logic HTML): bấm **"✏️ Sửa"** trong danh sách embed — KHÔNG đổi link. Muốn đổi nội dung/logic file HTML thì phải **"Thu hồi"** rồi upload lại — link sẽ đổi (embed_id mới), nhớ nhắc user cập nhật lại chỗ đã nhúng trong Lark nếu link đổi.

## Việc không được làm

- Không bịa số liệu hoặc suy đoán tên cột — mọi thứ trong dashboard và trong `data_query_spec` phải đối chiếu với schema/dữ liệu thật đã đọc ở Bước 1.
- Không tự ý mở rộng phạm vi bảng ra ngoài whitelist Serving để "cho tiện" — nếu bảng cần thiết nằm ngoài whitelist, phải tạo view pass-through (Bước 2), không có cách nào khác.
- Không quên authorized-view access ở TOÀN BỘ chuỗi dataset khi tạo view mới — thiếu 1 hop sẽ ra lỗi 500 khó chẩn đoán từ log, không phải lỗi spec.
