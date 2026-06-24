import io
import json
import logging
import unittest

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
        self.client = maven_app.app.test_client()

    def tearDown(self):
        maven_app.logger.handlers = self.original_handlers

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
        with maven_app.lock:
            maven_app.devices.clear()

        response = self.client.get("/health", headers={"X-Request-ID": "req-health-test"})
        body = response.get_json()

        self.assertEqual(response.status_code, 503)
        self.assertEqual(set(body), {"status", "services"})
        self.assertEqual(set(body["services"]), {"camera", "microphone", "ir"})
        for service in body["services"].values():
            self.assertEqual(set(service), {"status", "latency_ms", "error"})


if __name__ == "__main__":
    unittest.main()
