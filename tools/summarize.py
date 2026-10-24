"""
tools/summarize.py
------------------
Prints accepted/rejected statistics, rejection reasons, latency and
utilization from the CSV files written by workload.py and the server.

  python3 tools/summarize.py --workload results/workload.csv \
                             --samples results/utilization.csv
"""
import argparse
import csv
import statistics
from collections import Counter


def read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workload", default="results/workload.csv")
    p.add_argument("--samples", default=None)
    a = p.parse_args()

    rows = read(a.workload)
    total = len(rows)
    acc = [r for r in rows if r["status"] == "ACCEPTED"]
    rej = [r for r in rows if r["status"] == "REJECTED"]
    other = total - len(acc) - len(rej)
    print("=== Requests ===")
    print("total requests : %d" % total)
    print("accepted       : %d (%.1f%%)" % (len(acc), 100.0 * len(acc) / total))
    print("rejected       : %d (%.1f%%)" % (len(rej), 100.0 * len(rej) / total))
    if other:
        print("errors/other   : %d" % other)
    for reason, n in Counter(r["reason"] for r in rej).most_common():
        print("   rejected because %-22s %d" % (reason, n))
    if acc:
        print("accepted bandwidth requested: %.1f Mbps in total"
              % sum(float(r["bandwidth_mbps"]) for r in acc))
    lat = sorted(float(r["latency_ms"]) for r in rows)
    print("=== Response time (ms) ===")
    print("mean %.1f   median %.1f   max %.1f"
          % (statistics.mean(lat), statistics.median(lat), lat[-1]))

    if a.samples:
        s = read(a.samples)
        util = [float(r["utilization_pct"]) for r in s]
        if util:
            print("=== Link utilization (%d samples) ===" % len(util))
            print("average %.1f%%   peak %.1f%%" % (statistics.mean(util), max(util)))


if __name__ == "__main__":
    main()
