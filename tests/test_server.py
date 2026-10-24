"""
Integration tests: a real TCP server on localhost and real TCP clients.
Run from the project root:  python3 -m unittest discover -s tests -v
"""
import os
import socket
import sys
import threading
import time
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "server"))
sys.path.insert(0, os.path.join(HERE, "..", "client"))
from resource_manager import ResourceManager, NullPolicy  # noqa: E402
from server import ReservationServer                      # noqa: E402
from client import send_request                           # noqa: E402


class TestServer(unittest.TestCase):
    def setUp(self):
        self.manager = ResourceManager(10.0, policy=NullPolicy(verbose=False))
        self.manager.start_expiry_thread(interval_s=0.1)
        self.server = ReservationServer(self.manager, "127.0.0.1", 0)  # port 0 = any free port
        self.port = self.server.start()

    def tearDown(self):
        self.server.stop()
        self.manager.stop()

    def ask(self, req):
        return send_request("127.0.0.1", self.port, req)

    def test_reserve_status_release_over_tcp(self):
        r = self.ask({"cmd": "RESERVE", "src": "10.0.0.1", "dst": "10.0.0.3",
                      "bandwidth_mbps": 4, "duration_s": 60})
        self.assertEqual(r["status"], "ACCEPTED")
        self.assertEqual(self.ask({"cmd": "STATUS", "id": r["id"]})["status"], "OK")
        self.assertEqual(self.ask({"cmd": "RELEASE", "id": r["id"]})["status"], "OK")
        self.assertEqual(self.ask({"cmd": "STATUS", "id": r["id"]})["status"], "ERROR")

    def test_bad_input_does_not_crash_server(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=3) as s:
            f = s.makefile("r", encoding="utf-8")
            s.sendall(b"this is not json\n")
            self.assertIn("invalid JSON", f.readline())
            s.sendall(b'{"cmd": "FLY"}\n')
            self.assertIn("unknown command", f.readline())
            s.sendall(b'{"cmd": "STATS"}\n')              # same connection still works
            self.assertIn("capacity_mbps", f.readline())
        self.assertEqual(self.ask({"cmd": "STATS"})["status"], "OK")   # server still alive

    def test_many_concurrent_clients(self):
        """20 clients at once, 1 Mbps each, 10 Mbps link -> 10 accepted, 10 rejected."""
        results = []
        barrier = threading.Barrier(20)

        def client(i):
            barrier.wait()
            results.append(self.ask({"cmd": "RESERVE", "src": "10.0.0.%d" % (i + 1),
                                     "dst": "10.0.1.%d" % (i + 1),
                                     "bandwidth_mbps": 1, "duration_s": 60}))

        threads = [threading.Thread(target=client, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(r["status"] == "ACCEPTED" for r in results), 10)
        stats = self.ask({"cmd": "STATS"})
        self.assertEqual(stats["accepted"], 10)
        self.assertEqual(stats["rejected"], 10)
        self.assertEqual(stats["utilization_pct"], 100.0)

    def test_expiry_through_server(self):
        self.ask({"cmd": "RESERVE", "src": "10.0.0.1", "dst": "10.0.0.3",
                  "bandwidth_mbps": 5, "duration_s": 0.3})
        self.assertEqual(self.ask({"cmd": "STATS"})["used_mbps"], 5.0)
        time.sleep(0.8)
        s = self.ask({"cmd": "STATS"})
        self.assertEqual(s["used_mbps"], 0.0)
        self.assertEqual(s["expired"], 1)


if __name__ == "__main__":
    unittest.main()
