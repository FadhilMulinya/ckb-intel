FROM python:3.11-slim

WORKDIR /app
# Build from the repository root: docker build -f classifier-service/Dockerfile .
COPY classifier-service/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY classifier-service/app.py classifier-service/inference_cli.py classifier-service/v2_service.py ./
COPY classifier-service/wallet_intelligence ./wallet_intelligence
COPY ckb_data ./ckb_data

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
