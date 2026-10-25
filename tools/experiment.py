#!/usr/bin/env python3
"""
tools/experiment.py
-------------------
Runs the whole Stage 6 evaluation in ONE command (needs sudo, system python):

    sudo python3 tools/experiment.py

Before starting it you need the controller and the reservation server running
(the controller on 127.0.0.1:8080 and the server on 127.0.0.1:5000).
This script builds the Mininet network itself - do NOT start topo.py as well.

PART 1  Baseline vs reservation
        A "reserved" UDP stream (h1 -> h3) competes with a greedy UDP stream
        (h2 -> h4) over the 10 Mbps bottleneck.  Run once WITHOUT a reservation
        (baseline) and once WITH a 4 Mbps reservation, several times each.
PART 2  Accepted/rejected requests under light / medium / heavy load
PART 3  Challenge scenario: 25 clients ask at the same instant (overbooking test),
        then everything must expire and every rule must disappear.

Everything is written to the results/ folder as CSV files.
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "client"))
sys.path.insert(0, os.path.join(ROOT, "server"))
sys.path.insert(0, os.path.join(ROOT, "topology"))
from client import send_request  # noqa: E402

RESULTS = os.path.join(ROOT, "results")
RAW = os.path.join(RESULTS, "raw")

# ----------------------------------------------------------------------
# reading iperf output
# ----------------------------------------------------------------------
LINE = re.compile(r"(\d+\.\d+)\s*-\s*(\d+\.\d+)\s+sec")
BW = re.compile(r"([\d.]+)\s+Mbits/sec")
LOSS = re.compile(r"(\d+)\s*/\s*(\d+)\s*\(([\d.]+)%\)")


def parse_iperf(text):
    """Return (per_second, summary).
    per_second = [(second_number, Mbps), ...]   summary = {"mbps":, "loss_pct":} or None"""
    per_sec, summary = [], None
    for line in text.splitlines():
        m, b = LINE.search(line), BW.search(line)
        if not (m and b):
            continue
        start, end = float(m.group(1)), float(m.group(2))
        mbps = float(b.group(1))
        loss = LOSS.search(line)
        if end - start <= 1.5:
            per_sec.append((int(round(end)), mbps))
        else:
            summary = {"mbps": mbps,
                       "loss_pct": float(loss.group(3)) if loss else 0.0}
    if summary is None and per_sec:          # fall back to the average
        summary = {"mbps": sum(v for _, v in per_sec) / len(per_sec), "loss_pct": ""}
    return per_sec, summary


def read_file(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""


# ----------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------
def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def meters(switch):
    """[(meter_id, rate_kbps), ...] currently installed on a switch."""
    out = sh(["ovs-ofctl", "-O", "OpenFlow13", "dump-meters", switch])
    found, cur = [], None
    for line in out.splitlines():
        m = re.match(r"\s*meter=(\d+)", line)
        if m:
            cur = int(m.group(1))
            continue
        r = re.search(r"rate=(\d+)", line)
        if r and cur is not None:
            found.append((cur, int(r.group(1))))
            cur = None
    return found


def save_switch_state(tag):
    for sw in ("s1", "s2"):
        with open(os.path.join(RAW, "%s_%s_meters.txt" % (tag, sw)), "w") as f:
            f.write(sh(["ovs-ofctl", "-O", "OpenFlow13", "dump-meters", sw]))
        with open(os.path.join(RAW, "%s_%s_flows.txt" % (tag, sw)), "w") as f:
            f.write(sh(["ovs-ofctl", "-O", "OpenFlow13", "dump-flows", sw]))


def write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def ask(args, req):
    return send_request("127.0.0.1", args.server_port, req)


# ----------------------------------------------------------------------
# PART 1: baseline vs reservation
# ----------------------------------------------------------------------
def one_traffic_run(net, args, mode, run):
    h1, h2, h3, h4 = [net.get(n) for n in ("h1", "h2", "h3", "h4")]
    T = args.duration
    f3 = os.path.join(RAW, "run%d_%s_R_server.txt" % (run, mode))
    f4 = os.path.join(RAW, "run%d_%s_G_server.txt" % (run, mode))
    out3, out4 = open(f3, "w"), open(f4, "w")
    # servers listen for T+8 seconds, then exit by themselves (so their output is flushed)
    s3 = h3.popen(["iperf", "-s", "-u", "-p", "5001", "-i", "1", "-f", "m",
                   "-t", str(T + 8)], stdout=out3, stderr=subprocess.STDOUT)
    s4 = h4.popen(["iperf", "-s", "-u", "-p", "5002", "-i", "1", "-f", "m",
                   "-t", str(T + 8)], stdout=out4, stderr=subprocess.STDOUT)
    time.sleep(1.0)
    c1 = h1.popen(["iperf", "-c", "10.0.0.3", "-u", "-p", "5001", "-f", "m",
                   "-b", "%.2fM" % args.r_rate, "-t", str(T)],
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    c2 = h2.popen(["iperf", "-c", "10.0.0.4", "-u", "-p", "5002", "-f", "m",
                   "-b", "%.2fM" % args.g_rate, "-t", str(T)],
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(min(4.0, T / 2))
    if run == 1:                                  # keep evidence of the switch rules
        save_switch_state("run1_%s_during_traffic" % mode)
    c1.wait()
    c2.wait()
    for p in (s3, s4):
        try:
            p.wait(timeout=12)
        except subprocess.TimeoutExpired:
            p.terminate()
            p.wait()
    out3.close()
    out4.close()
    return parse_iperf(read_file(f3)), parse_iperf(read_file(f4))


def part1(net, args):
    print("\n=== PART 1: baseline vs reservation (%d runs each, %d s per run) ==="
          % (args.runs, args.duration))
    runs_rows, series_rows = [], []
    for run in range(1, args.runs + 1):
        for mode in ("baseline", "reserved"):
            rid = None
            if mode == "reserved":
                r = ask(args, {"cmd": "RESERVE", "src": "10.0.0.1", "dst": "10.0.0.3",
                               "bandwidth_mbps": args.reserve,
                               "duration_s": args.duration + 30})
                if r.get("status") != "ACCEPTED":
                    sys.exit("Reservation was not accepted: %s" % r)
                rid = r["id"]
                time.sleep(1.5)                    # let the controller install the rules
            (r_sec, r_sum), (g_sec, g_sum) = one_traffic_run(net, args, mode, run)
            if rid is not None:
                ask(args, {"cmd": "RELEASE", "id": rid})
                time.sleep(1.0)
            if not r_sum or not g_sum:
                print("  WARNING: could not read iperf output for run %d %s "
                      "(see results/raw/)" % (run, mode))
                continue
            print("  run %d %-8s reserved-stream %.2f Mbps (loss %s%%)   greedy-stream %.2f Mbps"
                  % (run, mode, r_sum["mbps"], r_sum["loss_pct"], g_sum["mbps"]))
            runs_rows.append([run, mode, r_sum["mbps"], r_sum["loss_pct"],
                              g_sum["mbps"], g_sum["loss_pct"]])
            for sec, v in r_sec:
                series_rows.append([run, mode, "reserved_stream", sec, v])
            for sec, v in g_sec:
                series_rows.append([run, mode, "greedy_stream", sec, v])
    write_csv(os.path.join(RESULTS, "comparison_runs.csv"),
              ["run", "mode", "reserved_mbps", "reserved_loss_pct",
               "greedy_mbps", "greedy_loss_pct"], runs_rows)
    write_csv(os.path.join(RESULTS, "comparison_timeseries.csv"),
              ["run", "mode", "stream", "second", "mbps"], series_rows)


# ----------------------------------------------------------------------
# PART 2: accepted / rejected under three loads
# ----------------------------------------------------------------------
def part2(args):
    print("\n=== PART 2: accepted/rejected requests at three load levels ===")
    for name, interval in (("light", 2.0), ("medium", 0.8), ("heavy", 0.2)):
        t0 = time.time()
        out = os.path.join(RESULTS, "workload_%s.csv" % name)
        subprocess.run([sys.executable, os.path.join(HERE, "workload.py"),
                        "--server", "127.0.0.1", "--port", str(args.server_port),
                        "--requests", "30", "--interval", str(interval),
                        "--seed", "1", "--out", out], check=True)
        time.sleep(10)                              # let every reservation expire
        phases.append((name, t0, time.time()))
        print("  %s load done" % name)


# ----------------------------------------------------------------------
# PART 3: challenge scenario
# ----------------------------------------------------------------------
def part3(args):
    print("\n=== PART 3: 25 simultaneous requests (overbooking test) ===")
    t0 = time.time()
    out = os.path.join(RESULTS, "workload_burst.csv")
    subprocess.run([sys.executable, os.path.join(HERE, "workload.py"),
                    "--server", "127.0.0.1", "--port", str(args.server_port),
                    "--requests", "25", "--interval", "0", "--min-bw", "1",
                    "--max-bw", "3", "--min-dur", "20", "--max-dur", "20",
                    "--seed", "7", "--out", out], check=True)
    time.sleep(1.5)
    stats = ask(args, {"cmd": "STATS"})
    save_switch_state("burst_active")
    reserved_s1 = sum(rate for mid, rate in meters("s1") if mid < 4000000)
    reserved_s2 = sum(rate for mid, rate in meters("s2") if mid < 4000000)
    be_s1 = [rate for mid, rate in meters("s1") if mid >= 4000000]
    cap_kbps = args.capacity * 1000
    ok_cap = reserved_s1 <= cap_kbps and reserved_s2 <= cap_kbps
    print("  server says: %d accepted so far, %.1f Mbps reserved of %.0f"
          % (stats["accepted"], stats["used_mbps"], args.capacity))
    print("  switch s1 : total reserved-meter rate %.1f Mbps  (limit %.0f)"
          % (reserved_s1 / 1000.0, args.capacity))
    print("  switch s2 : total reserved-meter rate %.1f Mbps  (limit %.0f)"
          % (reserved_s2 / 1000.0, args.capacity))
    print("  best-effort limiter on s1: %s kbps" % (be_s1 or "not installed"))
    print("  NO OVERBOOKING:", "PASS" if ok_cap else "FAIL")

    print("  waiting for all 25 reservations to expire (about 25 s) ...")
    time.sleep(25)
    left = meters("s1") + meters("s2")
    print("  meters left on the switches after expiry:", len(left),
          "-> ", "PASS" if not left else "FAIL")
    final = ask(args, {"cmd": "STATS"})
    write_csv(os.path.join(RESULTS, "burst_check.csv"),
              ["capacity_mbps", "accepted_total", "server_used_mbps",
               "s1_reserved_meter_mbps", "s2_reserved_meter_mbps",
               "no_overbooking", "meters_left_after_expiry", "server_used_after_mbps"],
              [[args.capacity, stats["accepted"], stats["used_mbps"],
                reserved_s1 / 1000.0, reserved_s2 / 1000.0,
                "PASS" if ok_cap else "FAIL", len(left), final["used_mbps"]]])
    phases.append(("burst", t0, time.time()))


# ----------------------------------------------------------------------
phases = []


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--capacity", type=float, default=10.0)
    p.add_argument("--server-port", type=int, default=5000)
    p.add_argument("--controller", default="http://127.0.0.1:8080")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--duration", type=int, default=10, help="seconds per traffic run")
    p.add_argument("--r-rate", type=float, default=3.8,
                   help="Mbps the reserved UDP stream sends (below the reservation, "
                        "because packet headers add about 3%%)")
    p.add_argument("--reserve", type=float, default=4.0, help="Mbps reserved for it")
    p.add_argument("--g-rate", type=float, default=10.0, help="Mbps of the greedy stream")
    p.add_argument("--parts", default="123", help="which parts to run, e.g. 123 or 1")
    args = p.parse_args()

    if os.geteuid() != 0:
        sys.exit("Run with sudo:  sudo python3 tools/experiment.py")
    os.makedirs(RAW, exist_ok=True)

    # the server and the controller must already be running
    try:
        ask(args, {"cmd": "STATS"})
    except (OSError, ValueError):
        sys.exit("Cannot reach the reservation server on port %d. Start it first."
                 % args.server_port)

    from mininet.link import TCLink  # noqa: F401  (fails early if mininet is missing)
    from mininet.log import setLogLevel
    from topo import build
    from sdn_policy import ControllerPolicy

    setLogLevel("warning")
    net = build(args.capacity)
    net.start()
    try:
        health = ControllerPolicy(args.controller, verbose=False)
        for _ in range(20):
            status, body = health._call("GET", "/health")
            if status == 200 and len(body.get("switches", [])) == 2:
                break
            time.sleep(1)
        else:
            sys.exit("Controller does not see both switches. Is ryu-manager running?")
        print("controller sees switches:", body["switches"])
        net.pingAll()

        if "1" in args.parts:
            part1(net, args)
        if "2" in args.parts:
            part2(args)
        if "3" in args.parts:
            part3(args)
    finally:
        net.stop()
        if phases:
            write_csv(os.path.join(RESULTS, "phases.csv"),
                      ["phase", "start_epoch", "end_epoch"],
                      [[n, "%.3f" % a, "%.3f" % b] for n, a, b in phases])
        try:
            final = ask(args, {"cmd": "STATS"})
            with open(os.path.join(RESULTS, "server_stats.json"), "w") as f:
                json.dump(final, f, indent=2)
        except (OSError, ValueError):
            pass
    print("\nDone. Now run:  python3 tools/make_graphs.py")


if __name__ == "__main__":
    main()
