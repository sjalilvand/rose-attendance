# Backend image — template from docs/REQUIREMENTS.md section 20.
# A complete Django project (config/, apps/, manage.py) and a hashed
# requirements.lock are required before this image can be built.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# GeoDjango runtime libraries. The soname package names differ between
# Debian releases (bookworm: libgdal32 + libgeos-c1v5; trixie: libgdal36 +
# libgeos-c1t64) and python:3.12-slim now tracks trixie — resolve them
# dynamically from the apt cache instead of hard-coding a release.
RUN set -eux; \
    apt-get update; \
    GDAL_PKG="$(apt-cache pkgnames libgdal | grep -E '^libgdal[0-9]+$' | sort -V | tail -n 1)"; \
    GEOS_PKG="$(apt-cache pkgnames libgeos-c1 | grep -E '^libgeos-c1([vt][0-9]+)?$' | sort -V | tail -n 1)"; \
    echo "GeoDjango runtime: GDAL=${GDAL_PKG} GEOS=${GEOS_PKG}"; \
    test -n "${GDAL_PKG}" && test -n "${GEOS_PKG}"; \
    apt-get install -y --no-install-recommends libpq5 "${GDAL_PKG}" "${GEOS_PKG}"; \
    rm -rf /var/lib/apt/lists/*

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
