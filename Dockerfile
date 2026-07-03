FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    libglib2.0-0 \
    libgobject-2.0-0 \
    libcairo2 \
    libharfbuzz0b \
    fonts-liberation \
    fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY app/ /app/
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /app/output

ENTRYPOINT ["python", "main.py"]
