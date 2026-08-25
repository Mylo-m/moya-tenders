# MY-LO Moya — Cloud Run container
FROM python:3.11-slim

WORKDIR /app

# Install deps first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Pre-seed demo tenders so the live service has data immediately.
# (Real data is produced by the 6h scraper cron; this guarantees a non-empty demo.)
RUN python3 seed_demo.py

# Cloud Run sets PORT (default 8080); gunicorn serves the FastAPI app.
ENV PORT=8080
EXPOSE 8080
CMD exec gunicorn moya_api.server:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120
