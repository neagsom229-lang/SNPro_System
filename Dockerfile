FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p instance storage

EXPOSE 5000

CMD ["gunicorn", "-b", "0.0.0.0:5000", "-w", "3", "--timeout", "300", "run:app"]
