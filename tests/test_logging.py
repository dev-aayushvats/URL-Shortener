import json
import logging

from app.logging_config import JsonFormatter


def test_request_id_generated_and_returned(client):
    r = client.get("/health")
    assert len(r.headers["x-request-id"]) == 32


def test_safe_client_request_id_is_echoed(client):
    r = client.get("/health", headers={"X-Request-ID": "trace-123"})
    assert r.headers["x-request-id"] == "trace-123"


def test_unsafe_request_id_is_replaced(client):
    r = client.get("/health", headers={"X-Request-ID": "bad id\twith spaces"})
    assert r.headers["x-request-id"] != "bad id\twith spaces"
    assert len(r.headers["x-request-id"]) == 32


def test_access_log_is_structured(client, caplog):
    with caplog.at_level(logging.INFO, logger="app.access"):
        r = client.get("/nonexistent-code")
    record = next(rec for rec in caplog.records if rec.name == "app.access")
    assert (record.method, record.path, record.status) == ("GET", "/nonexistent-code", 404)
    assert record.duration_ms >= 0
    assert r.status_code == 404


def test_json_formatter_output():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "hello %s", ("w",), None)
    record.status = 200
    out = json.loads(JsonFormatter().format(record))
    assert out["message"] == "hello w"
    assert out["level"] == "INFO"
    assert out["status"] == 200
    assert "ts" in out
