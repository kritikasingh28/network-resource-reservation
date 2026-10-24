"""
resource_manager.py
-------------------
Keeps track of the network bandwidth that can be reserved.

Idea: our network has ONE bottleneck link with a fixed capacity (for example
10 Mbps). Every reservation takes a slice of that capacity for some time.
This file decides:
  * is there enough bandwidth left?          (conflict detection)
  * is the same host pair already reserved?  (conflict detection)
  * when does a reservation end?             (expiry)
  * how many requests were accepted/rejected? (statistics)

Many client threads call this class at the same time, so every change to the
shared data happens while holding a lock.
"""

import csv
import ipaddress
import os
import threading
import time


class NullPolicy:
    """Stage 1 stand-in for the SDN controller.

    It only prints what WOULD be installed. In Stage 4 we replace it with a
    class that talks to the real Ryu controller. Both classes have the same
    two methods, so ResourceManager does not need to change.
    """

    def __init__(self, verbose=True):
        self.verbose = verbose

    def install(self, res):
        if self.verbose:
            print("[policy] install  id=%d %s -> %s %.2f Mbps"
                  % (res["id"], res["src"], res["dst"], res["bandwidth_mbps"]))
        return True   # True = success

    def remove(self, res):
        if self.verbose:
            print("[policy] remove   id=%d %s -> %s"
                  % (res["id"], res["src"], res["dst"]))
        return True


class ResourceManager:
    def __init__(self, capacity_mbps=10.0, policy=None, log_path=None,
                 max_duration_s=3600):
        self.capacity = float(capacity_mbps)
        self.policy = policy if policy is not None else NullPolicy()
        self.log_path = log_path
        self.max_duration = max_duration_s

        self.lock = threading.Lock()      # protects everything below
        self.reservations = {}            # id -> reservation dict
        self.next_id = 1
        self.stats = {"accepted": 0, "rejected": 0, "released": 0,
                      "expired": 0, "rejected_reasons": {}}

        self._stop_event = threading.Event()
        self._expiry_thread = None

    # ------------------------------------------------------------------
    # helpers (call these only while holding self.lock)
    # ------------------------------------------------------------------
    def _used(self):
        return sum(r["bandwidth_mbps"] for r in self.reservations.values())

    def _log(self, event, res=None, reason=""):
        """Append one line to the CSV event log (used later for graphs)."""
        if not self.log_path:
            return
        new_file = not os.path.exists(self.log_path)
        used = self._used()
        with open(self.log_path, "a", newline="") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["time", "event", "id", "src", "dst", "bandwidth_mbps",
                            "used_mbps", "utilization_pct", "reason"])
            w.writerow([
                "%.3f" % time.time(), event,
                res["id"] if res else "",
                res["src"] if res else "",
                res["dst"] if res else "",
                res["bandwidth_mbps"] if res else "",
                "%.2f" % used, "%.1f" % (100.0 * used / self.capacity), reason])

    def _reject(self, reason, message, src="", dst="", bw=""):
        self.stats["rejected"] += 1
        reasons = self.stats["rejected_reasons"]
        reasons[reason] = reasons.get(reason, 0) + 1
        fake = {"id": "", "src": src, "dst": dst, "bandwidth_mbps": bw}
        self._log("REJECTED", fake, reason)
        return {"status": "REJECTED", "reason": reason, "message": message,
                "available_mbps": round(self.capacity - self._used(), 3)}

    def _remove(self, rid, event):
        """Take a reservation out and tell the policy to remove the rule."""
        res = self.reservations.pop(rid)
        self.policy.remove(res)
        self._log(event, res)
        return res

    # ------------------------------------------------------------------
    # public operations
    # ------------------------------------------------------------------
    def reserve(self, src, dst, bandwidth_mbps, duration_s):
        # 1) validate the input
        try:
            ipaddress.ip_address(src)
            ipaddress.ip_address(dst)
            bandwidth_mbps = float(bandwidth_mbps)
            duration_s = float(duration_s)
        except (ValueError, TypeError):
            with self.lock:
                return self._reject("INVALID_REQUEST",
                                    "src/dst must be IP addresses and "
                                    "bandwidth/duration must be numbers")
        if src == dst:
            with self.lock:
                return self._reject("INVALID_REQUEST", "src and dst are the same",
                                    src, dst, bandwidth_mbps)
        if bandwidth_mbps <= 0 or bandwidth_mbps > self.capacity:
            with self.lock:
                return self._reject("INVALID_REQUEST",
                                    "bandwidth must be > 0 and <= %.1f Mbps"
                                    % self.capacity, src, dst, bandwidth_mbps)
        if duration_s <= 0 or duration_s > self.max_duration:
            with self.lock:
                return self._reject("INVALID_REQUEST",
                                    "duration must be > 0 and <= %d s"
                                    % self.max_duration, src, dst, bandwidth_mbps)

        # 2) conflict detection + allocation, all under the lock so two
        #    clients can never both grab the last free bandwidth
        with self.lock:
            for r in self.reservations.values():
                if r["src"] == src and r["dst"] == dst:
                    return self._reject(
                        "DUPLICATE_FLOW",
                        "this host pair already has reservation %d" % r["id"],
                        src, dst, bandwidth_mbps)

            if self._used() + bandwidth_mbps > self.capacity + 1e-9:
                return self._reject(
                    "INSUFFICIENT_BANDWIDTH",
                    "not enough free bandwidth on the link",
                    src, dst, bandwidth_mbps)

            res = {"id": self.next_id, "src": src, "dst": dst,
                   "bandwidth_mbps": bandwidth_mbps, "duration_s": duration_s,
                   "start": time.time(), "expires_at": time.time() + duration_s}

            # install the SDN rule; if that fails, do not keep the reservation
            if not self.policy.install(res):
                return self._reject("POLICY_FAILED",
                                    "controller could not install the policy",
                                    src, dst, bandwidth_mbps)

            self.next_id += 1
            self.reservations[res["id"]] = res
            self.stats["accepted"] += 1
            self._log("ACCEPTED", res)
            return {"status": "ACCEPTED", "id": res["id"], "src": src, "dst": dst,
                    "bandwidth_mbps": bandwidth_mbps, "duration_s": duration_s}

    def release(self, rid):
        with self.lock:
            if rid not in self.reservations:
                return {"status": "ERROR", "reason": "NOT_FOUND",
                        "message": "no active reservation with id %s" % rid}
            self._remove(rid, "RELEASED")
            self.stats["released"] += 1
            return {"status": "OK", "message": "reservation %s released" % rid}

    def status(self, rid):
        with self.lock:
            r = self.reservations.get(rid)
            if r is None:
                return {"status": "ERROR", "reason": "NOT_FOUND",
                        "message": "no active reservation with id %s "
                                   "(never existed, released or expired)" % rid}
            return {"status": "OK", "id": rid, "src": r["src"], "dst": r["dst"],
                    "bandwidth_mbps": r["bandwidth_mbps"],
                    "remaining_s": round(r["expires_at"] - time.time(), 1)}

    def list_active(self):
        with self.lock:
            items = [{"id": r["id"], "src": r["src"], "dst": r["dst"],
                      "bandwidth_mbps": r["bandwidth_mbps"],
                      "remaining_s": round(r["expires_at"] - time.time(), 1)}
                     for r in self.reservations.values()]
            return {"status": "OK", "reservations": items}

    def get_stats(self):
        with self.lock:
            used = self._used()
            return {"status": "OK",
                    "capacity_mbps": self.capacity,
                    "used_mbps": round(used, 3),
                    "available_mbps": round(self.capacity - used, 3),
                    "utilization_pct": round(100.0 * used / self.capacity, 1),
                    "active_reservations": len(self.reservations),
                    "accepted": self.stats["accepted"],
                    "rejected": self.stats["rejected"],
                    "released": self.stats["released"],
                    "expired": self.stats["expired"],
                    "rejected_reasons": dict(self.stats["rejected_reasons"])}

    # ------------------------------------------------------------------
    # expiry
    # ------------------------------------------------------------------
    def expire_old(self):
        """Remove every reservation whose time is over. Returns how many."""
        now = time.time()
        with self.lock:
            dead = [rid for rid, r in self.reservations.items()
                    if r["expires_at"] <= now]
            for rid in dead:
                self._remove(rid, "EXPIRED")
                self.stats["expired"] += 1
            return len(dead)

    def start_expiry_thread(self, interval_s=1.0):
        def loop():
            while not self._stop_event.wait(interval_s):
                self.expire_old()
        self._expiry_thread = threading.Thread(target=loop, daemon=True)
        self._expiry_thread.start()

        # ------------------------------------------------------------------
    # utilization tracking: write one row every `interval_s` seconds
    # ------------------------------------------------------------------
    def start_sampler(self, path, interval_s=1.0):
        t0 = time.time()
        with open(path, "w", newline="") as f:
            csv.writer(f).writerow(["time", "elapsed_s", "used_mbps",
                                    "utilization_pct", "active_reservations"])

        def loop():
            while not self._stop_event.wait(interval_s):
                with self.lock:
                    used = self._used()
                    active = len(self.reservations)
                with open(path, "a", newline="") as f:
                    csv.writer(f).writerow([
                        "%.3f" % time.time(), "%.1f" % (time.time() - t0),
                        "%.2f" % used, "%.1f" % (100.0 * used / self.capacity),
                        active])
        threading.Thread(target=loop, daemon=True).start()

    def stop(self):
        self._stop_event.set()
