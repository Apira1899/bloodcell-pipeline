# /api – BloodMNIST inference API (FastAPI + ONNX Runtime)

| Endpoint | Description |
|---|---|
| `GET /health` | status + model loading time (used by liveness/readiness probes) |
| `GET /version` | API and model versions |
| `POST /predict` | body `{"file_name": "...", "image_base64": "<PNG/JPEG base64>"}` → cell type + confidence |
| `GET /metrics` | number of calls, successes, errors, average latency |

## Run locally (no Docker)
```bash
cd api
pip install -r requirements-dev.txt
MODEL_PATH=../model/model-1.0.0.onnx LABELS_PATH=../model/labels.json uvicorn app.main:app --port 8000
# open http://localhost:8000/docs
```

## Tests and lint
```bash
cd api
ruff check .
pytest -q          # 9 tests: success, invalid input (422), missing body (422), health, version, metrics
```
Tests build a tiny dummy ONNX model, so they do not need the trained model.

## Docker (build from the repository root)
```bash
docker build -f api/Dockerfile -t bloodcell-api:1.0.0 .
docker run -p 8000:8000 bloodcell-api:1.0.0
docker images bloodcell-api        # must be < 500 MB
```

## Call example
```bash
IMG=$(base64 -w0 demo_images/neutrophil_0.png)      # macOS: base64 -i file.png
curl -X POST https://<api-url>/predict -H "Content-Type: application/json" \
  -d "{\"file_name\":\"neutrophil_0.png\",\"image_base64\":\"$IMG\"}"
```

## Configuration (environment variables only)
| Variable | Default |
|---|---|
| `MODEL_VERSION` | `1.0.0` |
| `MODEL_PATH` | `/app/model/model-${MODEL_VERSION}.onnx` |
| `LABELS_PATH` | `/app/model/labels.json` |
| `MAX_IMAGE_BYTES` | `1000000` |
| `API_VERSION` | `1.0.0` |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | empty → telemetry off. On Azure, store it as a Container Apps **secret** |

Custom metrics sent to Application Insights: `inferences_total`, `model_latency_ms`, `prediction_errors_total`.
