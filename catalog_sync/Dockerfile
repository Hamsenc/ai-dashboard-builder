# catalog_sync KHÔNG gọi Claude — không cần Node.js, image nhẹ hơn image chính.
FROM python:3.12-slim

WORKDIR /job

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

CMD ["python", "job.py"]
