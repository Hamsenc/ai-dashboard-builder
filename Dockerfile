# Cần Node.js vì claude-agent-sdk gọi ngầm CLI `claude` (npm package
# @anthropic-ai/claude-code) để auth bằng CLAUDE_CODE_OAUTH_TOKEN — không phải chỉ
# gọi thẳng REST API như anthropic SDK thông thường.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get purge -y curl gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

WORKDIR /app/app
ENV PORT=8080
# --proxy-headers + --forwarded-allow-ips="*": Cloud Run terminate TLS ở tầng ngoài
# rồi forward vào container bằng HTTP nội bộ — thiếu cờ này thì request.url_for()
# (dùng để sinh redirect_uri cho Lark OAuth) sẽ ra scheme "http://" sai, phải khớp
# đúng https:// mới đăng ký được với Lark Developer Console.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
