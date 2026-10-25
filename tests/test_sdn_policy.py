"""
Tests for ControllerPolicy using a FAKE controller (a tiny HTTP server).
This proves the server sends the right HTTP requests at the right moments
(reserve -> POST, release -> DELETE, expiry -> DELETE, controller down ->
reservation refused). It does NOT test the real Ryu controller.
Run from the project root:  python3 -m unittest discover -s tests -v
"""
import json
import os
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
from resource_manager import ResourceManager  # noqa: E402
from sdn_policy import ControllerPolicy       # noqa: E402


class FakeController:
    """Records every request it receives."""

    def __init__(self, fail_posts=False):
        self.requests = []          # list of (method, path, body)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(("POST", self.path, body))
                if fail_posts:
                    self._reply(503, {"status": "error", "message": "no switches"})
                else:
                    self._reply(200, {"status": "ok", "id": body["id"]})

            def do_DELETE(self):
                outer.requests.append(("DELETE", self.path, None))
                self._reply(200, {"status": "ok"})

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class TestControllerPolicy(unittest.TestCase):
    def setUp(self):
        self.fake = FakeController()
        self.policy = ControllerPolicy(self.fake.url, verbose=False)
        self.m = ResourceManager(10.0, policy=self.policy)

    def tearDown(self):
        self.fake.close()
        self.m.stop()

    def test_reserve_sends_post(self):
        r = self.m.reserve("10.0.0.1", "10.0.0.3", 4, 60)
        self.assertEqual(r["status"], "ACCEPTED")
        self.assertEqual(self.fake.requests, [("POST", "/policy", {
            "id": r["id"], "src": "10.0.0.1", "dst": "10.0.0.3", "bandwidth_mbps": 4.0})])
    def test_capacity_is_sent_when_configured(self):
        m = ResourceManager(10.0, policy=ControllerPolicy(self.fake.url, verbose=False,
                                                          capacity_mbps=10.0))
        r = m.reserve("10.0.0.1", "10.0.0.3", 4, 60)
        self.assertEqual(self.fake.requests[-1][2]["capacity_mbps"], 10.0)
        self.assertEqual(r["status"], "ACCEPTED")


    def test_release_sends_delete(self):
        rid = self.m.reserve("10.0.0.1", "10.0.0.3", 4, 60)["id"]
        self.m.release(rid)
        self.assertEqual(self.fake.requests[-1], ("DELETE", "/policy/%d" % rid, None))

    def test_expiry_sends_delete(self):
        rid = self.m.reserve("10.0.0.1", "10.0.0.3", 4, 0.2)["id"]
        time.sleep(0.4)
        self.m.expire_old()
        self.assertEqual(self.fake.requests[-1], ("DELETE", "/policy/%d" % rid, None))

    def test_rejected_request_sends_nothing(self):
        self.m.reserve("10.0.0.1", "10.0.0.3", 8, 60)
        n = len(self.fake.requests)
        r = self.m.reserve("10.0.0.2", "10.0.0.4", 5, 60)    # 8 + 5 > 10
        self.assertEqual(r["status"], "REJECTED")
        self.assertEqual(len(self.fake.requests), n)         # controller not contacted

    def test_controller_down_refuses_reservation(self):
        self.fake.close()                                    # nothing listens any more
        r = self.m.reserve("10.0.0.1", "10.0.0.3", 4, 60)
        self.assertEqual(r["status"], "REJECTED")
        self.assertEqual(r["reason"], "POLICY_FAILED")
        self.assertEqual(self.m.get_stats()["used_mbps"], 0.0)

    def test_controller_error_refuses_reservation(self):
        self.fake.close()
        bad = FakeController(fail_posts=True)
        self.addCleanup(bad.close)
        m = ResourceManager(10.0, policy=ControllerPolicy(bad.url, verbose=False))
        self.assertEqual(m.reserve("10.0.0.1", "10.0.0.3", 4, 60)["reason"], "POLICY_FAILED")

    def test_release_survives_controller_down(self):
        rid = self.m.reserve("10.0.0.1", "10.0.0.3", 4, 60)["id"]
        self.fake.close()
        self.assertEqual(self.m.release(rid)["status"], "OK")   # no crash
        self.assertEqual(self.m.get_stats()["used_mbps"], 0.0)


if __name__ == "__main__":
    unittest.main()
