FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5080

# Single worker on purpose: the background health-check thread lives inside
# the worker process, so >1 worker would run duplicate checkers.
CMD ["gunicorn", "--bind", "0.0.0.0:5080", "--workers", "1", "--threads", "8", "app:app"]
