"""
Unit tests for ResourceManager (no network needed).
Run from the project root:  python3 -m unittest discover -s tests -v
"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
from resource_manager import ResourceManager, NullPolicy  # noqa: E402


def make(capacity=10.0):
    return ResourceManager(capacity_mbps=capacity, policy=NullPolicy(verbose=False))


class FailingPolicy:
    def install(self, res):
        return False

    def remove(self, res):
        return True


class TestResourceManager(unittest.TestCase):
    def test_accept_within_capacity(self):
        m = make()
        r = m.reserve("10.0.0.1", "10.0.0.3", 4, 60)
        self.assertEqual(r["status"], "ACCEPTED")
        self.assertEqual(m.get_stats()["used_mbps"], 4.0)

    def test_reject_when_capacity_exceeded(self):
        m = make()
        self.assertEqual(m.reserve("10.0.0.1", "10.0.0.3", 6, 60)["status"], "ACCEPTED")
        r = m.reserve("10.0.0.2", "10.0.0.4", 5, 60)       # 6 + 5 > 10
        self.assertEqual(r["status"], "REJECTED")
        self.assertEqual(r["reason"], "INSUFFICIENT_BANDWIDTH")
        self.assertEqual(r["available_mbps"], 4.0)

    def test_exact_fit_is_accepted(self):
        m = make()
        m.reserve("10.0.0.1", "10.0.0.3", 6, 60)
        self.assertEqual(m.reserve("10.0.0.2", "10.0.0.4", 4, 60)["status"], "ACCEPTED")

    def test_duplicate_host_pair_rejected(self):
        m = make()
        m.reserve("10.0.0.1", "10.0.0.3", 2, 60)
        r = m.reserve("10.0.0.1", "10.0.0.3", 2, 60)
        self.assertEqual(r["reason"], "DUPLICATE_FLOW")

    def test_invalid_requests(self):
        m = make()
        for args in [("bad", "10.0.0.3", 1, 10), ("10.0.0.1", "10.0.0.1", 1, 10),
                     ("10.0.0.1", "10.0.0.3", -1, 10), ("10.0.0.1", "10.0.0.3", 99, 10),
                     ("10.0.0.1", "10.0.0.3", 1, 0), ("10.0.0.1", "10.0.0.3", "x", 10)]:
            self.assertEqual(m.reserve(*args)["reason"], "INVALID_REQUEST", args)

    def test_release_frees_bandwidth(self):
        m = make()
        rid = m.reserve("10.0.0.1", "10.0.0.3", 8, 60)["id"]
        self.assertEqual(m.release(rid)["status"], "OK")
        self.assertEqual(m.get_stats()["used_mbps"], 0.0)
        self.assertEqual(m.release(rid)["reason"], "NOT_FOUND")   # second release fails

    def test_status_and_list(self):
        m = make()
        rid = m.reserve("10.0.0.1", "10.0.0.3", 3, 60)["id"]
        self.assertEqual(m.status(rid)["bandwidth_mbps"], 3.0)
        self.assertEqual(len(m.list_active()["reservations"]), 1)
        self.assertEqual(m.status(999)["reason"], "NOT_FOUND")

    def test_expiry(self):
        m = make()
        m.reserve("10.0.0.1", "10.0.0.3", 5, 0.3)
        time.sleep(0.5)
        self.assertEqual(m.expire_old(), 1)
        s = m.get_stats()
        self.assertEqual(s["used_mbps"], 0.0)
        self.assertEqual(s["expired"], 1)

    def test_expiry_thread(self):
        m = make()
        m.start_expiry_thread(interval_s=0.1)
        m.reserve("10.0.0.1", "10.0.0.3", 5, 0.3)
        time.sleep(0.8)
        m.stop()
        self.assertEqual(m.get_stats()["active_reservations"], 0)

    def test_policy_failure_rolls_back(self):
        m = ResourceManager(10.0, policy=FailingPolicy())
        r = m.reserve("10.0.0.1", "10.0.0.3", 2, 60)
        self.assertEqual(r["reason"], "POLICY_FAILED")
        self.assertEqual(m.get_stats()["active_reservations"], 0)

    def test_concurrent_requests_never_overbook(self):
        """30 threads each ask for 1 Mbps on a 10 Mbps link: exactly 10 win."""
        m = make(10.0)
        results = []
        barrier = threading.Barrier(30)

        def worker(i):
            barrier.wait()                       # all threads start together
            results.append(m.reserve("10.0.0.%d" % (i + 1), "10.0.1.%d" % (i + 1), 1, 60))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        accepted = sum(1 for r in results if r["status"] == "ACCEPTED")
        self.assertEqual(accepted, 10)
        self.assertEqual(m.get_stats()["used_mbps"], 10.0)
        self.assertEqual(m.get_stats()["rejected"], 20)


if __name__ == "__main__":
    unittest.main()
