# ATL13 ingest service image (API and worker share it).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# rasterio's manylinux wheel links against the system libexpat.
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-service.txt ./
RUN pip install -r requirements-service.txt

COPY pyproject.toml alembic.ini ./
COPY src ./src
COPY config ./config
COPY migrations ./migrations
COPY data/aoi ./data/aoi
RUN pip install --no-deps -e .

EXPOSE 8000
CMD ["uvicorn", "kakhovka_altimetry.service.api:app", "--host", "0.0.0.0", "--port", "8000"]
