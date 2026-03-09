FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV WHISPER_MODEL=medium

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    patchelf \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt && \
    find /usr/local/lib -name "libctranslate2*.so*" \
         -exec patchelf --clear-execstack {} \;

RUN python -c "import os; from huggingface_hub import snapshot_download; m=os.environ['WHISPER_MODEL']; snapshot_download(f'Systran/faster-whisper-{m}', local_dir=f'/models/faster-whisper-{m}')"

COPY . .

ENV PORT=8080
ENV HF_HUB_OFFLINE=1
EXPOSE 8080

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
