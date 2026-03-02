FROM python:3.12-slim

# System deps: Node, pnpm, Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates git \
    chromium chromium-driver \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g pnpm \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install-deps chromium \
    && playwright install chromium

# Node deps + build
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build

EXPOSE 41900

CMD ["python3", "main.py"]
