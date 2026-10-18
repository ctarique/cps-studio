> Retained engineering background from the supplied source reference. Version-specific test totals, hardware observations, deployment steps, and linked records are historical; some referenced files were not supplied. For this public copy, start with [the repository README](../../README.md) and [source status](../../SOURCE-STATUS.md).

# Next lab session

> Historical planning notice, 23 September 2026: the sequence below records the earlier Core 1.0.1 handoff, including then-pending diagnostics and its older approval flow/VAL mapping. It is not an instruction to replace firmware or reinstall the later captured Pi. For candidate 1.0.4, use [SUCCESSOR.md](SUCCESSOR.md), the reconciled thesis requirements and the current Validation and Evidence Matrix in the enclosing successor package. Preserve earlier failed attempts; later deployment and researcher observations remain separate evidence contexts.

The Master chat reports failed Wi-Fi attempts VAL02-R01/R02, a flash backup, and diagnostic firmware already installed with output still pending. This task did not independently verify those prior lab results.

1. Capture the pending diagnostic output before replacing firmware. Determine AP visibility and the actual association/disconnect result. The new application is not a confirmed fix for association.
2. Preserve R01/R02 and use the next unused lab attempt ID. The ZIP lacks files explicitly named for both attempts; reconcile them with the Master attachments and private lab records.
3. Keep the existing AP, instructor SSH path, default-deny policy and disabled forwarding. Diagnose the observed Wi-Fi failure.
4. After preserving diagnostics and backup, bootstrap trusted firmware under instructor control. Confirm its private lease, /health and signed status. Repeat with independent ESP32 power.
5. Install the Pi release in simulator mode, verify browser/TLS access, then switch explicitly to Wi-Fi with a new configuration reference.
6. Run source submission, preparation, instructor approval, execution and status. Observe the selected onboard white LED directly. Include denied roles, malformed source, unapproved execution and unavailable transport.
7. Exercise stop/reset/recovery. A reported stop is not proof that the LED stopped.
8. Connect Pi HDMI to the TV. Inspect the local display and record input, resolution, scaling and observation.
9. Export the run record. Keep raw observations privately and map their hashes and lab attempt IDs to the Gateway run ID using the lab-index template.

| Target | Evidence required |
| --- | --- |
| VAL-01 | Role/configuration records; accepted and rejected workflows |
| VAL-02 | Wi-Fi exchange, device report, recovery and relevant direct observations |
| VAL-03 | HDMI presentation, settings and observation |
| VAL-04 | Ordered run records, provenance and missing evidence classes |
| VAL-05 | Separate supporting evaluation; not enabled by this core release |

Record PASS, PARTIAL, FAIL or INCOMPLETE only after reviewing the required evidence. All hardware-dependent results remain unvalidated here. Observation references alone do not establish a physical result. Do not update Chapters 4/5 solely from software test results.
