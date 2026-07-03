FROM python:3.11-alpine AS builder
RUN apk add --no-cache gcc musl-dev postgresql-dev
WORKDIR /app
COPY requirements.txt .
RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install --no-cache-dir --user -r requirements.txt
COPY main.py .

FROM python:3.11-alpine AS runner
WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PATH=/root/.local/bin:$PATH
COPY --from=builder /root/.local /root/.local
COPY main.py .
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "main:app", "--bind", "0.0.0.0:8000", "--workers", "2", "--log-level", "info"]
