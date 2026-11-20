"""Azure Monitor OpenTelemetry: traces + 2 custom metrics (inference count, model latency) + errors."""
import logging

from opentelemetry import metrics

from . import config

log = logging.getLogger("api")


def setup_telemetry() -> None:
    if not config.APPINSIGHTS_CONNECTION_STRING:
        log.info("APPLICATIONINSIGHTS_CONNECTION_STRING not set: telemetry disabled (local mode)")
        return
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(connection_string=config.APPINSIGHTS_CONNECTION_STRING)
    log.info("Azure Monitor OpenTelemetry enabled")


# Instruments are created lazily so they bind to the provider configured above
_meter = None
_instruments = {}


def _get(name):
    global _meter
    if _meter is None:
        _meter = metrics.get_meter("bloodcell-api")
        _instruments["inferences"] = _meter.create_counter(
            "inferences_total", unit="1", description="Number of successful predictions")
        _instruments["latency"] = _meter.create_histogram(
            "model_latency_ms", unit="ms", description="ONNX model inference time")
        _instruments["errors"] = _meter.create_counter(
            "prediction_errors_total", unit="1", description="Rejected or failed predictions")
    return _instruments[name]


def record_success(cell_type: str, latency_ms: float) -> None:
    attrs = {"cell_type": cell_type, "model_version": config.MODEL_VERSION}
    _get("inferences").add(1, attrs)
    _get("latency").record(latency_ms, attrs)


def record_error(reason: str) -> None:
    _get("errors").add(1, {"reason": reason, "model_version": config.MODEL_VERSION})
