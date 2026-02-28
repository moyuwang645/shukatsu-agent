FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install ALL system deps required by Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libpango-1.0-0 libasound2 libxshmfence1 libx11-xcb1 \
    libxfixes3 libcairo2 libcairo-gobject2 libgtk-3-0 libgdk-pixbuf-2.0-0 \
    libdbus-1-3 libatspi2.0-0 libxext6 libx11-6 libxcb1 \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (Docker cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium (system deps already installed above)
RUN python -m playwright install chromium

# Copy application code
COPY . .

# Create data directory
RUN mkdir -p data

EXPOSE 5000

CMD ["python", "app.py"]
