"""One Flex Consumption Function App, three functions (Python v2 model):
- dispatcher : Event Grid trigger (BlobCreated on input/) -> validate -> queue or rejected/
- worker     : queue trigger (inference-requests) -> API /predict -> output/ + Cosmos DB
- recent     : HTTP GET /api/recent -> last 20 inferences (for the dashboard)
No secret in code: everything comes from application settings; Azure access uses the
Function App's managed identity (DefaultAzureCredential)."""
import base64
import json
import logging
import os
import time

import azure.functions as func
import httpx
from azure.core.exceptions import ResourceNotFoundError
from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

import pipeline as p

app = func.FunctionApp()
log = logging.getLogger("pipeline")

# ---------- Settings (application settings on Azure, local.settings.json locally) ----------
STORAGE_ACCOUNT_URL = os.getenv("STORAGE_ACCOUNT_URL", "")      # https://<account>.blob.core.windows.net
API_URL = os.getenv("API_URL", "").rstrip("/")                  # https://api-<team>....azurecontainerapps.io
API_TIMEOUT_S = float(os.getenv("API_TIMEOUT_S", "15"))
COSMOS_ENDPOINT = os.getenv("COSMOS_ENDPOINT", "")
COSMOS_DB = os.getenv("COSMOS_DB", "pipeline")
COSMOS_CONTAINER = os.getenv("COSMOS_CONTAINER", "inferences")
QUEUE_CONNECTION = "PIPELINE_STORAGE"  # identity-based: PIPELINE_STORAGE__queueServiceUri

# ---------- Telemetry: custom metrics sent to Application Insights ----------
_meter = None
if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from opentelemetry import metrics

        configure_azure_monitor()
        _meter = metrics.get_meter("pipeline")
    except Exception:  # telemetry must never break the pipeline
        log.exception("telemetry setup failed")

if _meter:
    M_PROCESSED = _meter.create_counter("pipeline_inferences_total", description="Files processed by the worker")
    M_DURATION = _meter.create_histogram("pipeline_duration_ms", unit="ms", description="Worker end-to-end time")
    M_REJECTED = _meter.create_counter("pipeline_rejected_total", description="Files rejected by the dispatcher")
    M_ERRORS = _meter.create_counter("pipeline_errors_total", description="Worker failures (will be retried)")


def _metric(name, value=1, **attrs):
    if _meter:
        {"processed": M_PROCESSED.add, "duration": M_DURATION.record,
         "rejected": M_REJECTED.add, "errors": M_ERRORS.add}[name](value, attrs)


# ---------- Clients created once per instance and reused ----------
_clients = {}


def blob_service() -> BlobServiceClient:
    if "blob" not in _clients:
        _clients["blob"] = BlobServiceClient(STORAGE_ACCOUNT_URL, credential=DefaultAzureCredential())
    return _clients["blob"]


def cosmos_container():
    if "cosmos" not in _clients:
        client = CosmosClient(COSMOS_ENDPOINT, credential=DefaultAzureCredential())
        _clients["cosmos"] = client.get_database_client(COSMOS_DB).get_container_client(COSMOS_CONTAINER)
    return _clients["cosmos"]


def http_client() -> httpx.Client:
    if "http" not in _clients:  # reused HTTP client (connection pooling) with timeout
        _clients["http"] = httpx.Client(timeout=httpx.Timeout(API_TIMEOUT_S, connect=10.0))
    return _clients["http"]


# =====================================================================================
# 1) DISPATCHER – Event Grid trigger
# =====================================================================================
@app.function_name(name="dispatcher")
@app.event_grid_trigger(arg_name="event")
@app.queue_output(arg_name="msg", queue_name="inference-requests", connection=QUEUE_CONNECTION)
def dispatcher(event: func.EventGridEvent, msg: func.Out[str]) -> None:
    data = event.get_json()
    url = data.get("url", "")
    size = int(data.get("contentLength") or 0)
    etag = data.get("eTag") or ""
    blob_name = p.blob_name_from_url(url, "input")
    log.info("dispatcher: event %s for %s (%s bytes)", event.event_type, blob_name, size)

    reason = p.check_metadata(blob_name, size)
    content = None
    if reason is None:
        content = blob_service().get_blob_client("input", blob_name).download_blob().readall()
        reason = p.check_content(content)

    if reason:
        _reject(blob_name, reason, content)
        return

    message = p.make_queue_message(blob_name, etag, size, event.event_time.isoformat() if event.event_time else None)
    msg.set(json.dumps(message))
    log.info("dispatcher: queued %s", message)


def _reject(blob_name: str, reason: str, content: bytes | None) -> None:
    """Copy the file to rejected/ (same name) + a .reason.json file explaining why."""
    svc = blob_service()
    if content is None:
        try:
            content = svc.get_blob_client("input", blob_name).download_blob().readall()
        except ResourceNotFoundError:
            content = b""
    svc.get_blob_client("rejected", blob_name).upload_blob(content, overwrite=True, metadata={"reason": reason[:200]})
    svc.get_blob_client("rejected", blob_name + ".reason.json").upload_blob(
        json.dumps({"file": blob_name, "reason": reason, "rejected_at": p.now_iso()}),
        overwrite=True, content_settings=ContentSettings(content_type="application/json"))
    _metric("rejected", reason=reason.split(":")[0][:40])
    log.warning("dispatcher: REJECTED %s -> %s", blob_name, reason)


# =====================================================================================
# 2) WORKER – queue trigger (5 attempts, then inference-requests-poison: see host.json)
# =====================================================================================
@app.function_name(name="worker")
@app.queue_trigger(arg_name="qmsg", queue_name="inference-requests", connection=QUEUE_CONNECTION)
def worker(qmsg: func.QueueMessage) -> None:
    t0 = time.perf_counter()
    try:
        msg = json.loads(qmsg.get_body().decode("utf-8"))
        p.validate_queue_message(msg)
    except (ValueError, json.JSONDecodeError):
        _metric("errors", reason="bad_message")
        log.error("worker: invalid message (attempt %s): %r", getattr(qmsg, "dequeue_count", "?"), qmsg.get_body()[:200])
        raise  # -> retried, then moved to inference-requests-poison

    blob_name = msg["blob_name"]
    doc_id = p.inference_id(blob_name, msg["etag"])
    container = cosmos_container()

    # Idempotence: same blob + same ETag already processed -> do nothing
    try:
        container.read_item(item=doc_id, partition_key=blob_name)
        log.info("worker: %s already processed (id=%s), skipping", blob_name, doc_id)
        return
    except ResourceNotFoundError:
        pass

    try:
        content = blob_service().get_blob_client("input", blob_name).download_blob().readall()
        resp = http_client().post(f"{API_URL}/predict", json={
            "file_name": blob_name, "image_base64": base64.b64encode(content).decode()})
        resp.raise_for_status()
        prediction = resp.json()
    except Exception as exc:
        _metric("errors", reason=type(exc).__name__)
        log.error("worker: failed for %s (attempt %s/5): %s", blob_name, getattr(qmsg, "dequeue_count", "?"), exc)
        raise  # -> automatic retry

    duration_ms = (time.perf_counter() - t0) * 1000
    record = p.build_record(msg, prediction, duration_ms)

    blob_service().get_blob_client("output", p.output_blob_name(blob_name)).upload_blob(
        json.dumps({**record, "probabilities": prediction.get("probabilities", {})}, indent=2),
        overwrite=True, content_settings=ContentSettings(content_type="application/json"))
    container.upsert_item(record)  # upsert = idempotent write

    _metric("processed", prediction=record["prediction"], model_version=record["modelVersion"])
    _metric("duration", duration_ms, model_version=record["modelVersion"])
    log.info("worker: %s -> %s (%.2f) in %.0f ms", blob_name, record["prediction"], record["confidence"], duration_ms)


# =====================================================================================
# 3) RECENT – HTTP GET /api/recent (CORS restricted to the dashboard origin, see infra)
# =====================================================================================
@app.function_name(name="recent")
@app.route(route="recent", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def recent(req: func.HttpRequest) -> func.HttpResponse:
    try:
        limit = max(1, min(int(req.params.get("limit", "20")), 100))
    except ValueError:
        limit = 20
    items = list(cosmos_container().query_items(
        query=f"SELECT TOP {limit} c.id, c.fileName, c.timestamp, c.prediction, c.confidence, "
              "c.modelVersion, c.durationMs, c.modelLatencyMs FROM c ORDER BY c.timestamp DESC",
        enable_cross_partition_query=True))
    return func.HttpResponse(json.dumps(items), mimetype="application/json",
                             headers={"Cache-Control": "no-store"})
