FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1

RUN python -m pip install --no-cache-dir \
    duckdb==1.5.6 \
    pyarrow==25.0.1 \
    pytz==2026.2

WORKDIR /opt/worker

USER 65534:65534

CMD ["python", "-c", "import duckdb, pyarrow; print('Analytical dependencies ready')"]
