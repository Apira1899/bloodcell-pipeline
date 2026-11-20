import io

import pytest
from PIL import Image

import pipeline as p


def _png(size=(28, 28)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 50, 50)).save(buf, format="PNG")
    return buf.getvalue()


def test_blob_name_from_url():
    url = "https://stx.blob.core.windows.net/input/batch1/cell.png"
    assert p.blob_name_from_url(url) == "batch1/cell.png"
    with pytest.raises(ValueError):
        p.blob_name_from_url("https://stx.blob.core.windows.net/output/cell.png")


@pytest.mark.parametrize("name,size,ok", [
    ("cell.png", 500, True), ("cell.JPG", 500, True), ("cell.txt", 500, False),
    ("cell", 500, False), ("cell.png", 0, False), ("cell.png", 5_000_000, False)])
def test_check_metadata(name, size, ok):
    assert (p.check_metadata(name, size) is None) == ok


def test_check_content():
    assert p.check_content(_png()) is None
    assert p.check_content(b"not an image") is not None
    assert p.check_content(_png((4, 4))) is not None          # too small


def test_idempotency_key_is_stable():
    a = p.inference_id("x.png", '"0x8DC"')
    assert a == p.inference_id("x.png", "0x8DC")                # quotes ignored
    assert a != p.inference_id("x.png", "0x8DD")                # new version -> new id
    assert "/" not in p.inference_id("dir/x.png", "e")


def test_queue_message_roundtrip():
    m = p.make_queue_message("x.png", '"0x1"', 123, None)
    p.validate_queue_message(m)
    assert m["etag"] == "0x1"
    with pytest.raises(ValueError):
        p.validate_queue_message({"blob_name": "x.png"})


def test_build_record():
    m = p.make_queue_message("dir/x.png", "0x1", 10, None)
    r = p.build_record(m, {"cell_type": "platelet", "class_id": 7, "confidence": 0.9,
                           "model_version": "1.0.0", "inference_ms": 3.2}, 120.4)
    assert r["fileName"] == "dir/x.png" and r["prediction"] == "platelet"
    assert r["id"] == p.inference_id("dir/x.png", "0x1")
    assert p.output_blob_name("dir/x.png") == "dir/x.json"
