r"""
topology/topo.py
----------------
Mininet topology for the Network Resource Reservation System.

        h1 (10.0.0.1)                          h3 (10.0.0.3)
                      \                       /
                       s1 ===== 10 Mbps ===== s2
                      /   (bottleneck link)   \
        h2 (10.0.0.2)                          h4 (10.0.0.4)
                       |
                  "root" (10.0.0.100)  <- the reservation server runs here,
                                          in the VM's normal network, so it
                                          can also reach the SDN controller.

Run (from the project folder, with sudo, system python, NO venv):
    sudo python3 topology/topo.py
Start the controller FIRST (in another terminal).
"""

import argparse

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import setLogLevel, info
from mininet.net import Mininet
from mininet.node import Node, RemoteController, OVSSwitch


def connect_to_root(net, switch, ip, prefix="/24"):
    """Attach the VM's own network namespace to a switch (so the server can
    run on the VM and still be reachable from every Mininet host)."""
    root = Node("root", inNamespace=False)
    link = net.addLink(root, switch)
    root.setIP(ip, intf=link.intf1)   # prefix length defaults to /8 in Mininet
    root.cmd("ifconfig %s %s netmask 255.255.255.0" % (link.intf1, ip))
    return root


def build(bottleneck_mbps=10, controller_ip="127.0.0.1", controller_port=6653):
    net = Mininet(controller=None, switch=OVSSwitch, link=TCLink,
                  autoSetMacs=True)
    net.addController("c0", controller=RemoteController,
                      ip=controller_ip, port=controller_port,
                      protocols="OpenFlow13")

    s1 = net.addSwitch("s1", protocols="OpenFlow13")
    s2 = net.addSwitch("s2", protocols="OpenFlow13")

    h1 = net.addHost("h1", ip="10.0.0.1/24")
    h2 = net.addHost("h2", ip="10.0.0.2/24")
    h3 = net.addHost("h3", ip="10.0.0.3/24")
    h4 = net.addHost("h4", ip="10.0.0.4/24")

    # access links: fast, so the ONLY bottleneck is s1-s2
    for h, s in ((h1, s1), (h2, s1), (h3, s2), (h4, s2)):
        net.addLink(h, s, bw=100)
    net.addLink(s1, s2, bw=bottleneck_mbps)       # the reservable link

    connect_to_root(net, s1, "10.0.0.100")
    return net


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bottleneck", type=float, default=10,
                   help="bottleneck link capacity in Mbps (default 10)")
    p.add_argument("--controller-ip", default="127.0.0.1")
    p.add_argument("--controller-port", type=int, default=6653)
    a = p.parse_args()

    setLogLevel("info")
    net = build(a.bottleneck, a.controller_ip, a.controller_port)
    net.start()
    info("*** Topology ready. Server (run on the VM) should listen on "
         "10.0.0.100:5000\n")
    CLI(net)
    net.stop()


if __name__ == "__main__":
    main()
