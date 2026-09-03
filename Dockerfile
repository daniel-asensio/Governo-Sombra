FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# A base de dados e os resumos vivem em /data (montar um volume persistente aqui)
ENV GS_DATABASE_URL=sqlite:////data/governo_sombra.db GS_HOST=0.0.0.0 GS_PORT=8000 GS_SCHEDULER=1
RUN mkdir -p /data && chmod +x scripts/arrancar.sh
EXPOSE 8000
CMD ["scripts/arrancar.sh"]
