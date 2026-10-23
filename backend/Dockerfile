# Backend image — template from docs/REQUIREMENTS.md section 20.
# A complete Django project (config/, apps/, manage.py) and a hashed
# requirements.lock are required before this image can be built.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libpq5 libgdal32 libgeos-c1v5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock /app/requirements.lock

RUN pip install --require-hashes -r requirements.lock

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app \
       --create-home app

COPY --chown=app:app . /app

USER app

EXPOSE 8000

CMD ["gunicorn", "config.asgi:application", \
     "-k", "uvicorn_worker.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
