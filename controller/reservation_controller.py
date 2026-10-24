"""
controller/reservation_controller.py
------------------------------------
Ryu SDN controller = a normal learning switch (from Ryu's simple_switch_13)
PLUS a small REST API that the reservation server calls to install and
remove bandwidth policies.

REST API (listens on http://127.0.0.1:8080):
  POST   /policy      body: {"id": 1, "src": "10.0.0.1", "dst": "10.0.0.3",
                             "bandwidth_mbps": 4}
  DELETE /policy/1
  GET    /policy      -> list of installed policies
  GET    /health      -> {"status": "ok", "switches": [1, 2]}

What a policy is on the switch (OpenFlow 1.3):
  * a METER   : drops packets that go above the reserved rate
  * a FLOW    : matches IPv4 src -> dst, sends packets through that meter,
                then forwards them like a normal switch (OUTPUT:NORMAL)
  The flow has priority 100, higher than the learning-switch flows
  (priority 1), so it wins for the reserved host pair.

Run (venv-ryu active):  ryu-manager controller/reservation_controller.py
"""

import json

from ryu.app import simple_switch_13
from ryu.app.wsgi import ControllerBase, WSGIApplication, route
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from webob import Response

POLICY_PRIORITY = 100
ETH_TYPE_IP = 0x0800
APP_NAME = "reservation_api_app"


class ReservationController(simple_switch_13.SimpleSwitch13):
    _CONTEXTS = {"wsgi": WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(ReservationController, self).__init__(*args, **kwargs)
        self.datapaths = {}        # dpid -> datapath (connected switches)
        self.policies = {}         # policy id -> dict
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
    # install / remove a policy on every connected switch
    # ------------------------------------------------------------------
    def install_policy(self, pid, src, dst, mbps):
        if pid in self.policies:               # same id again: replace it
            self.remove_policy(pid)
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

    def remove_policy(self, pid):
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
        return True


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
            if pid <= 0 or mbps <= 0:
                raise ValueError("id and bandwidth_mbps must be positive")
        except (ValueError, KeyError, TypeError) as e:
            return _json({"status": "error", "message": "bad request: %s" % e}, 400)
        try:
            self.app.install_policy(pid, src, dst, mbps)
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
                      "policies": list(self.app.policies.values())})

    @route("policy", "/health", methods=["GET"])
    def health(self, req, **kwargs):
        return _json({"status": "ok",
                      "switches": sorted(self.app.datapaths.keys())})

