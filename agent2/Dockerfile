FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl unzip \
    && rm -rf /var/lib/apt/lists/*

COPY agent2/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY agent2/ ./agent2/
COPY shared/ ./shared/

CMD ["python", "-m", "agent2.main"]
