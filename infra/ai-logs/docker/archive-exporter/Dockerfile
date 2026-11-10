FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY archive_logs.py .

ENTRYPOINT ["python", "-u", "archive_logs.py"]
CMD ["serve"]
