> Retained engineering background from the supplied source reference. Version-specific test totals, hardware observations, deployment steps, and linked records are historical; some referenced files were not supplied. For this public copy, start with [the repository README](../../README.md) and [source status](../../SOURCE-STATUS.md).

# Historical code retirement

The supplied ZIP is preserved byte-for-byte. Its extracted System repository is retained privately as repository-snapshot beside the clean release. Original evidence and synced documents were not changed.

| Original path | Treatment in final release | Reason |
| --- | --- | --- |
| Software/gateway/app.py and serial tests | Replaced by gateway/ modules and new final-workflow tests | Monolithic SerialBridge, no student source stages |
| Software/gateway/operator_token.py | Credential validation contract reused for distinct roles and device key | Sound format check; no reuse of a shared authority credential |
| Software/gateway/templates/display.html | Read-only display separation retained; presentation replaced | Remove vehicle/steering/track claims from the LED experiment |
| Software/gateway/deploy | Unprivileged hardening approach retained in new service/installer | Remove dialout and retired serial configuration |
| Software/serial-chokepoint | Historical only; excluded from active bundle | Hub and USB serial chokepoint retired |
| Software/vehicle | Historical only; excluded from active bundle | ESP-NOW, PID/motors and historical pin assumptions |
| Software/observability-ebpf | Historical supporting source; not enabled | Serial-specific tracing is not final Wi-Fi evidence |
| Software/anomaly-detection | Historical supporting source; not enabled or deleted | Requires separate final-data/provenance evaluation |
| Software/Simulator/Simulator.html | Historical simulator retained in original archive | Does not implement this final Wi-Fi source workflow |
| Infrastructure/network private notes | Retained privately; not distributed | Private identifiers and historical configuration |
| Existing actions/data/evidence | Preserved in original archive and snapshot | No reclassification or replacement by home test evidence |

The original working tree also lacks several tracked Tools/lab_validation files and has a relocated simulator. These pre-existing differences are documented in the audit and were not silently restored.

Do not run the old installer or firmware as an alternative final transport. If an old service is present on the Pi, preserve its evidence and retire that service explicitly under instructor control before deploying this separate service. No old source was deleted, renamed or committed by this task.
