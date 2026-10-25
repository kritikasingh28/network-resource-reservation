"""
controller/reservation_controller.py
------------------------------------
Ryu SDN controller = a normal learning switch (from Ryu's simple_switch_13)
PLUS a small REST API that the reservation server calls to install and
remove bandwidth policies.

REST API (listens on http://127.0.0.1:8080):
  POST   /policy      body: {"id": 1, "src": "10.0.0.1", "dst": "10.0.0.3",
                             "bandwidth_mbps": 4, "capacity_mbps": 10}
  DELETE /policy/1
  GET    /policy      -> list of installed policies
  GET    /health      -> {"status": "ok", "switches": [1, 2]}

What the controller installs on every switch (OpenFlow 1.3):

 1. RESERVED flow (priority 100), one per reservation
      match  : IPv4 src -> dst
      action : through a METER that drops anything above the reserved rate,
               then forward like a normal switch.

 2. BEST-EFFORT limiter (priority 50), exists only while reservations exist
      match  : all other IPv4 traffic
      action : through a METER set to (link capacity - total reserved)
    Without it, unreserved traffic could still fill the link and squeeze the
    reserved flows. With it, reserved + unreserved can never exceed capacity.
    It is updated on every reserve/release/expiry and removed when the last
    reservation ends.

Run (venv-ryu active):  ryu-manager controller/reservation_controller.py
"""

import json

from ryu.app import simple_switch_13
from ryu.app.wsgi import ControllerBase, WSGIApplication, route
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from webob import Response

POLICY_PRIORITY = 100
BE_PRIORITY = 50
BE_METER_ID = 4000000          # reserved meter id for the best-effort limiter
MIN_BE_KBPS = 100              # never let the limiter reach 0 (control traffic)
ETH_TYPE_IP = 0x0800
APP_NAME = "reservation_api_app"


class ReservationController(simple_switch_13.SimpleSwitch13):
    _CONTEXTS = {"wsgi": WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(ReservationController, self).__init__(*args, **kwargs)
        self.datapaths = {}        # dpid -> datapath (connected switches)
        self.policies = {}         # policy id -> dict
        self.capacity_mbps = None  # told to us by the server in each POST
        self.be_installed = False
        wsgi = kwargs["wsgi"]
        wsgi.register(PolicyRestApi, {APP_NAME: self})

    # keep a list of connected switches
    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[dp.id] = dp
            self.logger.info("switch connected: dpid=%s", dp.id)
        elif ev.state == DEAD_DISPATCHER:
            self.datapaths.pop(dp.id, None)
            self.logger.info("switch disconnected: dpid=%s", dp.id)

    # ------------------------------------------------------------------
    # reserved-flow policies
    # ------------------------------------------------------------------
    def install_policy(self, pid, src, dst, mbps, capacity_mbps=None):
        if capacity_mbps:
            self.capacity_mbps = float(capacity_mbps)
        if pid in self.policies:               # same id again: replace it
            self.remove_policy(pid, update=False)
        if not self.datapaths:
            raise RuntimeError("no switches connected to the controller")

        kbps = int(mbps * 1000)
        burst = max(100, kbps // 10)           # allowed burst in kilobits
        for dp in self.datapaths.values():
            ofp, parser = dp.ofproto, dp.ofproto_parser

            # 1) meter: DROP everything above `kbps`
            band = parser.OFPMeterBandDrop(rate=kbps, burst_size=burst)
            dp.send_msg(parser.OFPMeterMod(
                datapath=dp, command=ofp.OFPMC_ADD,
                flags=ofp.OFPMF_KBPS | ofp.OFPMF_BURST,
                meter_id=pid, bands=[band]))

            # 2) flow: match src->dst, apply meter, then forward normally
            match = parser.OFPMatch(eth_type=ETH_TYPE_IP,
                                    ipv4_src=src, ipv4_dst=dst)
            inst = [parser.OFPInstructionMeter(pid),
                    parser.OFPInstructionActions(
                        ofp.OFPIT_APPLY_ACTIONS,
                        [parser.OFPActionOutput(ofp.OFPP_NORMAL)])]
            dp.send_msg(parser.OFPFlowMod(
                datapath=dp, priority=POLICY_PRIORITY, match=match,
                instructions=inst, cookie=pid))

        self.policies[pid] = {"id": pid, "src": src, "dst": dst,
                              "bandwidth_mbps": mbps}
        self.logger.info("policy %s installed: %s -> %s @ %s Mbps",
                         pid, src, dst, mbps)
        self._update_best_effort()

    def remove_policy(self, pid, update=True):
        pol = self.policies.pop(pid, None)
        if pol is None:
            return False
        for dp in self.datapaths.values():
            ofp, parser = dp.ofproto, dp.ofproto_parser
            match = parser.OFPMatch(eth_type=ETH_TYPE_IP,
                                    ipv4_src=pol["src"], ipv4_dst=pol["dst"])
            dp.send_msg(parser.OFPFlowMod(
                datapath=dp, command=ofp.OFPFC_DELETE_STRICT,
                out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY,
                priority=POLICY_PRIORITY, match=match))
            dp.send_msg(parser.OFPMeterMod(
                datapath=dp, command=ofp.OFPMC_DELETE,
                flags=0, meter_id=pid, bands=[]))
        self.logger.info("policy %s removed", pid)
        if update:
            self._update_best_effort()
        return True

    # ------------------------------------------------------------------
    # best-effort limiter: everything unreserved shares what is left over
    # ------------------------------------------------------------------
    def _update_best_effort(self):
        if self.capacity_mbps is None:
            return                              # capacity unknown: do nothing
        if not self.policies:
            if self.be_installed:
                self._remove_best_effort()
            return

        reserved_kbps = sum(int(p["bandwidth_mbps"] * 1000)
                            for p in self.policies.values())
        rate = max(MIN_BE_KBPS, int(self.capacity_mbps * 1000) - reserved_kbps)
        burst = max(100, rate // 10)
        for dp in self.datapaths.values():
            ofp, parser = dp.ofproto, dp.ofproto_parser
            band = parser.OFPMeterBandDrop(rate=rate, burst_size=burst)
            command = ofp.OFPMC_MODIFY if self.be_installed else ofp.OFPMC_ADD
            dp.send_msg(parser.OFPMeterMod(
                datapath=dp, command=command,
                flags=ofp.OFPMF_KBPS | ofp.OFPMF_BURST,
                meter_id=BE_METER_ID, bands=[band]))
            if not self.be_installed:
                match = parser.OFPMatch(eth_type=ETH_TYPE_IP)
                inst = [parser.OFPInstructionMeter(BE_METER_ID),
                        parser.OFPInstructionActions(
                            ofp.OFPIT_APPLY_ACTIONS,
                            [parser.OFPActionOutput(ofp.OFPP_NORMAL)])]
                dp.send_msg(parser.OFPFlowMod(
                    datapath=dp, priority=BE_PRIORITY, match=match,
                    instructions=inst, cookie=BE_METER_ID))
        self.be_installed = True
        self.logger.info("best-effort limiter set to %d kbps", rate)

    def _remove_best_effort(self):
        for dp in self.datapaths.values():
            ofp, parser = dp.ofproto, dp.ofproto_parser
            match = parser.OFPMatch(eth_type=ETH_TYPE_IP)
            dp.send_msg(parser.OFPFlowMod(
                datapath=dp, command=ofp.OFPFC_DELETE_STRICT,
                out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY,
                priority=BE_PRIORITY, match=match))
            dp.send_msg(parser.OFPMeterMod(
                datapath=dp, command=ofp.OFPMC_DELETE,
                flags=0, meter_id=BE_METER_ID, bands=[]))
        self.be_installed = False
        self.logger.info("best-effort limiter removed")


def _json(data, status=200):
    return Response(content_type="application/json", status=status,
                    body=json.dumps(data).encode("utf-8"))


class PolicyRestApi(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(PolicyRestApi, self).__init__(req, link, data, **config)
        self.app = data[APP_NAME]

    @route("policy", "/policy", methods=["POST"])
    def add_policy(self, req, **kwargs):
        try:
            body = json.loads(req.body.decode("utf-8"))
            pid = int(body["id"])
            src, dst = str(body["src"]), str(body["dst"])
            mbps = float(body["bandwidth_mbps"])
            cap = body.get("capacity_mbps")
            cap = float(cap) if cap is not None else None
            if pid <= 0 or mbps <= 0:
                raise ValueError("id and bandwidth_mbps must be positive")
        except (ValueError, KeyError, TypeError) as e:
            return _json({"status": "error", "message": "bad request: %s" % e}, 400)
        try:
            self.app.install_policy(pid, src, dst, mbps, cap)
        except RuntimeError as e:
            return _json({"status": "error", "message": str(e)}, 503)
        return _json({"status": "ok", "id": pid})

    @route("policy", "/policy/{pid}", methods=["DELETE"],
           requirements={"pid": r"[0-9]+"})
    def delete_policy(self, req, pid, **kwargs):
        if self.app.remove_policy(int(pid)):
            return _json({"status": "ok", "id": int(pid)})
        return _json({"status": "error", "message": "no such policy"}, 404)

    @route("policy", "/policy", methods=["GET"])
    def list_policies(self, req, **kwargs):
        return _json({"status": "ok",
                      "policies": list(self.app.policies.values()),
                      "best_effort_limiter": self.app.be_installed})

    @route("policy", "/health", methods=["GET"])
    def health(self, req, **kwargs):
        return _json({"status": "ok",
                      "switches": sorted(self.app.datapaths.keys())})
