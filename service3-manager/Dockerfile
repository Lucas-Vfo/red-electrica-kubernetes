FROM python:3.11-alpine AS builder
RUN apk add --no-cache gcc musl-dev postgresql-dev
WORKDIR /app
COPY requirements.txt .
RUN python3 -m pip install --upgrade pip \
    && python3 -m pip install --no-cache-dir --user -r requirements.txt
COPY worker.py .

FROM python:3.11-alpine AS runner
WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PATH=/root/.local/bin:$PATH
COPY --from=builder /root/.local /root/.local
COPY worker.py .
CMD ["python3", "worker.py"]
