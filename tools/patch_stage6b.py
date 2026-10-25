"""
patch_stage6b.py - applies the Stage 6 fix to tools/experiment.py and tools/make_graphs.py.
Usage:  python3 patch_stage6b.py ~/sdn-reservation
Nothing is written unless every replacement is found exactly once.
"""
import os
import sys

root = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else ".")
exp_path = os.path.join(root, "tools", "experiment.py")
gr_path = os.path.join(root, "tools", "make_graphs.py")
exp = open(exp_path).read()
gr = open(gr_path).read()

# ---- 1. replace one_traffic_run() with a version that runs several greedy streams
start = exp.index("def one_traffic_run(")
end = exp.index("def part1(")
NEW_FUNC = '''def combine(results):
    """Add up several parsed iperf streams -> (per_second list, summary)."""
    secs, total, losses = {}, 0.0, []
    for per_sec, summ in results:
        for sec, v in per_sec:
            secs[sec] = secs.get(sec, 0.0) + v
        if summ:
            total += summ["mbps"]
            if summ["loss_pct"] != "":
                losses.append(summ["loss_pct"])
    if not total:
        return [], None
    return sorted(secs.items()), {
        "mbps": total,
        "loss_pct": (sum(losses) / len(losses)) if losses else ""}


def one_traffic_run(net, args, mode, run):
    h1, h2, h3, h4 = [net.get(n) for n in ("h1", "h2", "h3", "h4")]
    T = args.duration
    # port 5001 = the reserved stream (h1 -> h3)
    # ports 5002... = the greedy background streams (h2 -> h4)
    jobs = [("R", h3, 5001)] + [("G%d" % i, h4, 5001 + i)
                                for i in range(1, args.greedy_streams + 1)]
    servers, files = [], []
    for name, host, port in jobs:
        path = os.path.join(RAW, "run%d_%s_%s_server.txt" % (run, mode, name))
        fh = open(path, "w")
        files.append((name, path, fh))
        # servers listen for T+8 seconds, then exit by themselves (so their output is flushed)
        servers.append(host.popen(["iperf", "-s", "-u", "-p", str(port), "-i", "1",
                                   "-f", "m", "-t", str(T + 8)],
                                  stdout=fh, stderr=subprocess.STDOUT))
    time.sleep(1.0)
    clients = [h1.popen(["iperf", "-c", "10.0.0.3", "-u", "-p", "5001", "-f", "m",
                         "-b", "%.2fM" % args.r_rate, "-t", str(T)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)]
    for i in range(1, args.greedy_streams + 1):
        clients.append(h2.popen(["iperf", "-c", "10.0.0.4", "-u", "-p", str(5001 + i),
                                 "-f", "m", "-b", "%.2fM" % args.g_rate, "-t", str(T)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    time.sleep(min(4.0, T / 2))
    if run == 1:                                  # keep evidence of the switch rules
        save_switch_state("run1_%s_during_traffic" % mode)
    for c in clients:
        c.wait()
    for p in servers:
        try:
            p.wait(timeout=12)
        except subprocess.TimeoutExpired:
            p.terminate()
            p.wait()
    for _, _, fh in files:
        fh.close()
    parsed = {name: parse_iperf(read_file(path)) for name, path, _ in files}
    greedy = combine([v for k, v in parsed.items() if k != "R"])
    return parsed["R"], greedy


'''
exp = exp[:start] + NEW_FUNC + exp[end:]

# ---- 2. new command-line options and defaults
OLD_ARGS = '''    p.add_argument("--r-rate", type=float, default=3.8,
                   help="Mbps the reserved UDP stream sends (below the reservation, "
                        "because packet headers add about 3%%)")
    p.add_argument("--reserve", type=float, default=4.0, help="Mbps reserved for it")
    p.add_argument("--g-rate", type=float, default=10.0, help="Mbps of the greedy stream")
'''
NEW_ARGS = '''    p.add_argument("--r-rate", type=float, default=3.4,
                   help="iperf -b setting of the reserved UDP stream (kept well below "
                        "the reservation: iperf's M is 2^20 and headers add ~3%%)")
    p.add_argument("--reserve", type=float, default=4.0, help="Mbps reserved for it")
    p.add_argument("--g-rate", type=float, default=5.0,
                   help="iperf -b setting of EACH greedy stream")
    p.add_argument("--greedy-streams", type=int, default=4,
                   help="number of greedy background streams (h2 to h4)")
'''
assert exp.count(OLD_ARGS) == 1, "could not find the option block in experiment.py"
exp = exp.replace(OLD_ARGS, NEW_ARGS)

# ---- 3. graphs: new default target and wording
assert gr.count('default=3.8,') == 1, "make_graphs.py: target default not found"
gr = gr.replace('default=3.8,', 'default=3.4,')
assert gr.count('"Greedy stream (h2 to h4)"') == 2, "make_graphs.py: titles not found"
gr = gr.replace('"Greedy stream (h2 to h4)"', '"Greedy streams (h2 to h4, total)"')
assert gr.count('"dashed line: %.1f Mbps sent" % target') == 1, "make_graphs.py: label not found"
gr = gr.replace('"dashed line: %.1f Mbps sent" % target',
                '"dashed line: sender set to iperf -b %.1fM" % target')

open(exp_path, "w").write(exp)
open(gr_path, "w").write(gr)
print("patched:", exp_path)
print("patched:", gr_path)
