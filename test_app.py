import io
import json
import logging
import os
import time
import unittest
from unittest.mock import patch

os.environ["MAVEN_SCANNER_AUTOSTART"] = "0"

import app as maven_app


def boom_for_test():
    raise RuntimeError("simulated failure")


class ProductionReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if "boom_for_test" not in maven_app.app.view_functions:
            maven_app.app.add_url_rule(
                "/__boom_for_test",
                "boom_for_test",
                boom_for_test,
            )

    def setUp(self):
        self.log_stream = io.StringIO()
        self.log_handler = logging.StreamHandler(self.log_stream)
        self.log_handler.setFormatter(logging.Formatter("%(message)s"))
        self.original_handlers = list(maven_app.logger.handlers)
        maven_app.logger.handlers = [self.log_handler]
        maven_app.logger.setLevel(logging.INFO)
        maven_app.last_service_health.clear()
        maven_app.clear_paired_session()
        with maven_app.lock:
            maven_app.devices.clear()
            maven_app.scanner_state["last_scan_at"] = time.time()
            maven_app.scanner_state["last_success_at"] = time.time()
            maven_app.scanner_state["last_error"] = None
        self.scanner_running_patch = patch.object(
            maven_app, "scanner_is_running", return_value=True
        )
        self.scanner_running_patch.start()
        self.client = maven_app.app.test_client()

    def tearDown(self):
        self.scanner_running_patch.stop()
        maven_app.logger.handlers = self.original_handlers
        maven_app.clear_paired_session()

    def log_events(self):
        return [
            json.loads(line)
            for line in self.log_stream.getvalue().splitlines()
            if line.strip()
        ]

    def test_unhandled_exception_is_structured_and_correlated(self):
        original_testing = maven_app.app.testing
        original_propagate = maven_app.app.config.get("PROPAGATE_EXCEPTIONS")
        maven_app.app.testing = False
        maven_app.app.config["PROPAGATE_EXCEPTIONS"] = False
        try:
            response = self.client.get(
                "/__boom_for_test",
                headers={"X-Request-ID": "req-production-test"},
            )
        finally:
            maven_app.app.testing = original_testing
            maven_app.app.config["PROPAGATE_EXCEPTIONS"] = original_propagate

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers["X-Request-ID"], "req-production-test")
        self.assertEqual(response.get_json(), {"error": "internal server error"})

        events = self.log_events()
        exception_event = next(
            event for event in events if event["event"] == "request_exception"
        )
        request_event = next(
            event for event in events if event["event"] == "request_complete"
        )

        self.assertEqual(exception_event["request_id"], "req-production-test")
        self.assertEqual(exception_event["endpoint"], "boom_for_test")
        self.assertEqual(exception_event["exception_type"], "RuntimeError")
        self.assertEqual(request_event["request_id"], "req-production-test")
        self.assertEqual(request_event["status_code"], 500)

    def test_health_schema_stays_stable_without_discovered_device(self):
        response = self.client.get("/health", headers={"X-Request-ID": "req-health-test"})
        body = response.get_json()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(set(body), {"status", "services", "scanner"})
        self.assertEqual(set(body["services"]), {"camera", "microphone", "ir"})
        self.assertEqual(
            set(body["scanner"]),
            {"status", "running", "last_scan_at", "last_success_at", "error"},
        )
        for service in body["services"].values():
            self.assertEqual(set(service), {"status", "latency_ms", "error"})

    def test_health_marks_unhealthy_when_scanner_not_running(self):
        self.scanner_running_patch.stop()
        response = self.client.get("/health")
        body = response.get_json()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(body["status"], "unhealthy")
        self.assertFalse(body["scanner"]["running"])
        self.assertEqual(body["scanner"]["error"], "scanner not running")

    def test_start_scanner_is_idempotent(self):
        maven_app.scanner_started = False
        with patch.object(maven_app.threading, "Thread") as mock_thread:
            mock_thread.return_value.start = lambda: None
            self.assertTrue(maven_app.start_scanner())
            self.assertFalse(maven_app.start_scanner())
            self.assertTrue(maven_app.scanner_is_running())
            mock_thread.assert_called_once()

    def test_health_prefers_paired_session_ip(self):
        maven_app.set_paired_session("secret-token", "192.168.1.50", "Living room")
        with patch.object(maven_app, "check_http_service") as mock_check:
            mock_check.return_value = {
                "name": "camera",
                "status": "healthy",
                "latency_ms": 1.0,
                "error": None,
            }
            response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        for call in mock_check.call_args_list:
            self.assertTrue(call.args[1].startswith("http://192.168.1.50:"))

    def test_api_paired_returns_authoritative_ip(self):
        maven_app.set_paired_session("secret-token", "192.168.1.50", "Living room")
        response = self.client.get(
            "/api/paired",
            headers={"X-Maven-Token": "secret-token"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["ip"], "192.168.1.50")
        self.assertEqual(body["name"], "Living room")

    def test_api_paired_restores_session_from_discovered_devices(self):
        with maven_app.lock:
            maven_app.devices["192.168.1.77"] = {
                "ip": "192.168.1.77",
                "name": "Bedroom",
                "pairing": False,
                "seen": 1.0,
            }

        with patch.object(maven_app, "verify_device_token", side_effect=lambda token, ip: ip == "192.168.1.77"):
            response = self.client.get(
                "/api/paired?ip=192.168.1.1",
                headers={"X-Maven-Token": "restored-token"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["ip"], "192.168.1.77")
        session = maven_app.get_paired_session()
        self.assertEqual(session["token"], "restored-token")
        self.assertEqual(session["ip"], "192.168.1.77")

    def test_rebind_updates_paired_ip_when_token_moves(self):
        maven_app.set_paired_session("secret-token", "192.168.1.10", "MAVEN")

        def verify_side_effect(token, ip):
            return ip == "192.168.1.99"

        with patch.object(maven_app, "verify_device_token", side_effect=verify_side_effect):
            maven_app.rebind_paired_ip_if_needed([("192.168.1.99", {"ok": True})])

        session = maven_app.get_paired_session()
        self.assertEqual(session["ip"], "192.168.1.99")
        rebound_events = [
            event for event in self.log_events() if event["event"] == "paired_ip_rebound"
        ]
        self.assertEqual(len(rebound_events), 1)
        self.assertEqual(rebound_events[0]["old_ip"], "192.168.1.10")
        self.assertEqual(rebound_events[0]["new_ip"], "192.168.1.99")

    def test_proxy_send_uses_paired_ip_not_client_query(self):
        maven_app.set_paired_session("secret-token", "192.168.1.50", "MAVEN")

        with patch.object(maven_app.req, "post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.text = '{"ok": true}'
            response = self.client.post(
                "/proxy/send/power_toggle?ip=192.168.1.99",
                headers={"X-Maven-Token": "secret-token"},
            )

        self.assertEqual(response.status_code, 200)
        mock_post.assert_called_once()
        self.assertIn("192.168.1.50", mock_post.call_args.args[0])
        self.assertNotIn("192.168.1.99", mock_post.call_args.args[0])

    def test_proxy_send_requires_paired_session(self):
        response = self.client.post(
            "/proxy/send/power_toggle?ip=192.168.1.50",
            headers={"X-Maven-Token": "secret-token"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.get_json()["ok"])

    def test_disconnect_clears_paired_session(self):
        maven_app.set_paired_session("secret-token", "192.168.1.50", "MAVEN")
        response = self.client.post(
            "/api/disconnect",
            headers={"X-Maven-Token": "secret-token"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(maven_app.get_paired_session())


if __name__ == "__main__":
    unittest.main()
