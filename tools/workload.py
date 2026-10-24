"""
tools/workload.py
-----------------
Fires many random reservation requests at the server, at the same time,
and records every answer in a CSV file (for Stage 5/6 evaluation).

Example:
  python3 tools/workload.py --server 10.0.0.100 --requests 40 --interval 0.3 \
         --out results/workload.csv
Use --seed to repeat exactly the same random workload.
"""
import argparse
import csv
import os
import random
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))
from client import send_request  # noqa: E402

HOSTS = ["10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--requests", type=int, default=40)
    p.add_argument("--interval", type=float, default=0.3,
                   help="mean seconds between request arrivals (0 = all at once)")
    p.add_argument("--min-bw", type=float, default=1.0)
    p.add_argument("--max-bw", type=float, default=5.0)
    p.add_argument("--min-dur", type=float, default=3.0)
    p.add_argument("--max-dur", type=float, default=8.0)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", default="results/workload.csv")
    a = p.parse_args()

    rng = random.Random(a.seed)
    rows, lock, threads = [], threading.Lock(), []
    t0 = time.time()

    def one(i, src, dst, bw, dur):
        req = {"cmd": "RESERVE", "src": src, "dst": dst,
               "bandwidth_mbps": bw, "duration_s": dur}
        start = time.time()
        try:
            resp = send_request(a.server, a.port, req)
        except (OSError, ValueError) as e:
            resp = {"status": "ERROR", "reason": "CLIENT_ERROR: %s" % e}
        latency_ms = (time.time() - start) * 1000
        with lock:
            rows.append([i, "%.2f" % (start - t0), src, dst, bw, dur,
                         resp.get("status"), resp.get("reason", ""),
                         resp.get("id", ""), "%.2f" % latency_ms])

    for i in range(a.requests):
        src, dst = rng.sample(HOSTS, 2)
        bw = round(rng.uniform(a.min_bw, a.max_bw), 1)
        dur = round(rng.uniform(a.min_dur, a.max_dur), 1)
        t = threading.Thread(target=one, args=(i + 1, src, dst, bw, dur))
        t.start()
        threads.append(t)
        if a.interval > 0:
            time.sleep(rng.expovariate(1.0 / a.interval))
    for t in threads:
        t.join()

    rows.sort()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["req_no", "sent_at_s", "src", "dst", "bandwidth_mbps",
                    "duration_s", "status", "reason", "id", "latency_ms"])
        w.writerows(rows)
    print("sent %d requests, results in %s" % (len(rows), a.out))


if __name__ == "__main__":
    main()
