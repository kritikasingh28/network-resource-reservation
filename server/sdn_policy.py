"""
sdn_policy.py
-------------
The bridge between the reservation server and the SDN controller.

ResourceManager calls install() when a reservation is accepted and remove()
when it is released or expires. Here we turn those calls into HTTP requests
to the Ryu controller's REST API (controller/reservation_controller.py).

It has the same two methods as NullPolicy (in resource_manager.py), so the
ResourceManager does not care which one it is given.
"""

import json
import urllib.error
import urllib.request


class ControllerPolicy:
    def __init__(self, base_url="http://127.0.0.1:8080", timeout=3.0, verbose=True,
                 capacity_mbps=None):
        self.capacity_mbps = capacity_mbps   # sent so the controller can cap unreserved traffic
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verbose = verbose
        # talk to the controller directly, never through an HTTP proxy
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _call(self, method, path, body=None):
        """Send one HTTP request. Returns (status_code or None, response dict)."""
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            self.base_url + path, data=data, method=method,
            headers={"Content-Type": "application/json"})
        try:
            with self._opener.open(req, timeout=self.timeout) as r:
                return r.status, json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:           # controller answered with an error code
            try:
                return e.code, json.loads(e.read().decode("utf-8") or "{}")
            except ValueError:
                return e.code, {}
        except (urllib.error.URLError, OSError, ValueError) as e:   # unreachable / bad reply
            return None, {"message": str(e)}

    def _say(self, text):
        if self.verbose:
            print("[sdn] " + text)

    def install(self, res):
        """Ask the controller to install the rate-limit rule. True = success."""
        payload = {"id": res["id"], "src": res["src"], "dst": res["dst"],
                   "bandwidth_mbps": res["bandwidth_mbps"]}
        if self.capacity_mbps is not None:
            payload["capacity_mbps"] = self.capacity_mbps
        status, body = self._call("POST", "/policy", payload)
        ok = (status == 200 and body.get("status") == "ok")
        self._say("install id=%s %s -> %s %.2f Mbps : %s"
                  % (res["id"], res["src"], res["dst"], res["bandwidth_mbps"],
                     "OK" if ok else "FAILED (%s %s)" % (status, body.get("message", ""))))
        return ok

    def remove(self, res):
        """Ask the controller to remove the rule. 404 counts as success
        (it is already gone)."""
        status, body = self._call("DELETE", "/policy/%d" % res["id"])
        ok = status in (200, 404)
        self._say("remove  id=%s : %s"
                  % (res["id"], "OK" if ok else "FAILED (%s %s)" % (status, body.get("message", ""))))
        return ok
