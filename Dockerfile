FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so code changes don't invalidate the cached install layer.
COPY pyproject.toml README.md ./
COPY certgen/__init__.py certgen/__init__.py
RUN pip install .

COPY . .
RUN pip install --no-deps . \
    && useradd --create-home --uid 1000 certgen \
    && mkdir -p /app/storage \
    && chown -R certgen /app/storage
USER certgen

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"

CMD ["uvicorn", "certgen.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
