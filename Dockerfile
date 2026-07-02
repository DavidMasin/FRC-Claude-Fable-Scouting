# frcscout web UI — Railway-ready image.
# Railway injects $PORT; job state lives in one gunicorn worker (scale with
# threads). Mount a volume at /data so scouted matches survive deploys.

FROM python:3.11-slim

# opencv-python-headless needs libglib; ffmpeg helps with odd stream formats
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[ui,ingest]" gunicorn

# seed rubric shipped with the repo; regenerate with `frcscout rubric build --fetch`
COPY rubric.json ./rubric.json

ENV FRCSCOUT_OUT_DIR=/data/out \
    PYTHONUNBUFFERED=1

EXPOSE 8080
CMD ["sh", "-c", "gunicorn -w 1 --threads 8 --timeout 120 -b 0.0.0.0:${PORT:-8080} frcscout.ui.wsgi:app"]
