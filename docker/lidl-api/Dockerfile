FROM python:3.11-slim

WORKDIR /app

# System dependencies required by Playwright's Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir fastapi "uvicorn[standard]" playwright httpx pytest pytest-asyncio

# Install Chromium browser
RUN playwright install chromium

COPY app.py .

# /scripts is volume-mounted at runtime (contains lidl_receipts.py)
# /data is volume-mounted at runtime (persistent disk)
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
