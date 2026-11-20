"""All configuration comes from environment variables (no secrets in code)."""
import os

API_VERSION = os.getenv("API_VERSION", "1.0.0")
MODEL_VERSION = os.getenv("MODEL_VERSION", "1.0.0")
MODEL_PATH = os.getenv("MODEL_PATH", f"/app/model/model-{MODEL_VERSION}.onnx")
LABELS_PATH = os.getenv("LABELS_PATH", "/app/model/labels.json")
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", "1000000"))  # 1 MB, same as input_schema.json
IMAGE_SIZE = int(os.getenv("IMAGE_SIZE", "28"))
# Telemetry is enabled only when this variable is set (Container Apps env var / secret)
APPINSIGHTS_CONNECTION_STRING = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
