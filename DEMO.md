# Mininet Demo Checklist

This is a checklist for carrying out and recording the demo; it is not proof that the demo has already run. Use the exact launch and client commands from your repository's `README.md`, because filenames and arguments can differ.

## 1. Start the controller
Run the Ryu startup command documented in your README. Keep the terminal open and confirm there are no startup errors. Save a screenshot of the terminal.

## 2. Start Mininet
Run the documented topology command. At the Mininet prompt, run:

```text
pingall
```

Save the output. If your README gives a topology-inspection command, run it and capture that output too.

## 3. Start the reservation server
Run the documented server command. Confirm it is listening on the configured address and port. Save a screenshot.

## 4. Test a valid reservation
Use the real client command and message format from your README/code. Request an amount that fits the available capacity.

**Expected:** accepted response and a recorded reservation. Save the client response and server log.

## 5. Test an over-capacity request
Make a request that exceeds the remaining capacity.

**Expected:** rejected response and no over-allocation. Save the response and log.

## 6. Inspect switch policy
Use the switch names and OpenFlow options configured in your project. These common commands may work if your switches are named `s1` and `s2` and use OpenFlow 1.3:

```bash
sudo ovs-ofctl -O OpenFlow13 dump-flows s1
sudo ovs-ofctl -O OpenFlow13 dump-flows s2
sudo ovs-ofctl -O OpenFlow13 meter-stats s1
sudo ovs-ofctl -O OpenFlow13 meter-stats s2
```

Save the output after accepting a reservation.

## 7. Show release or expiry
Use the actual release command, or make a short-duration reservation and wait for expiry.

**Expected:** the resource is freed and its associated switch policy is removed. Capture switch output before and after release/expiry.

## 8. Run evaluation scripts
The project notes mention `workload.py`, `summarize.py`, and `make_graphs.py`. Check the README or each script's help before running them; use the exact commands documented in your repository. Save terminal output, CSVs, and graphs.

## Evidence checklist

- [ ] Controller started
- [ ] Mininet topology started
- [ ] `pingall` output saved
- [ ] Server started
- [ ] Accepted request captured
- [ ] Rejected over-capacity request captured
- [ ] Flow/meter output captured before expiry
- [ ] Flow/meter output captured after expiry
- [ ] Evaluation output, CSVs, and graphs saved
- [ ] Report and test statuses updated to match the real evidence

Suggested screenshot names: `01_controller_started.png`, `02_mininet_pingall.png`, `03_server_started.png`, `04_request_accepted.png`, `05_request_rejected.png`, `06_policy_before_expiry.png`, `07_policy_after_expiry.png`, `08_evaluation_results.png`.

Do not use sample or old screenshots as if they came from the current run.
