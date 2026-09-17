FROM python:3.11-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/prod.txt

COPY src/ src/
COPY scripts/ scripts/

ENV PYTHONPATH=/app/src
EXPOSE 5000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5000"]
