# Network Resource Reservation System — Project Report

**Course:** Computer Networks  
**Team:** Kritika Singh (PES2UG25AM135), Jiah Bansal (PES2UG25AM117), Lisha Chowdary (PES2UG25AM144)

> **Before submitting:** This draft uses project details and preliminary results shared so far. Check every value against your actual code, logs, CSV files, graphs, and switch output. Do not claim a test passed unless you have evidence.

## 1. Abstract

Computer networks have limited bandwidth, and multiple users may request bandwidth at the same time. This project develops a TCP-based Network Resource Reservation System. Clients send reservation requests to a server, which checks whether the requested bandwidth is available. A resource manager tracks reservations, detects conflicts, and releases resources when reservations are cancelled or expire. For accepted requests, the application communicates with a Ryu Software-Defined Networking (SDN) controller, which applies supported OpenFlow rules and meters on Open vSwitch switches. Mininet provides a virtual network for testing. Request outcomes and utilization information are recorded for evaluation.

## 2. Objectives

1. Accept bandwidth requests through TCP.
2. Reject requests that exceed the configured capacity.
3. Handle concurrent clients without over-allocating bandwidth.
4. Maintain reservation records and detect conflicts.
5. Install SDN policies for accepted reservations.
6. Release resources and remove policies on cancellation or expiry.
7. Track resource use and accepted/rejected requests.
8. Evaluate the system using test cases in Mininet.

## 3. Topology

The project uses four Mininet hosts connected through two Open vSwitch switches. The link between the switches is configured as a 10 Mbps bottleneck. The reservation server is intended to be reachable at `10.0.0.100`; confirm its exact host/interface mapping in `topo.py`. The server communicates with the Ryu controller through a REST API, and the controller communicates with switches using OpenFlow.

| Element | Configuration to verify |
|---|---|
| Hosts | h1, h2, h3, h4 |
| Example host IPs | h1: `10.0.0.1`, h2: `10.0.0.2`, h3: `10.0.0.3`, h4: `10.0.0.4` |
| Switches | s1 and s2 |
| Bottleneck | s1–s2 link, 10 Mbps |
| Reservation server | Intended `10.0.0.100` |
| TCP port | Intended `5000`; verify in code |
| Ryu REST port | Intended `8080`; verify in code |
| Switch protocol | Intended OpenFlow 1.3; verify in configuration |

**Add evidence:** Include a topology screenshot or diagram and your own Mininet `pingall` output.

## 4. Configuration and implementation

### Components

- **TCP client/server:** Sends reservation requests and returns results.
- **Resource manager:** Checks capacity, stores reservations, detects conflicts, and handles release/expiry.
- **Threads and lock:** Supports concurrent connections and protects the allocation check/update.
- **SDN connector:** Sends policy install/remove requests to the controller REST API.
- **Ryu controller:** Installs or removes supported switch flow rules and meters.
- **Mininet:** Emulates hosts, switches, and the bottleneck link.
- **Evaluation scripts:** Record workload outcomes, utilization, and throughput.

### Protocols and tools

| Technology | Purpose |
|---|---|
| TCP sockets | Reliable, ordered request/response communication |
| JSON | Structured request and response messages |
| Python threads/lock | Concurrent clients and safe allocation updates |
| Mininet | Repeatable virtual network |
| Open vSwitch/OpenFlow | Switch-level policy enforcement |
| Ryu/REST API | Connects application decisions to SDN policies |
| CSV/graphs | Stores and summarizes evaluation results |

### Reservation flow

1. Client sends a TCP request.
2. Server validates it.
3. Resource manager checks capacity and conflicts.
4. The application asks Ryu to install a policy.
5. The reservation is confirmed only if policy installation succeeds.
6. On release or expiry, the allocation is freed and its policy removed.

### Configuration record

Fill these using your actual VM and README before submission:

| Setting | Value |
|---|---|
| VM/OS | [Fill in] |
| Python version | [Fill in] |
| Mininet/Open vSwitch/Ryu versions | [Fill in] |
| Link capacity | 10 Mbps; verify `topo.py` |
| TCP server IP/port | Intended `10.0.0.100:5000`; verify code |
| Controller REST port | Intended `8080`; verify code |
| OpenFlow version | Intended 1.3; verify configuration |
| Exact startup commands | Copy from your README |

## 5. Test cases and results/comments

| ID | Test | Expected result | Current evidence/status | Comment/action |
|---|---|---|---|---|
| T1 | Valid request | Accepted, allocation stored, policy installed | Integration reported; verify with live output | Save client response and flow/meter output |
| T2 | Over-capacity request | Rejected; total stays within 10 Mbps | Capacity/conflict logic reported; verify output | Save request and rejection response |
| T3 | Concurrent requests | No over-allocation | Peak 9.7/10 Mbps reported in a burst test | Check CSV/log and save evidence |
| T4 | Expiry | Allocation freed and policy removed | Rule removal reported | Capture switch output before/after expiry |
| T5 | Explicit release | Allocation and policy removed | Must be verified in current run | Save response and before/after switch output |
| T6 | Controller unavailable | No false success; policy failure returned | Expected by design; test before marking passed | Save error response and server log |
| T7 | Load test | Counts/utilization recorded | Load test reported; verify actual files | Check workload CSV and summary |
| T8 | Baseline vs reserved traffic | Throughput measured and compared | Reported 1.90 vs 3.57 Mbps, UDP, three runs | Verify raw CSV and graph |
| T9 | Unit tests | Automated tests pass | 22 tests reported as passing | Re-run and save terminal output |
| T10 | Mininet connectivity | `pingall` succeeds | 0% packet loss reported | Re-run and save output |

### Preliminary results reported

- 22 automated tests passed (reported in the project progress summary).
- Concurrent test peak: 9.7 Mbps reserved out of 10 Mbps (reported).
- One overload run: 11 of 30 requests accepted (reported; verify the corresponding CSV/log).
- UDP throughput comparison: 1.90 Mbps without reservation and 3.57 Mbps with reservation, over three runs in the described scenario (reported).
- Associated rules were reportedly removed after expiry; include actual before/after switch evidence.

**Comments:** Results are preliminary and apply only to the tested scenarios. A meter caps matching traffic; by itself it does not guarantee a minimum bandwidth rate. The outcome depends on the flow rules, competing traffic, queue configuration, and link settings. Keep actual CSVs, graphs, and terminal output with the report.

## 6. Limitations

1. The reported traffic comparison covers UDP, three runs, and one scenario.
2. Results may change with traffic patterns, queue settings, and configuration.
3. OpenFlow meters do not by themselves guarantee a minimum rate.
4. Only mark a test as passed when you have its actual output or log.
5. Confirm the exact host mapping, versions, ports, and commands from the repository.

## 7. GitHub submission checklist

- Source code and configuration files.
- `README.md` with setup and run instructions.
- `docs/REPORT.md`, `docs/DEMO.md`, and `docs/TEST_CASES.md`.
- Actual CSV logs and graphs.
- Screenshots from your own Mininet run: connectivity, accepted request, rejected request, switch rules/meters, and expiry cleanup.
- Optional recording link, if you actually make a recording and the instructor allows it.

After pushing, open the GitHub repository and check that all files, images, and links work and that your instructor has access.
