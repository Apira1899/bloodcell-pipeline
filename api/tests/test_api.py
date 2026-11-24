import base64

from conftest import LABELS


def test_predict_success(client, png_b64):
    r = client.post("/predict", json={"file_name": "cell.png", "image_base64": png_b64})
    assert r.status_code == 200
    body = r.json()
    assert body["cell_type"] in LABELS
    assert 0.0 <= body["confidence"] <= 1.0
    assert abs(sum(body["probabilities"].values()) - 1.0) < 1e-2
    assert body["model_version"] == "1.0.0-test"
    assert body["file_name"] == "cell.png"


def test_predict_invalid_base64_returns_422(client):
    r = client.post("/predict", json={"file_name": "x.png", "image_base64": "%%%not-base64%%%"})
    assert r.status_code == 422


def test_predict_not_an_image_returns_422(client):
    fake = base64.b64encode(b"this is a text file, not a png").decode()
    r = client.post("/predict", json={"file_name": "x.png", "image_base64": fake})
    assert r.status_code == 422


def test_predict_wrong_type_returns_422(client):
    r = client.post("/predict", json={"file_name": "x.png", "image_base64": 12345})
    assert r.status_code == 422


def test_predict_missing_body_returns_422(client):
    r = client.post("/predict")
    assert r.status_code == 422


def test_predict_missing_field_returns_422(client):
    r = client.post("/predict", json={"file_name": "x.png"})
    assert r.status_code == 422


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "model_load_time_ms" in r.json()


def test_version(client):
    body = client.get("/version").json()
    assert body["api_version"] == "1.0.0" and body["model_version"] == "1.0.0-test"
    assert "git_sha" in body


def test_metrics_counts_calls(client, png_b64):
    before = client.get("/metrics").json()["predict_calls"]
    client.post("/predict", json={"file_name": "a.png", "image_base64": png_b64})
    after = client.get("/metrics").json()
    assert after["predict_calls"] == before + 1
    assert after["average_latency_ms"] >= 0
