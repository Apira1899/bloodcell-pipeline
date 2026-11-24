"""BloodMNIST inference API: GET /health, GET /version, POST /predict, GET /metrics."""
import base64
import binascii
import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from . import config, telemetry
from .model import BloodCellModel, InvalidImageError

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("api")

state = {"model": None, "error": None}


class Stats:
    """In-memory counters for GET /metrics (per replica)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.calls = self.success = self.errors = 0
        self.total_ms = 0.0
        self.started = time.time()

    def add(self, ms: float, ok: bool):
        with self.lock:
            self.calls += 1
            self.success += ok
            self.errors += not ok
            self.total_ms += ms


stats = Stats()


@asynccontextmanager
async def lifespan(app: FastAPI):
    telemetry.setup_telemetry()
    try:
        state["model"] = BloodCellModel(config.MODEL_PATH, config.LABELS_PATH, config.IMAGE_SIZE)
        log.info("model %s loaded in %s ms", config.MODEL_VERSION, state["model"].load_time_ms)
    except Exception as exc:  # the API still starts; /health reports the problem
        state["error"] = str(exc)
        log.exception("model loading failed")
    yield


app = FastAPI(title="BloodMNIST inference API", version=config.API_VERSION, lifespan=lifespan)


# ---------- Schemas (Pydantic validation -> automatic 422 on bad input) ----------
class PredictRequest(BaseModel):
    file_name: str = Field(..., min_length=1, max_length=256, examples=["basophil_0.png"])
    image_base64: str = Field(..., min_length=8, description="PNG or JPEG file, base64-encoded")

    @field_validator("image_base64")
    @classmethod
    def decode_and_check_size(cls, v: str) -> str:
        try:
            raw = base64.b64decode(v, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("image_base64 is not valid base64") from exc
        if len(raw) > config.MAX_IMAGE_BYTES:
            raise ValueError(f"image larger than {config.MAX_IMAGE_BYTES} bytes")
        return v


class PredictResponse(BaseModel):
    file_name: str
    class_id: int
    cell_type: str
    confidence: float
    probabilities: dict[str, float]
    model_version: str
    inference_ms: float


# ---------- Endpoints ----------
@app.get("/health")
def health():
    model = state["model"]
    if model is None:
        raise HTTPException(status_code=503, detail={"status": "unhealthy", "error": state["error"]})
    return {"status": "ok", "model_loaded": True, "model_load_time_ms": model.load_time_ms}


@app.get("/version")
def version():
    return {"api_version": config.API_VERSION, "model_version": config.MODEL_VERSION, "git_sha": config.GIT_SHA}


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    model = state["model"]
    if model is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    t0 = time.perf_counter()
    try:
        result = model.predict(base64.b64decode(req.image_base64))
    except InvalidImageError as exc:
        stats.add((time.perf_counter() - t0) * 1000, ok=False)
        telemetry.record_error("invalid_image")
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    stats.add((time.perf_counter() - t0) * 1000, ok=True)
    telemetry.record_success(result["cell_type"], result["inference_ms"])
    return PredictResponse(file_name=req.file_name, model_version=config.MODEL_VERSION, **result)


@app.get("/metrics")
def get_metrics():
    with stats.lock:
        avg = stats.total_ms / stats.calls if stats.calls else 0.0
        return {
            "predict_calls": stats.calls,
            "successes": stats.success,
            "errors": stats.errors,
            "average_latency_ms": round(avg, 2),
            "uptime_s": round(time.time() - stats.started, 1),
        }
