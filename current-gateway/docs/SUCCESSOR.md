> Retained engineering background from the supplied source reference. Version-specific test totals, hardware observations, deployment steps, and linked records are historical; some referenced files were not supplied. For this public copy, start with [the repository README](../../README.md) and [source status](../../SOURCE-STATUS.md).

# CPS Studio 1.0.7 successor notes

1.0.4 successor work: 23 September 2026. 1.0.5 maintenance correction: 1 October 2026. 1.0.6 display and telemetry successor: 2 October 2026. 1.0.7 CPS Studio final-release work: 6 October 2026.

Status: the 1.0.7 source passes 147/147 Python tests and both native host firmware-engine checks. Live development-hardware smoke testing has been completed. Production deployment acceptance remains a separate step until the preserved 1.0.6 production service is deliberately upgraded and the running 1.0.7 process is verified.

Version 1.0.7 succeeds the preserved deployed 1.0.6 baseline. Historical releases, private configuration, prior evidence and physical observations remain attached to the release and operating context in which they were recorded and are not automatically relabeled as 1.0.7 evidence.

## 1.0.7 CPS Studio final release

Version 1.0.7 succeeds the preserved deployed 1.0.6 baseline. CPS Studio is the user-facing identity of Sentinel-CPS; internal service names, environment variables, release paths and protocol identifiers retain their existing Sentinel-CPS naming for compatibility and historical continuity.

The release completes the current browser, Lab Display and Digital Twin presentation work and integrates the ESP32-WROVER Autonomous Car through the Raspberry Pi Gateway. Ordinary users continue to interact through Gateway-mediated browser workflows rather than direct Raspberry Pi administration or direct browser connections to CPS device addresses.

The Autonomous Car path provides authenticated status, LDR telemetry, vehicle RSSI, authenticated OV2640 image capture and bounded fixed motor actions. MTR A and MTR B expose only the approved clockwise/counter-clockwise semantic operations. Firmware fixes the motor pin mapping and bounds each motor action to 120 ms; arbitrary GPIO and arbitrary duration are not exposed.

Single-frame and three-frame camera captures may be retained temporarily in the Gateway's in-memory Gallery. Gallery entries are scoped to the workstation context, bounded to twelve recent captures and expire with the temporary session/cache. They are operational images, not formal physical-observation evidence.

The Digital Twin presents Gateway-mediated LED and vehicle information, including fresh authenticated connectivity, LED report, LDR readings, vehicle RSSI, motor activity and camera activity. Browser display polling does not connect directly to the ESP32 devices. Dedicated Gateway workers perform authenticated read-only device status/telemetry collection and retain only bounded sanitized current reports for presentation.

Connection indicators mean current fresh authenticated application-level Gateway-to-device communication and reachability. They do not establish physical behavior. Device-reported state, Gateway-command state and direct physical observation remain separate evidence classes.

The 1.0.7 source passes 147/147 Python tests. The canonical `tools/test.py` check additionally passes the native ESP32-CAM firmware parser/engine/response checks and the Autonomous Car motor-engine checks for fixed pins, the 120 ms bound, stopping behavior, exclusivity and clock-wrap behavior.

Researcher-performed live hardware smoke testing of the 1.0.7 development build has exercised the ESP32-CAM, Autonomous Car controls and capture path, Gallery, Digital Twin and Lab Display. Production deployment acceptance remains separate until the preserved 1.0.6 production release is deliberately replaced through the staged upgrade procedure and the running process is verified.

Known platform behavior: reassociation of the ESP32-CAM can intermittently trigger a BCM43455/brcmfmac firmware restart on the Raspberry Pi 4 access point. The AP automatically recovers and connected devices reassociate. CPS Studio reflects the temporary communication loss through its connectivity indicators. This occurs below the CPS Studio application layer.

## Historical 1.0.6 display and Digital Twin successor


Version 1.0.6 completes the current Lab Display and Digital Twin presentation work. Lab View and Digital Twin remain browser presentation surfaces mediated by the Raspberry Pi Gateway; ordinary users are not given direct administrative access to the Pi or direct browser access to CPS device addresses.

The ESP32-CAM Digital Twin now has a read-only device-telemetry path. After the Gateway has already received and authenticated a CAM device response through the existing SCPS1 transport, it retains only a sanitized in-memory report for display use. The display endpoint exposes current LED report, GPIO capability and freshness metadata without credentials, routing details, boot nonce, sequence state, program digest or run identifier.

The Digital Twin does not independently poll the ESP32-CAM. Its display GET therefore does not compete with a device command or bypass the Gateway's normal operation locking. A cached report expires after eight seconds. A stale, missing, unavailable or unauthenticated report produces an unknown/neutral Twin state rather than an inferred physical condition.

The Digital Twin bulb illuminates only when the read-only endpoint supplies a fresh authenticated `led_reported=1` report. A fresh authenticated `led_reported=0` report presents LED off. These remain device reports rather than direct physical observations.

The Autonomous Car Digital Twin and track presentation remain presentation-only in this release. CAR-01 physical motor control, vehicle sensing and final Gateway control integration are unfinished and are not claimed by the 1.0.6 CAM telemetry work.

No ESP32 firmware source or SCPS1 wire field changes are introduced by 1.0.6.

## 1.0.5 maintenance correction

Version 1.0.5 separates the Gateway's administrative lock state from physical target readiness. An authenticated instructor UNLOCK invalidates pending prepared authority and changes the Gateway to unlocked without issuing a STATUS request to the ESP32. This administrative transition does not establish target readiness, default physical state or successful communication.

Before Guided ON or Custom Run can cause physical work, the existing execution path still requires fresh authenticated target readiness. Missing, stale, inconsistent or unavailable target state therefore blocks physical execution even when the Gateway is administratively unlocked. LOCK_STOP and RESET remain device-facing recovery actions.

Software regression coverage includes two new cases: UNLOCK succeeds without a device STATUS exchange, and an unlocked Gateway still refuses physical execution when target transport is unavailable.

## Current scope and workflow

The Gateway mediates bounded LED/status operations to the trusted ESP32-CAM and bounded authenticated Autonomous Car operations to the ESP32-WROVER over explicitly selected private Wi-Fi. In-process and loopback HTTP simulators remain separate nonphysical modes; communication failure never selects simulation automatically. The TV receives the Pi's local display over HDMI and has no network control role. Autonomous Car support includes authenticated status, LDR telemetry, RSSI, camera capture and fixed 120 ms motor actions; autonomous course-following behavior is not claimed. Optional eBPF and offline model analysis are outside the active control path.

An admitted workstation browser can use Guided ON/OFF or submit a Custom Program. The workstation session is temporary workflow context, not proof of a named student's identity. Routine compliant Custom work proceeds through Check, automatic preparation/policy checks, Ready to Run and deliberate Run. Per-run instructor approval is not the normal flow. Instructor login, recovery, evidence access and any policy-exception authority remain separate. OS administration and private provisioning remain instructor duties.

The browser administration path uses its authenticated session and CSRF checks for mutations. The preserved explicit `X-Sentinel-Token` API path also accepts the configured instructor credential; it does not require that browser session/CSRF pair. These paths identify instructor authority, not a named administrator. Neither grants student OS or firmware-administration access.

Check binds an immutable source snapshot. The editor and template controls are disabled during Check, stale replies are rejected, and changing the source requires another Check. Before an explicit Run, the browser refreshes the attempt's current server authority. An invalidated attempt does not generate an execute request. The server checks authority again and remains decisive if state changes between those requests.

Execution consumes an attempt. A successful or uncertain dispatch is never retried automatically; another execution requires a fresh Check and new run ID. The browser obtains bounded status observations after dispatch. A terminal report must correlate to the run and prepared program and report LED off before the backend marks `DEVICE_REPORTED_COMPLETE`. The normal page then reports device completion and requires a fresh Check. A device report, including one from authenticated Wi-Fi transport, is not a direct physical observation. Simulator reports remain simulator evidence even where the UI uses the configured ESP32-CAM label.

## Language and execution bounds

Accepted source is one `void experiment() { ... }` function. Calls are literal `led(0);`, `led(1);`, `wait_ms(N);` and `status();`. Includes, comments, variables, loops, other functions, filesystem/network operations and trailing source are rejected. If LED calls occur, the final LED call must be off; status-only work is permitted. Preparation creates a bounded interaction program, not an uploaded firmware image.

| Boundary | Current implementation |
| --- | --- |
| Source | 1–2,048 ASCII characters/bytes |
| Operations | 1–32 calls |
| Each wait | Canonical decimal integer, 10–1,000 ms inclusive |
| Aggregate requested waiting | At most 5,000 ms |
| Encoded program | At most 255 bytes |
| Firmware elapsed guard | Stops when elapsed time exceeds 5,500 ms |
| Optional Gateway policy | May tighten operation count, aggregate waiting and LED permission |
| Active execution | One program on the target at a time |

The numerical limits are adopted project requirements and independently tested source boundaries. They are not measured LED timing guarantees or a claim of advisor approval. These source-language limits apply to the LED Flasher workflow. The ESP32-CAM profile remains bounded separately, while the 1.0.7 Autonomous Car path uses its own fixed motor mapping, authenticated device protocol and firmware-enforced 120 ms motor-action bound.

## Recovery, readiness and stopping

Startup remains locked and invalidates pending authority. The configuration reference now includes workflow version 9, so older records remain historical and do not silently become current authorization. An instructor may read retained historical evidence; further workflow actions require the active configuration.

| Boundary | Pending prepared LED authority | Resulting eligibility |
| --- | --- | --- |
| Instructor LOCK_STOP or RESET | Invalidated across workstation sessions | Locked; recovery and a fresh Check are required |
| Instructor UNLOCK | Invalidated, including work checked while locked | Administrative Gateway unlock does not contact the target; fresh authenticated target readiness is still required before physical execution, and Custom work requires a fresh Check |
| Explicit run STOP | Invalidated | Gateway remains locked; consumed attempt cannot run again |
| Confirmed Guided OFF | Invalidated | Does not itself globally lock an already unlocked Gateway; another run needs fresh Check |
| Communication failure or uncertainty | Invalidated | Locked recovery; no automatic RUN retry |
| Fresh authenticated DEVICE_BUSY refusal | Not globally invalidated | The unexecuted prepared attempt remains eligible after the target becomes available |
| Ordinary grammar or policy rejection | Other pending attempts unaffected | Correct the rejected source and submit a new Check |

The transport already fetched a fresh nonce/HMAC-bound status before commands in the predecessor. That readiness gate was not missing. The successor preserves it and durably records an allowlisted pre-command report before dispatch. It records run ID, state, reported LED, GPIO capability, program digest and origin; it excludes credentials, boot nonces, routing details and arbitrary device text. A failure to retain this preflight evidence prevents the command from being sent. In-process fixtures use a matching simulator callback; no wire field was added.

Guided ON sends a bounded five-second requested-wait program with final LED off. Guided OFF is a bounded stopping action available to any admitted workstation context, including a different session from ON. OFF keeps its own command ID. Firmware reports that STOP command ID; it does not preserve the ON ID as the STOP result ID. The Gateway links an earlier run only when the authenticated pre-STOP identity and program digest match a retained current-configuration run and the STOP is confirmed with LED off. Evidence records both `stopped_run_id` and `stop_command_id`; the earlier run can then become `DEVICE_REPORTED_COMPLETE`. Unknown, mismatched or unconfirmed prior identity never closes an unrelated run. OFF failure or uncertainty locks recovery. Instructor Lock/Stop remains a distinct recovery action.

## Display and browser behavior

Display GETs and polling do not query or control hardware. Workstation Home, prepare and track mutations enforce the shared presentation owner and protect an active LED run. Locked state prevents ordinary presentation mutations, including instructor prepare/track/idle requests. While unlocked, an instructor may deliberately override presentation without stopping a running device. The active-device marker is conservative until a fresh terminal or STOP report is obtained; elapsed browser time or display expiry alone does not clear it.

The eight administration scenes remain independent presentation choices. The Locked scene control consults actual Gateway health and invokes Lock/Stop when needed; a RECOVERY image alone is not treated as proof that the Gateway is locked. Administration feedback and logout handle pages without the old advanced result element. Advanced controls remain hidden. Car ownership errors are visible. Autonomous Car interaction is limited to the implemented bounded motor and camera operations; no unrestricted vehicle Run control is exposed.

Custom status observation uses a one-second interval, at most 12 requests and a 15-second scheduling window. Each request has a three-second abort limit. Guided observation begins after six seconds, then checks a RUNNING report at one-second intervals within a 15-second scheduling window, with the same per-request abort limit. A request started before the scheduling deadline may finish afterward. These bounds do not measure physical stopping time. Correlation failure, unavailable status or exhausted observation ends polling with an explicit uncertain-state message; none retransmits execution. A successful local Guided OFF also clears the page's pending Custom authority.

## Changed source files

### 1.0.7 final-release changes

| Files | Purpose |
| --- | --- |
| `gateway/app.py` | Authenticated CAM health and CAR telemetry workers, sanitized live device reports, vehicle capture/Gallery integration and current Gateway presentation data |
| `gateway/car_transport.py`, CAR protocol/support code | Separate authenticated Autonomous Car transport, bounded semantic motor operations and fail-closed transport handling |
| `esp32/sentinel_car/` | ESP32-WROVER vehicle firmware with fixed motor mapping, 120 ms motor bound, LDR/camera reporting and authenticated Gateway communication |
| `gateway/static/display_twin.js`, `display_twin.css`, `gateway/templates/display.html` | CPS Studio Digital Twin vehicle/LED presentation, connection indicators, LDR/RSSI values and RUN/IDLE activity state |
| `gateway/static/display.js`, `display.css` and related display assets | CPS Studio Lab Display presentation and final identity/presentation refinement |
| Autonomous Car templates/static assets | Bounded motor controls, authenticated camera capture, temporary workstation-scoped Gallery and Digital Twin link |
| Portal templates/static assets | CPS Studio visual identity, Home, CPS Apps, Administration and supporting page refinements |
| `tests/` | Expanded Gateway, Autonomous Car, transport, firmware-source, Gallery, Digital Twin and packaging regression coverage |
| `VERSION`, `README.md`, `docs/SUCCESSOR.md` | Identify and document final release 1.0.7 while preserving historical baseline distinctions |

### Historical 1.0.6 successor changes


| Files | Purpose |
| --- | --- |
| `gateway/app.py` | Short-lived sanitized ESP32-CAM report cache and read-only `/api/display/devices` endpoint |
| `gateway/static/display_twin.js`, `display_twin.css` | Digital Twin presentation and fresh authenticated CAM LED-state rendering |
| `gateway/static/display.js`, `display.css`, `display_clock.js`, `display_select_visuals.js` | Completed Lab Display states, motion, clock, experiment visuals and track presentation |
| `gateway/templates/display.html` | Lab View / Digital Twin structure and current presentation assets |
| `tests/test_display_devices.py` | Six regressions covering unknown, fresh ON/OFF, stale, unavailable and no-device-query behavior |
| `VERSION`, `README.md`, `docs/SUCCESSOR.md` | Identify and document release 1.0.6 while retaining historical baseline distinctions |

### Retained predecessor change record

| Files | Purpose |
| --- | --- |
| `gateway/app.py` | Shared pending-authority invalidation; durable preflight evidence; explicit Guided STOP linkage; terminal Custom state; presentation owner/active/lock checks |
| `gateway/config.py` | Workflow version 9 in the configuration binding |
| `gateway/transport.py`, `gateway/simulator.py` | Verified pre-command callback without changing SCPS1 |
| `gateway/static/custom_program.js`, `led_control.js` | Immutable Check, stale-authority preflight, bounded status observation and feedback |
| `gateway/static/workflow.js`, `admin_display.js`, `car.js` | Safe administration feedback/logout, actual lock handling and visible presentation errors |
| `gateway/templates/experiment_led.html`, `admin.html`, `experiment_car.html` | Unique/visible feedback elements and clarified controls |
| `tools/release_policy.py`, `tools/verify_bundle.py` | Admit the existing reviewed raster-asset directories; require exact manifest coverage of selected release files |
| `tests/test_backend_reconciliation.py`, `test_source_bounds.py`, `test_transport.py`, `test_packaging.py` | Targeted regressions, limits, recovery-order expectation and packaging checks |
| `VERSION`, `README.md`, `docs/SUCCESSOR.md` | Identify maintenance release 1.0.5, document administrative UNLOCK separation, and preserve historical baseline distinctions |
| `verification/software-tests-SW-SUCCESSOR-1.0.4.json`, corresponding `.txt`, and `firmware-host-SUCCESSOR-1.0.4.txt` | Retain historical 1.0.4 candidate results and code/configuration/test hash binding alongside later maintenance records |

No firmware source, `gateway/evidence.py` or `gateway/lab_display.py` change was needed. Source packaging retains the existing assets; it does not admit arbitrary binaries. Allowed raster suffixes are JPG/JPEG/PNG/WebP directly inside the reviewed brand, contact, display-gallery, experiment-images and home-gallery directories. Private state, provisioned templates, unexpected files and included symlinks remain refused or excluded by the existing policy. SHA-256 manifests check integrity, not publisher authenticity.

## Verification and retained failures

Raw successor evidence is under `04-Verification/` in the enclosing successor package; paths below are relative to that directory. The source's `verification/` folder retains [SW-SUCCESSOR-1.0.4](../verification/software-tests-SW-SUCCESSOR-1.0.4.json), its full Python output and a separately labeled host firmware-core result. That historical 1.0.4 record binds 133 code/configuration/test files and the relevant result hashes. Earlier SW-R03/SW-R04 and firmware target-build records remain historical; they were not relabeled as later results.

| Check | Result and locator |
| --- | --- |
| Predecessor existing suite | 58/58 passed; `baseline-existing-suite-loopback.txt` |
| Initial new backend cases against predecessor | 11 methods: 3 passed, 8 failed, with 10 failure entries including recovery subcases; `backend-before.txt` |
| Same initial cases after corrections | 11/11 passed; `backend-after-first.txt` |
| Expanded backend and existing transport/workstation coverage | 58/58 passed; `backend-and-transport-after.txt` |
| Historical 1.0.4 final Python suite | 84/84 passed in 30.700 s; retained 1.0.4 result |
| Staged 1.0.5 Python suite | 86/86 passed in 48.118 s; includes UNLOCK-without-device and unavailable-device-execution regressions |
| 1.0.6 successor Python suite | 92/92 passed; adds six focused read-only display-device telemetry regressions |
| 1.0.7 final Python suite | 147/147 passed; canonical `tools/test.py` also passed both native firmware-engine checks |
| Host firmware core | Passed parser/engine/response checks; `firmware-host-core.txt` |
| Browser baseline | Six expected defect/limitation reproductions; `browser/baseline/results.json` |
| Final mocked browser | 12/12 passed; `browser/candidate/results.json` |
| Actual local Flask application with in-process simulator | 8/8 browser scenarios passed; zero browser errors or external requests; `browser/integrated/results.json` |
| Original package integrity/selection | Old manifest rejected and existing raster assets rejected by old selection; `packaging-before.json` |

Focused totals overlap the final suite and must not be added to 84. A baseline browser `pass: true` means the harness observed the expected gap, not that the predecessor had correct behavior. Early runs that lacked Flask or could not bind localhost are retained as environment failures in `baseline-existing-suite.txt` and `baseline-existing-suite-deps.txt`; they are not product-defect reproductions. Dependencies were made available from existing local wheels in an isolated fixture environment. Browser checks used installed Chrome. They do not cover every browser or the ESP32 network stack.

The retained host C++ and Arduino-related records belong to their recorded earlier baselines; no firmware source or SCPS1 wire-format change was made for 1.0.5. The 1.0.5 maintenance correction changes Gateway administrative UNLOCK behavior and its browser feedback. Physical acceptance of that correction remains pending until the staged release is selected and tested with the target disconnected.

## Local software demonstration

Use a disposable unpacked copy for a demonstration, with private local state separate from deployment evidence. Verify the final packaged source with `python3 tools/verify_bundle.py`. A development tree being reconciled may legitimately fail verification until its final manifest is regenerated; do not bypass that check on a delivered release.

With Python 3.11+ and the pinned dependencies available in a local virtual environment, use `python tools/test.py` for the software suite and host C++ checks, and `python tools/home.py` for the loopback simulator. The commands and two-terminal HTTP-fixture setup in [HOME.md](HOME.md) are retained, but use this current page sequence:

1. Open the portal at `http://127.0.0.1:8080` and Administration at `/admin`. Read the administrator credential privately from `.local/home.env`; there is no student token to enter.
2. Instructor: establish the reported default state using recovery as needed, then Unlock. This is simulator state only. Unlock invalidates any preparation made beforehand.
3. Workstation: select LED Flasher. Use Guided ON/OFF, or enter a permitted Custom Program and select Check. Select Run once when Ready to Run.
4. Read the bounded completion feedback. Repeat only through a fresh Check. Inspect `/display`; its browser image is not an HDMI test.
5. Exercise instructor Lock/Stop and recovery, retain evidence and preserve earlier attempts. Stop the local server when finished.

`tools/home.py` creates/reuses private fixture credentials and `.local/evidence`. Do not point it at a deployed evidence store or copy its simulator history into a physical result record. The historical submit/approve browser sequence in HOME/HANDOFF is superseded by the steps above.

## Staged upgrade for an existing Pi installation

This is a manual instructor procedure for a future authorized maintenance session, not an executed migration or a tested upgrade script. **Do not run `deploy/install.sh` on an existing installation.** It is fresh-install-only and intentionally refuses existing service, account, release, configuration or evidence state. Do not remove those safeguards or erase existing paths to make it run.

1. **Inventory the actual installation.** Record the active service and any socket/proxy units, effective working directory/entry point, resolved release pointer, Python environment, private config/environment paths, evidence directory, service ownership/modes and current transport. Compare the effective unit and overrides with the delivered template. The template uses `/opt/sentinel-cps-final/current`, `/etc/sentinel-cps-final/` and `/var/lib/sentinel-cps-final`; these are comparison points, not assumptions about the live host. Retain listener/firewall/forwarding state and clock quality. Keep secret values out of the shareable inventory. Do not replace a working proxy or infer the original workstation from a loopback backend address.
2. **Quiesce and preserve.** Finish or stop device work under instructor control, inspect the physical LED/default state and record any uncertainty. Prevent new browser work during maintenance. Stop the identified application service and any activation mechanism that could restart it before a filesystem copy. Preserve the complete evidence directory consistently, including any SQLite WAL/SHM files, plus private configuration, environment, unit overrides, current release pointer and required runtime files. Preserve owners/modes and hashes in a restricted backup. An SQLite online backup is an alternative only when performed correctly for the active database. Copying only a live `.db` file is insufficient. Keep the unchanged backup and failed attempts.
3. **Stage in a new location.** Verify the delivered bundle and its separately retained checksum, then unpack to a new version-specific release directory beside the actual existing releases. Never overlay the active release. Create a separate virtual environment there using the pinned dependency lock and the included wheelhouse for a supported Pi Python ABI (3.11 or 3.13). Preserve the existing service user and permissions. Do not run the installer, generate replacement deployment credentials, copy example config over private config, change network settings or flash firmware.
4. **Rehearse independently.** Before selecting the candidate, run software checks and an isolated simulator with fresh synthetic credentials and a separate scratch evidence directory. For database compatibility, work from a copy of the consistent backup, never its sole preserved copy. Confirm schema/startup behavior and historical reads with the installed dependencies. Candidate startup changes workflow state and appends evidence; treat the rehearsal copy as disposable test data. Do not run candidate and old processes against the same ledger. Record that workflow version 9 changes the configuration reference and that prior prepared attempts will not carry over.
5. **Select the staged release deliberately.** While the service and activation path remain stopped, select the new release through the installation's actual release-pointer mechanism. Keep the old release and pointer target for rollback. Retain the reviewed private configuration/environment and evidence location; do not overwrite them with bundle templates. Start the reviewed existing service and verify the effective process entry point and version, not just a directory name or symlink. Record source/manifest hashes, process identity, configuration reference, service status and startup lock. No browser session or previous Ready state should be treated as permission to resume execution.
6. **Verify before admitting normal work.** Review Gateway health and instructor authentication. Establish a fresh authenticated terminal LED-off device report, perform instructor recovery/Unlock, and use a new Check and new run ID. Capture run IDs, configuration identity, wire/device result class, timing observations and direct physical observation separately. Test stopping/recovery invalidation, denied ownership, Custom completion and the TV display in its actual geometry. Preserve failed/partial results. Browser success alone does not close formal acceptance criteria.
7. **Rollback without erasing the attempt.** Stop and quiesce the candidate, preserve its complete new evidence and runtime state, and select the separately verified previous release. Confirm database compatibility before reusing a ledger; if a prior consistent snapshot is needed, retain both candidate history and that snapshot under distinct identities and document the discontinuity. Never overwrite or delete the failed candidate's evidence. Restart locked, perform instructor recovery and use a new attempt. A rollback to earlier software also restores its known limitations.

Deployment acceptance needs its own record. The preserved 1.0.3 capture, deployed 1.0.4 baseline, final 1.0.5 maintenance baseline, deployed 1.0.6 baseline and 1.0.7 candidate results remain distinct evidence. The 1.0.7 software and development-hardware checks do not by themselves establish that 1.0.7 is the running production Pi process. Production acceptance must record the selected release, service process, private configuration reference, Gateway/device communication and direct laboratory observation after the staged upgrade.
