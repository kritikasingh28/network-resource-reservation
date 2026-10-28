# Test Cases — Network Resource Reservation System

Update statuses only after checking the current code and real output.

| ID | Test | Expected result | Current status/evidence | Save this evidence |
|---|---|---|---|---|
| T1 | Valid reservation | Accepted; allocation and switch policy exist | Integration reported; verify live run | Client response + flow/meter dump |
| T2 | Over-capacity request | Rejected; total stays within 10 Mbps | Logic reported; verify output | Rejection response + server log |
| T3 | Concurrent clients | No over-allocation | 9.7/10 Mbps reported; verify CSV/log | Workload CSV/log |
| T4 | Expiry | Allocation freed and policy removed | Reported; capture current run evidence | Before/after flow/meter output |
| T5 | Explicit release | Allocation and policy removed | Verify in current run | Response + before/after switch output |
| T6 | Controller unavailable | No false success; policy failure returned | Not confirmed; test it | Error response + server log |
| T7 | Load test | Accepted/rejected counts and utilization recorded | Reported; verify files | CSV + summary output |
| T8 | Baseline vs reserved UDP traffic | Throughput compared | 1.90 vs 3.57 Mbps reported; verify raw data | CSV + graph |
| T9 | Unit tests | Automated tests pass | 22 passing reported; rerun | Test terminal output |
| T10 | Mininet connectivity | `pingall` succeeds | 0% loss reported; rerun | `pingall` output |

“Reported” means the project summary says it was observed. It does not replace checking the actual log or repeating the test in your VM.
