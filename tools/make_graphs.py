#!/usr/bin/env python3
"""
tools/make_graphs.py
--------------------
Turns the CSV files in results/ into graphs (PNG files in results/graphs/).
Needs matplotlib:  sudo apt install python3-matplotlib -y

    python3 tools/make_graphs.py
Graphs whose input files do not exist are skipped.
"""
import argparse
import csv
import os
import statistics
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")                      # draw to files, no window needed
import matplotlib.pyplot as plt            # noqa: E402

# colours: one meaning per colour across all graphs
BASELINE = "#eb6834"      # orange = no reservation
RESERVED = "#2a78d6"      # blue   = with reservation
NEUTRAL = "#9a9993"       # grey   = rejected requests
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "text.color": INK,
    "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 11, "axes.titlesize": 13, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "legend.frameon": False,
})


def read(path):
    if not os.path.exists(path):
        return None
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def save(fig, outdir, name):
    path = os.path.join(outdir, name)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    print("wrote", path)


# ---------------------------------------------------------------- fig 1
def fig_comparison(res, outdir, target):
    rows = read(os.path.join(res, "comparison_runs.csv"))
    if not rows:
        return
    by = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by[r["mode"]]["r"].append(fnum(r["reserved_mbps"]))
        by[r["mode"]]["loss"].append(fnum(r["reserved_loss_pct"]))
        by[r["mode"]]["g"].append(fnum(r["greedy_mbps"]))
    modes = [("baseline", "No reservation", BASELINE),
             ("reserved", "With reservation", RESERVED)]

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.4))
    for ax, key, title in ((axes[0], "r", "Reserved stream (h1 to h3)"),
                           (axes[1], "g", "Greedy stream (h2 to h4)")):
        for i, (m, label, col) in enumerate(modes):
            vals = [v for v in by[m][key] if v is not None]
            if not vals:
                continue
            mean = statistics.mean(vals)
            ax.bar(i, mean, width=0.55, color=col, label=label)
            ax.scatter([i] * len(vals), vals, color=INK, s=14, zorder=3)
            txt = "%.2f Mbps" % mean
            if key == "r" and by[m]["loss"] and by[m]["loss"][0] is not None:
                txt += "\nloss %.1f%%" % statistics.mean(
                    v for v in by[m]["loss"] if v is not None)
            ax.text(i, mean / 2.0, txt, ha="center", va="center", fontsize=11,
                    color="white", fontweight="bold")
        ax.set_xticks([0, 1])
        ax.set_xticklabels([m[1] for m in modes])
        ax.set_ylabel("Received throughput (Mbps)")
        ax.set_ylim(0, 11)
        ax.set_title(title)
        ax.grid(axis="x", visible=False)
    axes[0].axhline(target, color=INK2, linestyle="--", linewidth=1.2)
    axes[0].text(-0.38, target + 0.2, "dashed line: %.1f Mbps sent" % target,
                 ha="left", fontsize=9, color=INK2)
    axes[0].legend(loc="upper left")
    fig.suptitle("Effect of a 4 Mbps reservation on a shared 10 Mbps link "
                 "(dots = individual runs)", x=0.01, ha="left", fontsize=12)
    save(fig, outdir, "fig1_baseline_vs_reservation.png")

    # text summary
    with open(os.path.join(res, "comparison_summary.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mode", "runs", "reserved_mean_mbps", "reserved_min_mbps",
                    "reserved_loss_mean_pct", "greedy_mean_mbps"])
        for m, label, _ in modes:
            r = [v for v in by[m]["r"] if v is not None]
            l = [v for v in by[m]["loss"] if v is not None]
            g = [v for v in by[m]["g"] if v is not None]
            if r:
                w.writerow([m, len(r), "%.2f" % statistics.mean(r), "%.2f" % min(r),
                            "%.2f" % statistics.mean(l) if l else "",
                            "%.2f" % statistics.mean(g)])
    print("wrote", os.path.join(res, "comparison_summary.csv"))


# ---------------------------------------------------------------- fig 2
def fig_timeseries(res, outdir, target):
    rows = read(os.path.join(res, "comparison_timeseries.csv"))
    if not rows:
        return
    data = defaultdict(lambda: defaultdict(list))   # (stream, mode) -> second -> [mbps]
    for r in rows:
        data[(r["stream"], r["mode"])][int(r["second"])].append(float(r["mbps"]))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharey=True)
    for ax, stream, title in ((axes[0], "reserved_stream", "Reserved stream (h1 to h3)"),
                              (axes[1], "greedy_stream", "Greedy stream (h2 to h4)")):
        for mode, label, col in (("baseline", "No reservation", BASELINE),
                                 ("reserved", "With reservation", RESERVED)):
            d = data.get((stream, mode))
            if not d:
                continue
            secs = sorted(d)
            ax.plot(secs, [statistics.mean(d[s]) for s in secs], color=col,
                    linewidth=2, label=label)
        ax.set_title(title)
        ax.set_xlabel("Seconds since the test started")
        ax.set_ylim(0, 11)
        ax.legend(loc="lower right" if stream == "greedy_stream" else "lower left")
    axes[0].set_ylabel("Received throughput (Mbps, mean of runs)")
    axes[0].axhline(target, color=INK2, linestyle="--", linewidth=1.2)
    save(fig, outdir, "fig2_throughput_over_time.png")


# ---------------------------------------------------------------- fig 3
def fig_loads(res, outdir):
    names = [("light", "Light\n(1 request / 2 s)"), ("medium", "Medium\n(1 request / 0.8 s)"),
             ("heavy", "Heavy\n(1 request / 0.2 s)")]
    acc, rej, labels = [], [], []
    reasons = {}
    for key, label in names:
        rows = read(os.path.join(res, "workload_%s.csv" % key))
        if not rows:
            continue
        a = sum(1 for r in rows if r["status"] == "ACCEPTED")
        rj = [r for r in rows if r["status"] == "REJECTED"]
        acc.append(a)
        rej.append(len(rj))
        labels.append(label)
        reasons[key] = {x: sum(1 for r in rj if r["reason"] == x)
                        for x in {r["reason"] for r in rj}}
    if not acc:
        return
    fig, ax = plt.subplots(figsize=(8, 4.6))
    xs = range(len(labels))
    ax.bar(xs, acc, width=0.55, color=RESERVED, label="Accepted")
    ax.bar(xs, rej, width=0.55, bottom=[a + 0.0 for a in acc], color=NEUTRAL,
           label="Rejected", edgecolor=SURFACE, linewidth=2)
    for i, (a, r) in enumerate(zip(acc, rej)):
        ax.text(i, a / 2.0, "%d accepted" % a, ha="center", va="center",
                color="white", fontsize=10, fontweight="bold")
        ax.text(i, a + r / 2.0, "%d rejected" % r, ha="center", va="center",
                color=INK, fontsize=10)
        ax.text(i, a + r + 0.5, "%.0f%% accepted" % (100.0 * a / (a + r)),
                ha="center", fontsize=10, color=INK2)
    ax.set_xticks(list(xs))
    ax.set_xticklabels(labels)
    ax.set_ylabel("Requests (30 per load level)")
    ax.set_ylim(0, 35)
    ax.set_title("Accepted and rejected reservation requests by load")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper right", ncol=2)
    save(fig, outdir, "fig3_accepted_rejected_by_load.png")


# ---------------------------------------------------------------- fig 4
def fig_utilization(res, outdir):
    rows = read(os.path.join(res, "utilization.csv"))
    if not rows:
        return
    ph = read(os.path.join(res, "phases.csv")) or []
    t0 = float(rows[0]["time"])
    xs = [float(r["time"]) - t0 for r in rows]
    ys = [float(r["utilization_pct"]) for r in rows]
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.plot(xs, ys, color=RESERVED, linewidth=2)
    ax.axhline(100, color=INK2, linestyle="--", linewidth=1)
    for r in ph:
        a, b = float(r["start_epoch"]) - t0, float(r["end_epoch"]) - t0
        ax.axvspan(a, b, color=GRID, alpha=0.45, linewidth=0)
        ax.text((a + b) / 2, 104, r["phase"], ha="center", fontsize=9, color=INK2)
    ax.set_ylim(0, 112)
    ax.set_xlabel("Seconds since the server started")
    ax.set_ylabel("Reserved share of link capacity (%)")
    ax.set_title("Link utilization tracked by the server (one sample per second)")
    save(fig, outdir, "fig4_utilization_over_time.png")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--results", default=os.path.join(os.path.dirname(__file__), "..", "results"))
    p.add_argument("--target", type=float, default=3.8,
                   help="Mbps the reserved UDP stream sends (dashed line)")
    a = p.parse_args()
    res = os.path.abspath(a.results)
    out = os.path.join(res, "graphs")
    os.makedirs(out, exist_ok=True)
    fig_comparison(res, out, a.target)
    fig_timeseries(res, out, a.target)
    fig_loads(res, out)
    fig_utilization(res, out)


if __name__ == "__main__":
    main()
