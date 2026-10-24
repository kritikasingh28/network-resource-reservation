"""
client.py
---------
Command-line TCP client for the reservation server.

Examples:
  python3 client/client.py reserve 10.0.0.1 10.0.0.3 4 60
  python3 client/client.py status 1
  python3 client/client.py release 1
  python3 client/client.py list
  python3 client/client.py stats
"""

import argparse
import json
import socket


def send_request(host, port, request, timeout=5.0):
    """Open a TCP connection, send ONE request line, return the response dict."""
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.sendall((json.dumps(request) + "\n").encode("utf-8"))
        f = s.makefile("r", encoding="utf-8", newline="\n")
        line = f.readline()
    if not line:
        raise ConnectionError("server closed the connection without replying")
    return json.loads(line)


def main():
    p = argparse.ArgumentParser(description="Bandwidth reservation client")
    p.add_argument("--server", default="127.0.0.1", help="server IP address")
    p.add_argument("--port", type=int, default=5000)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("reserve", help="request bandwidth between two hosts")
    r.add_argument("src")
    r.add_argument("dst")
    r.add_argument("bandwidth_mbps", type=float)
    r.add_argument("duration_s", type=float)

    for name in ("release", "status"):
        s = sub.add_parser(name)
        s.add_argument("id", type=int)
    sub.add_parser("list")
    sub.add_parser("stats")

    a = p.parse_args()
    if a.cmd == "reserve":
        req = {"cmd": "RESERVE", "src": a.src, "dst": a.dst,
               "bandwidth_mbps": a.bandwidth_mbps, "duration_s": a.duration_s}
    elif a.cmd in ("release", "status"):
        req = {"cmd": a.cmd.upper(), "id": a.id}
    else:
        req = {"cmd": a.cmd.upper()}

    try:
        print(json.dumps(send_request(a.server, a.port, req), indent=2))
    except (OSError, ValueError) as e:
        print("Could not talk to the server: %s" % e)


if __name__ == "__main__":
    main()
