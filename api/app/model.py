"""Loads the ONNX model once and runs inference on CPU."""
import io
import json
import time

import numpy as np
import onnxruntime as ort
from PIL import Image, UnidentifiedImageError


class InvalidImageError(ValueError):
    """Raised when the bytes are not a readable image."""


class BloodCellModel:
    def __init__(self, model_path: str, labels_path: str, image_size: int = 28):
        t0 = time.perf_counter()
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1  # Container Apps: 0.25 vCPU
        self.session = ort.InferenceSession(model_path, opts, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        with open(labels_path, encoding="utf-8") as f:
            labels = json.load(f)
        self.labels = [labels[str(i)] for i in range(len(labels))]
        self.image_size = image_size
        self.load_time_ms = round((time.perf_counter() - t0) * 1000, 2)

    def preprocess(self, data: bytes) -> np.ndarray:
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except (UnidentifiedImageError, OSError) as exc:
            raise InvalidImageError("file is not a valid PNG/JPEG image") from exc
        img = img.convert("RGB").resize((self.image_size, self.image_size), Image.BILINEAR)
        arr = np.asarray(img, dtype=np.float32) / 255.0  # HWC in [0, 1]
        return arr.transpose(2, 0, 1)[None, ...]  # (1, 3, H, W)

    def predict(self, data: bytes) -> dict:
        x = self.preprocess(data)
        t0 = time.perf_counter()
        probs = self.session.run(None, {self.input_name: x})[0][0]
        inference_ms = (time.perf_counter() - t0) * 1000
        idx = int(np.argmax(probs))
        return {
            "class_id": idx,
            "cell_type": self.labels[idx],
            "confidence": round(float(probs[idx]), 4),
            "probabilities": {name: round(float(p), 4) for name, p in zip(self.labels, probs)},
            "inference_ms": round(inference_ms, 2),
        }
