> Retained engineering background from the supplied source reference. Version-specific test totals, hardware observations, deployment steps, and linked records are historical; some referenced files were not supplied. For this public copy, start with [the repository README](../../README.md) and [source status](../../SOURCE-STATUS.md).

# Sentinel-CPS Core 1.0.1 handoff

> Retained historical record: all release identities, test totals, approval-flow instructions and deployment statements below belong to the 7 September Core 1.0.1 handoff. They are not candidate 1.0.4 results. See [SUCCESSOR.md](SUCCESSOR.md) for current behavior, verification and upgrade guidance. The body of this earlier record is preserved.

Date: 2026-09-07.

The current Core package has been audited and corrected for the final Gateway/one-ESP32/private-Wi-Fi/direct-HDMI architecture. All 79 Python tests and the native C++ checks pass. AI Thinker ESP32-CAM firmware compilation passes. **Pi deployment, Wi-Fi operation, HDMI and physical LED behavior remain unvalidated.**

## Delivered files and preservation

Use Sentinel-CPS-Core-1.0.1.zip and its adjacent SHA-256 file. The ZIP contains one sentinel-cps-final directory with the Gateway, trusted firmware source, simulator, tests, configuration templates, offline Pi dependencies and instructions.

The supplied thesis ZIP, extracted historical repository, synced source documents, initial Core ZIP and earlier verification records were preserved. No commit, push, service installation, firewall change, firmware upload or manuscript edit was performed.

The audited input was Core 1.0.0, verified against all 67 entries in its manifest before changes. This is a standalone package, not a Git checkout. The historical System repository's HEAD is recorded in audit/AUDIT.md; it is not the identity of this new release.

## Files changed from Core 1.0.0

| Files | Change |
| --- | --- |
| gateway/app.py | Historical evidence reads; instructor reads during logging failure; observation credential rejection; reported-run correlation; accurate rejected-workflow labels; dispatch/recovery/failure display state |
| gateway/config.py | Configuration reference also binds timeout and storage quotas |
| gateway/protocol.py, gateway/transport.py | Reject contradictory signed status, inconsistent RUN results and exhausted sequences |
| gateway/simulator.py | Bound the whole HTTP request; reject ambiguous framing; recover after incomplete requests; match firmware sequence limit |
| esp32/sentinel_esp32/sentinel_esp32.ino; new response.h | Fixed response buffer and a single nonblocking send, including errors and health; no response retries inside the execution loop |
| tests/test_gateway.py, tests/test_transport.py, tests/firmware_core.cpp; new tests/test_packaging.py | Necessary regressions for the audit findings |
| tools/package.py, tools/verify_bundle.py; new tools/release_policy.py | Exclude private state, reject provisioned templates, enforce release file rules, reject symlink paths, preserve archive outputs |
| tools/build_firmware.py, tools/home.py | Fresh private build outputs and private home credential creation; preserve prior attempts |
| deploy/install.sh; new tools/install_preflight.py | Refuse existing final configuration, evidence, release, unit, account or group before fresh installation |
| README.md, VERSION, docs/HOME.md, docs/DEPLOYMENT.md, docs/PROTOCOL.md | Release 1.0.1, exact simulator commands, corrected behavior and installation limits |
| audit/CORE-AUDIT.md, audit/requirement-coverage.csv, audit/core-audit-baseline.json, audit/core-manifest-before.json | Current audit, 84-row traceability and preserved audit input |
| verification/RESULTS.md and new SW-R04/FW-R03/regression/package records | Final source-bound results; earlier failures and passes remain distinguishable |
| docs/HANDOFF.md, MANIFEST.json | This handoff and the final release integrity manifest |

No historical implementation or evidence file was deleted. audit/changed-files.json gives the complete release-file hash comparison.

## Architecture decisions

1. **Gateway mediation and roles.** Students submit, prepare and execute approved LED/status work. The instructor reviews/approves work, manages recovery and reviews evidence. Configuration is an instructor OS task. Credentials are distinct for the student cohort, instructor and device; display access has no authority.
2. **Bounded interaction preparation.** The permitted source is one C++-style experiment() function containing led(0/1), wait_ms(10–1000) and status calls. Limits: 2048 ASCII bytes, 32 calls, 5000 ms of waits, final LED call off. Preparation creates bounded bytecode, not a firmware binary. Firmware independently checks it and accepts one running program. This uses the requirements' permitted interaction-work-item path; arbitrary C++, general OTA and student firmware administration are excluded.
3. **Trusted ESP32 firmware.** The board profile selects the AI Thinker ESP32-CAM's GPIO4 white flash LED, active high. Camera/SD features are unused. Generic configuration disables GPIO. Empty credentials refuse startup. USB is only an instructor bootstrap/diagnostic option, never a Hub runtime path.
4. **Explicit transport selection.** In-process simulator and loopback HTTP simulator are nonphysical modes. Real transport checks the configured Linux wireless route and uses a fixed private ESP32 endpoint. There is no automatic fallback. Signed messages bind status nonces and command results; boot/sequence checks reject replay.
5. **Visible failure and recovery.** Startup is locked. Approval is invalidated at restart; interrupted communication becomes INCOMPLETE. Dispatch intent is committed before external action. A missing POST response is uncertain and is never automatically retried. Stop requests lock the Gateway. A reported stop or local unlock is not a physical conclusion.
6. **Evidence boundaries.** Submission, authorization, preparation, transport, device reports, recovery and observation references remain distinct. Simulation never becomes Wi-Fi evidence. Historical evidence stays readable across configuration changes. Readable records remain available to authenticated instructors when logging fails, labeled audit_logging=UNAVAILABLE and workflow_locked=true; actions remain blocked.
7. **Scope.** The display is Pi-local output for direct HDMI. No Hub, ESP-NOW, Pi-to-Hub serial dependency, TV network service, live model control or additional experiment was added. Optional supporting eBPF/monitoring/Isolation Forest work stays disabled.

## Requirement coverage

The authoritative comparison covers **36 functional and 48 security requirements**:

| Status in this release | Count | Meaning |
| --- | ---: | --- |
| Implemented for the bounded LED/status workflow | 57 | Code and relevant software checks exist; deployment/physical clauses still need lab evidence |
| Configuration or lab procedure only | 8 | Pi permissions/network policy or HDMI/observation duties are specified but not executed here |
| Conditional supporting capability not enabled | 19 | No supporting monitoring/model evaluation is claimed |

These are coverage classifications, not 84 PASS results. audit/requirement-coverage.csv retains the exact requirement text, implementation reference, software evidence, remaining work and UNVALIDATED physical status for every row. audit/CORE-AUDIT.md records the twelve findings and corrections. The earlier generic requirements-after.csv is retained as historical implementation assessment.

## Test and build results

| Attempt/check | Result |
| --- | --- |
| SW-R04, full Python suite | 79 passed in 13.734 seconds: 38 Gateway, 22 transport/simulator, 15 packaging/deployment, 4 source tests |
| Native C++ engine/response checks | Passed with warnings treated as errors |
| FW-R03, esp32:esp32:esp32cam | Compiled: 939136 bytes program, 49264 bytes globals |
| Toolchain | Arduino CLI 1.5.1, Espressif Arduino core 3.3.7 |
| FW-R03 profile | GPIO4 white LED; blank credentials; no upload |
| Home/HTTP launchers | Both started successfully; Waitress-to-HTTP-fixture status passed; all test servers stopped |
| Archive | SHA-256 manifest and reproducibility checks recorded separately |

Added tests first reproduced the defects against unchanged implementation: Gateway had nine failures and one error, transport had eight failures and one error, and the nine initial packaging regressions failed. The subsequent focused checks and complete suite passed. Raw first outputs remain private; published copies replace local path prefixes and record both original and published hashes.

The source did not change during SW-R04. Source hashes and complete outputs are under verification/. Earlier SW-R01–R03 and FW-R01–R02 remain identifiable. Native tests exercise the shared parser/engine and response helper; the HTTP fixture does not execute the ESP32 networking stack.

## Exact home run instructions

Run these from the unpacked sentinel-cps-final directory on macOS or Linux, with Python 3.11+ and a C++ compiler. The initial home dependency install needs Internet access.

```sh
python3 tools/verify_bundle.py
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python tools/test.py
.venv/bin/python tools/home.py
```

Open http://127.0.0.1:8080 and http://127.0.0.1:8080/admin in separate tabs. Read .local/home.env privately for the matching credentials. Submit → prepare → instructor review/approve → instructor unlock → student run/status/stop → instructor evidence download. Select the same run ID on both pages. Ctrl-C stops the home service. Retain .local/evidence.

For the network fixture, stop the home service and follow the exact two-terminal commands in HOME.md. They reuse the private fixture credentials, run the HTTP simulator on loopback 8090 and the Gateway on 8080, and keep separate history in .local/http-evidence.

To reproduce the source/deployment ZIP after review, choose unused output names outside the release:

```sh
.venv/bin/python tools/package.py --output ../Sentinel-CPS-Core-rebuild-A.zip
.venv/bin/python tools/package.py --output ../Sentinel-CPS-Core-rebuild-B.zip
cmp ../Sentinel-CPS-Core-rebuild-A.zip ../Sentinel-CPS-Core-rebuild-B.zip
python3 tools/verify_bundle.py
```

The manifest provides integrity checking, not a publisher signature. Local state and virtual environments are excluded. Provisioned configuration must remain outside the release; packaging refuses modified private templates.

## Exact firmware build instructions

Use the recorded toolchain. Create a new private directory outside the unpacked release:

```sh
mkdir -m 700 ../sentinel-private
cp config/ai-thinker-esp32cam-led.example.h ../sentinel-private/sentinel_config.local.h
chmod 600 ../sentinel-private/sentinel_config.local.h
```

Edit that private header with the instructor's existing AP SSID/PSK, Pi private Wi-Fi address and device key. For compile-only work, leave credentials blank. Do not put browser credentials in the device header.

```sh
python3 tools/build_firmware.py --board esp32cam \
  --private-config ../sentinel-private/sentinel_config.local.h \
  --output ../sentinel-private/FW-R04
```

Choose the next unused local build-attempt directory on reruns. The helper refuses existing output and creates the new directory mode 0700. It never uploads. Provisioned binaries and compiler logs remain private. Preserve the pending diagnostic output and flash backup before instructor-led firmware replacement.

## Exact Pi installation/run instructions

Use a fresh final-installation target on 64-bit Raspberry Pi OS, Python 3.11 or 3.13, python3-venv/ensurepip, systemd and iproute2. The supplied wheelhouse supports those two ARM64 Python ABIs. OS provisioning and the Arduino toolchain are not bundled.

From the unpacked release on the Pi:

```sh
python3 tools/verify_bundle.py
sudo sh deploy/install.sh
systemctl is-active sentinel-cps-final
curl --fail http://127.0.0.1:8080/api/health
```

The service starts locked in SIMULATOR mode on loopback. It uses /opt/sentinel-cps-final/releases/1.0.1; private config is /etc/sentinel-cps-final; evidence is /var/lib/sentinel-cps-final. The installer refuses existing final state and does not implement upgrades or transactional rollback.

Follow DEPLOYMENT.md to configure the optional lab-trusted TLS proxy and gateway.lab.example. Preserve approved SSH, default-deny ingress/forwarding and the existing private AP. Do not expose the service publicly or give students Pi shell/device access.

After association is diagnosed and the ESP32 lease confirmed, place the private Wi-Fi configuration in /etc/sentinel-cps-final/gateway.json with the matching device key, wireless interface and a new LAB-CONFIG reference. Then:

```sh
sudo systemctl restart sentinel-cps-final
curl --fail http://127.0.0.1:8080/api/health
```

Confirm mode wifi. Use instructor reset/status/unlock before a new attempt. The transport must reject a wrong interface, endpoint, signature or device origin; it must not switch to simulation.

For HDMI, connect the Pi directly to the TV and open http://127.0.0.1:8080/display in the Pi's local browser. Record the actual HDMI input, resolution/scaling, run and observation.

## Unresolved issues and required lab work

- The Master reports failed VAL02-R01/R02 association attempts and pending diagnostic output. This release does not establish their cause or fix. Capture those diagnostics before replacing firmware, preserve the backup/hash, and reconcile raw first-attempt records absent under those names in the supplied ZIP.
- Validate Pi service privileges, private file permissions, TLS, permitted/denied roles, listeners, firewall rules and student isolation (VAL-01).
- Validate actual Wi-Fi association, fixed endpoint/route, signed status/interaction, independent ESP32 power, unavailable/wrong-key cases and no fallback (VAL-02).
- Directly observe the selected white LED and measure completion/stop behavior, including connection loss and incomplete requests. Firmware compilation and device-reported LED state do not provide that evidence.
- Validate Pi-to-TV HDMI presentation and record its settings/conditions (VAL-03).
- Correlate Gateway UUID, lab attempt ID, configuration, clock, separate evidence classes and private original observations (VAL-04). A hash attachment remains unverified.
- Storage exhaustion deliberately blocks actions. Instructor reads remain available only while the database is readable. Back up consistently using SQLite backup or a stopped service; preserve earlier stores before repairing storage and restarting.
- Existing final installations require a reviewed manual migration. The fresh installer can leave a partial new installation on failure; it does not overwrite or repair existing state.
- Cohort credentials do not prove individual identity. The ledger is not tamper-proof against an OS administrator. The device key is not protected from physical extraction, and HTTP authentication does not add application-layer encryption.
- Supporting VAL-05 evaluation is not enabled or assessed by this release. No thesis validation status or physical PASS claim was changed.

Follow LAB.md and the lab-index template for the next unused lab attempt. Preserve negative, partial and incomplete results alongside later outcomes.
