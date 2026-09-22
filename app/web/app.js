// Dùng chung giữa index.html và embeds.html — gọi API kèm X-Dev-User, bóc thẳng
// "detail" của lỗi FastAPI để hiện cho user đọc được thay vì JSON thô.
// Yêu cầu `devUser` đã tồn tại (biến toàn cục, mỗi trang tự khai báo `let devUser`
// trước khi gọi hàm này — an toàn vì thân hàm chỉ đọc devUser lúc GỌI, không lúc định nghĩa).
async function apiFetch(path, opts = {}) {
  opts.headers = Object.assign({'Content-Type': 'application/json', 'X-Dev-User': devUser}, opts.headers || {});
  const res = await fetch(path, opts);
  if (!res.ok) {
    const text = await res.text();
    let message = text;
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed.detail === 'string') message = parsed.detail;
    } catch (e) { /* không phải JSON, giữ nguyên text */ }
    throw new Error(message);
  }
  return res.json();
}
