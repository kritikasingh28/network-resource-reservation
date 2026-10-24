"""
server.py
---------
TCP reservation server.

* One listening socket; every client connection is handled in its own thread,
  so many clients can talk to the server at the same time.
* Protocol: one JSON object per line ("\n" at the end), both directions.

  request : {"cmd": "RESERVE", "src": "10.0.0.1", "dst": "10.0.0.3",
             "bandwidth_mbps": 4, "duration_s": 60}
            {"cmd": "RELEASE", "id": 1}
            {"cmd": "STATUS",  "id": 1}
            {"cmd": "LIST"}
            {"cmd": "STATS"}
  response: {"status": "ACCEPTED" | "REJECTED" | "OK" | "ERROR", ...}

Run:  python3 server/server.py --port 5000 --capacity 10
"""

import argparse
import json
import socket
import threading

from resource_manager import ResourceManager, NullPolicy
from sdn_policy import ControllerPolicy

MAX_LINE = 65536          # longest request line we accept (bytes)
IDLE_TIMEOUT_S = 120      # close a connection that is silent for this long


def handle_request(manager, req):
    """Turn one request (a dict) into one response (a dict)."""
    if not isinstance(req, dict):
        return {"status": "ERROR", "message": "request must be a JSON object"}
    cmd = str(req.get("cmd", "")).upper()

    if cmd == "RESERVE":
        return manager.reserve(req.get("src"), req.get("dst"),
                               req.get("bandwidth_mbps"), req.get("duration_s"))
    if cmd in ("RELEASE", "STATUS"):
        try:
            rid = int(req.get("id"))
        except (TypeError, ValueError):
            return {"status": "ERROR", "message": "id must be an integer"}
        return manager.release(rid) if cmd == "RELEASE" else manager.status(rid)
    if cmd == "LIST":
        return manager.list_active()
    if cmd == "STATS":
        return manager.get_stats()
    return {"status": "ERROR", "message": "unknown command: %r" % cmd}


class ReservationServer:
    def __init__(self, manager, host="0.0.0.0", port=5000):
        self.manager = manager
        self.host = host
        self.port = port
        self.sock = None
        self._stop = threading.Event()

    def start(self):
        """Open the socket and accept clients in a background thread."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.listen(50)
        self.sock.settimeout(1.0)          # so the loop can notice stop()
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return self.port

    def stop(self):
        self._stop.set()
        if self.sock:
            self.sock.close()

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, addr = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(conn, addr),
                             daemon=True).start()

    def _send(self, conn, resp):
        conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))

    def _handle_client(self, conn, addr):
        conn.settimeout(IDLE_TIMEOUT_S)
        try:
            f = conn.makefile("r", encoding="utf-8", newline="\n")
            while True:
                line = f.readline(MAX_LINE)
                if not line:                      # client closed the connection
                    break
                if len(line) >= MAX_LINE and not line.endswith("\n"):
                    self._send(conn, {"status": "ERROR",
                                      "message": "request line too long"})
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    req = json.loads(line)
                except json.JSONDecodeError:
                    resp = {"status": "ERROR", "message": "invalid JSON"}
                else:
                    resp = handle_request(self.manager, req)
                self._send(conn, resp)
        except OSError:
            pass                                  # timeout / connection reset
        finally:
            conn.close()


def main():
    p = argparse.ArgumentParser(description="TCP bandwidth reservation server")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--capacity", type=float, default=10.0,
                   help="reservable link capacity in Mbps")
    p.add_argument("--log", default=None, help="CSV file for the event log")
    p.add_argument("--controller", default=None,
                   help="Ryu REST URL, e.g. http://127.0.0.1:8080 "
                        "(leave out to run without an SDN controller)")
    args = p.parse_args()

    if args.controller:
        policy = ControllerPolicy(args.controller)
        print("SDN policies will be sent to %s" % args.controller)
    else:
        policy = NullPolicy()
        print("No --controller given: policies are only printed, not installed")
    manager = ResourceManager(capacity_mbps=args.capacity, policy=policy,
                              log_path=args.log)
    manager.start_expiry_thread()
    server = ReservationServer(manager, args.host, args.port)
    port = server.start()
    print("Reservation server listening on %s:%d (capacity %.1f Mbps)"
          % (args.host, port, args.capacity))
    try:
        threading.Event().wait()                  # run until Ctrl+C
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.stop()
        manager.stop()


if __name__ == "__main__":
    main()
