FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*
COPY . .
# A base de dados e os resumos vivem em /data (montar um volume persistente aqui)
ENV GS_DATABASE_URL=sqlite:////data/governo_sombra.db GS_HOST=0.0.0.0 GS_PORT=8000 GS_SCHEDULER=1
RUN mkdir -p /data && chmod +x scripts/arrancar.sh
EXPOSE 8000
CMD ["scripts/arrancar.sh"]
