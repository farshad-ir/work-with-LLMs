"""Tests for the MT5 ingest endpoint."""
import json
import pytest
from fastapi.testclient import TestClient

import app.main as main


@pytest.fixture
def client():
    return TestClient(main.app)


class TestMT5IngestEndpoint:
    """Tests for POST /api/mt5/ingest."""

    def _make_payload(self, **overrides):
        """Build a valid payload with optional overrides."""
        payload = {
            "request_id": "test_20261102_120000",
            "symbol": "EURUSD",
            "timeframe": "M15",
            "timestamp": "2026-11-02T12:00:00",
            "candle_count": 10,
            "candles": [
                {"time": f"2026-11-02T{i*15:02d}:00", "open": 1.08500 + i * 0.0001,
                 "high": 1.08520 + i * 0.0001, "low": 1.08480 + i * 0.0001,
                 "close": 1.08510 + i * 0.0001}
                for i in range(10)
            ],
        }
        payload.update(overrides)
        return payload

    def test_valid_request_returns_200(self, client):
        payload = self._make_payload()
        resp = client.post("/api/mt5/ingest", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["request_id"] == "test_20261102_120000"
        assert data["received_candles"] == 10

    def test_missing_required_field(self, client):
        payload = self._make_payload()
        del payload["symbol"]
        resp = client.post("/api/mt5/ingest", json=payload)
        assert resp.status_code == 400
        assert "symbol" in resp.json()["detail"].lower()

    def test_candle_count_mismatch(self, client):
        payload = self._make_payload(candle_count=5)
        resp = client.post("/api/mt5/ingest", json=payload)
        assert resp.status_code == 400
        assert "does not match" in resp.json()["detail"].lower()

    def test_wrong_candle_count_not_10(self, client):
        payload = self._make_payload(candle_count=5)
        payload["candles"] = payload["candles"][:5]
        resp = client.post("/api/mt5/ingest", json=payload)
        assert resp.status_code == 400
        assert "expected exactly 10" in resp.json()["detail"].lower()

    def test_invalid_json_body(self, client):
        resp = client.post("/api/mt5/ingest", content="not-json", headers={"Content-Type": "application/json"})
        assert resp.status_code == 400

    def test_missing_ohlc_field(self, client):
        payload = self._make_payload()
        payload["candles"][0].pop("open")
        resp = client.post("/api/mt5/ingest", json=payload)
        assert resp.status_code == 400
        assert "open" in resp.json()["detail"].lower()

    def test_non_numeric_price_field(self, client):
        payload = self._make_payload()
        payload["candles"][0]["open"] = "not-a-number"
        resp = client.post("/api/mt5/ingest", json=payload)
        assert resp.status_code == 400
        assert "numeric" in resp.json()["detail"].lower()

    def test_empty_candles_array(self, client):
        payload = self._make_payload(candle_count=0, candles=[])
        resp = client.post("/api/mt5/ingest", json=payload)
        assert resp.status_code == 400
        assert "expected exactly 10" in resp.json()["detail"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])