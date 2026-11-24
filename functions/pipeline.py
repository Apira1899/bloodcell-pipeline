"""Pure logic shared by the functions (no Azure calls) -> easy to unit test."""
import hashlib
import io
import os
import posixpath
from datetime import UTC, datetime

from PIL import Image, UnidentifiedImageError

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_BYTES", "1000000"))  # 1 MB, same as model/input_schema.json
MIN_SIDE, MAX_SIDE = 8, 4096


def blob_name_from_url(url: str, container: str = "input") -> str:
    """https://<acct>.blob.core.windows.net/input/sub/x.png -> 'sub/x.png'"""
    marker = f"/{container}/"
    if marker not in url:
        raise ValueError(f"URL is not in container '{container}': {url}")
    return url.split(marker, 1)[1]


def check_metadata(blob_name: str, size: int) -> str | None:
    """Cheap checks before downloading. Returns a rejection reason or None."""
    ext = posixpath.splitext(blob_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return f"extension '{ext or 'none'}' not allowed (expected {sorted(ALLOWED_EXTENSIONS)})"
    if size <= 0:
        return "empty file"
    if size > MAX_FILE_BYTES:
        return f"file too large: {size} bytes > {MAX_FILE_BYTES}"
    return None


def check_content(data: bytes) -> str | None:
    """'Schema' check for images: must be a readable PNG/JPEG with sane dimensions."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            w, h = img.size
    except (UnidentifiedImageError, OSError, SyntaxError):
        return "content is not a valid image"
    if fmt not in {"PNG", "JPEG"}:
        return f"image format {fmt} not allowed"
    if not (MIN_SIDE <= w <= MAX_SIDE and MIN_SIDE <= h <= MAX_SIDE):
        return f"image size {w}x{h} out of range"
    return None


def make_queue_message(blob_name: str, etag: str, size: int, event_time: str | None) -> dict:
    return {
        "blob_name": blob_name,
        "etag": etag.strip('"'),
        "size": size,
        "event_time": event_time or now_iso(),
    }


def validate_queue_message(msg: dict) -> None:
    for key, typ in (("blob_name", str), ("etag", str), ("size", int)):
        if not isinstance(msg.get(key), typ) or msg.get(key) in ("", None):
            raise ValueError(f"invalid queue message: field '{key}' missing or wrong type")


def inference_id(blob_name: str, etag: str) -> str:
    """Idempotency key: same file + same version -> same id (Cosmos ids cannot contain '/')."""
    return hashlib.sha256(f"{blob_name}|{etag.strip(chr(34))}".encode()).hexdigest()[:32]


def output_blob_name(blob_name: str) -> str:
    return posixpath.splitext(blob_name)[0] + ".json"


def build_record(msg: dict, prediction: dict, duration_ms: float) -> dict:
    ts = now_iso()
    return {
        "id": inference_id(msg["blob_name"], msg["etag"]),
        "fileName": msg["blob_name"],
        "etag": msg["etag"],
        "timestamp": ts,
        "day": ts[:10],
        "prediction": prediction["cell_type"],
        "classId": prediction["class_id"],
        "confidence": prediction["confidence"],
        "modelVersion": prediction["model_version"],
        "modelLatencyMs": prediction.get("inference_ms"),
        "durationMs": round(duration_ms, 1),
        "sizeBytes": msg["size"],
    }


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")