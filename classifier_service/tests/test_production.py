"""API deployment guards, with no Explorer calls or frozen-data writes."""
import io
import threading
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi.testclient import TestClient
import app as api
from v2_service import AnalysisError
from wallet_intelligence.clients import ExplorerClient, ClientUnavailable

ADDRESS = "ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqg239ffgrtl3mf4m6s02eweangtpe0gy9cph6u05"


class ProductionTests(unittest.TestCase):
    def test_live_capacity_rejects_excess_and_does_not_block_health_or_frozen(self):
        started, release = threading.Event(), threading.Event()

        def analyze(address, *, live):
            if live:
                started.set()
                if not release.wait(5):
                    raise RuntimeError("test worker did not release")
            return {"mode": "live" if live else "frozen"}

        with patch.object(api, "live_slots", threading.BoundedSemaphore(1)), \
             patch.object(api.service, "analyze", side_effect=analyze), \
             TestClient(api.app) as client, ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(client.post, "/analyze", json={"address": ADDRESS, "mode": "live"})
            try:
                self.assertTrue(started.wait(3))
                busy = client.post("/analyze", json={"address": ADDRESS, "mode": "live"})
                self.assertEqual(busy.status_code, 503)
                self.assertEqual(busy.json()["detail"]["status"], "ANALYSIS_BUSY")
                self.assertEqual(busy.headers["retry-after"], "5")
                self.assertEqual(client.get("/health").status_code, 200)
                self.assertEqual(client.post("/analyze", json={"address": ADDRESS}).status_code, 200)
            finally:
                release.set()
            self.assertEqual(future.result(timeout=3).status_code, 200)
            self.assertEqual(client.post("/analyze", json={"address": ADDRESS, "mode": "live"}).status_code, 200)

    def test_slots_released_on_expected_and_unexpected_errors(self):
        with patch.object(api, "live_slots", threading.BoundedSemaphore(1)), \
             patch.object(api.service, "analyze", side_effect=[AnalysisError("COLLECTION_FAILED", "offline"), RuntimeError("private traceback"), {}]), \
             TestClient(api.app, raise_server_exceptions=False) as client:
            responses = [client.post("/analyze", json={"address": ADDRESS, "mode": "live"}) for _ in range(3)]
            self.assertEqual([r.status_code for r in responses], [422, 500, 200])
            self.assertNotIn("private traceback", responses[1].text)

    def test_docs_validation_and_no_classifier_cors(self):
        with TestClient(api.app) as client:
            docs = client.get("/docs-overview").json()
            self.assertIn("rolling 30-day", docs["modes"]["live"])
            self.assertNotIn("NOT_YET_SUPPORTED", docs["modes"]["live"])
            self.assertEqual(client.post("/analyze", json={"address": "ckb1invalid"}).status_code, 400)
            self.assertEqual(client.post("/analyze", json={"address": ADDRESS, "mode": "other"}).status_code, 422)
            self.assertNotIn("access-control-allow-origin", client.get("/health", headers={"Origin": "https://demo.afriai.xyz"}).headers)

    def test_retry_after_is_bounded_and_network_timeout_is_used(self):
        for retry_after in ["999999", "-3", "not-a-number"]:
            error = urllib.error.HTTPError("https://example.invalid", 429, "limited", {"Retry-After": retry_after}, io.BytesIO())
            with patch("urllib.request.urlopen", side_effect=error) as request, \
                 patch("wallet_intelligence.clients.time.sleep") as sleep:
                with self.assertRaises(ClientUnavailable):
                    ExplorerClient(timeout=2, max_retries=1, request_delay_ms=0).get_address(ADDRESS)
                self.assertEqual(request.call_count, 2)
                self.assertEqual(request.call_args.kwargs["timeout"], 2)
                self.assertEqual(sleep.call_count, 1)
                self.assertGreaterEqual(sleep.call_args.args[0], 0)
                self.assertLessEqual(sleep.call_args.args[0], 8.25)
            error.close()
