FROM python:3.11-alpine AS builder
RUN apk add --no-cache gcc musl-dev postgresql-dev
WORKDIR /app
COPY requirements.txt .
RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install --no-cache-dir --user -r requirements.txt

FROM python:3.11-alpine AS runner
RUN apk add --no-cache libpq
WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PATH=/root/.local/bin:$PATH
COPY --from=builder /root/.local /root/.local
COPY main.py .
EXPOSE 8000
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "main:app", "--bind", "0.0.0.0:8000", "--workers", "2", "--log-level", "info"]
