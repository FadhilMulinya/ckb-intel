FROM python:3.11-slim

# Keep the service one level below /app: V2 resolves ../ckb_data from here.
WORKDIR /app/classifier_service
COPY classifier_service/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY classifier_service/app.py classifier_service/inference_cli.py classifier_service/v2_service.py classifier_service/environments.py ./
COPY classifier_service/wallet_intelligence ./wallet_intelligence
# Frozen SQLite is supplied separately as a read-only bind mount, never baked in.
RUN mkdir -p /app/ckb_data/ckb_data_v2 && useradd --uid 10001 --no-create-home app
USER app
EXPOSE 8000
# One worker keeps the in-process live-analysis semaphore authoritative.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
