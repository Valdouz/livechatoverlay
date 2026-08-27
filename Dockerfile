FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server ./server

RUN useradd --create-home --uid 1000 livechat && mkdir -p /data && chown livechat /data
USER livechat
VOLUME /data
EXPOSE 3000

CMD ["python", "-m", "server"]
