"""Tests use a tiny dummy ONNX model with the same input/output contract as the real one,
so CI does not depend on the 45 MB trained model."""
import base64
import io
import json
import os
import tempfile

import numpy as np
import onnx
import pytest
from onnx import TensorProto, helper, numpy_helper
from PIL import Image

N_CLASSES = 8
LABELS = ["basophil", "eosinophil", "erythroblast", "ig", "lymphocyte", "monocyte", "neutrophil", "platelet"]


def _build_dummy_model(path: str) -> None:
    # image (N,3,28,28) -> Flatten -> MatMul W (2352x8) -> Softmax -> probabilities (N,8)
    rng = np.random.default_rng(0)
    w = numpy_helper.from_array(rng.normal(size=(3 * 28 * 28, N_CLASSES)).astype(np.float32), "W")
    nodes = [
        helper.make_node("Flatten", ["image"], ["flat"], axis=1),
        helper.make_node("MatMul", ["flat", "W"], ["logits"]),
        helper.make_node("Softmax", ["logits"], ["probabilities"], axis=1),
    ]
    graph = helper.make_graph(
        nodes, "dummy",
        [helper.make_tensor_value_info("image", TensorProto.FLOAT, ["batch", 3, 28, 28])],
        [helper.make_tensor_value_info("probabilities", TensorProto.FLOAT, ["batch", N_CLASSES])],
        initializer=[w],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.save(model, path)


_tmp = tempfile.mkdtemp()
_model_path = os.path.join(_tmp, "model-test.onnx")
_labels_path = os.path.join(_tmp, "labels.json")
_build_dummy_model(_model_path)
with open(_labels_path, "w") as f:
    json.dump({str(i): n for i, n in enumerate(LABELS)}, f)

# Must be set before the app (and its config) is imported
os.environ.update({"MODEL_PATH": _model_path, "LABELS_PATH": _labels_path,
                   "MODEL_VERSION": "1.0.0-test", "API_VERSION": "1.0.0"})
os.environ.pop("APPLICATIONINSIGHTS_CONNECTION_STRING", None)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:  # "with" runs the lifespan -> model is loaded
        yield c


@pytest.fixture
def png_b64():
    img = Image.fromarray(np.random.default_rng(1).integers(0, 255, (28, 28, 3), dtype=np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()
