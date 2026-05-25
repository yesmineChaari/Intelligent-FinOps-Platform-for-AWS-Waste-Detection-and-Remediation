FROM python:3.11-slim

WORKDIR /app

COPY agent1/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY agent1/ ./agent1/
COPY shared/ ./shared/
COPY rules.yaml ./rules.yaml

CMD ["python", "-m", "agent1.main"]
