> Retained engineering background from the supplied source reference. Version-specific test totals, hardware observations, deployment steps, and linked records are historical; some referenced files were not supplied. For this public copy, start with [the repository README](../../README.md) and [source status](../../SOURCE-STATUS.md).

# Experiment source and Wi-Fi protocol

> Successor context, 23 September 2026: the source grammar and SCPS1 wire format below are retained and unchanged. The workflow/authority paragraphs describe the earlier Core approval model. Candidate 1.0.4 uses workstation Check → Ready to Run → Run, shared invalidation across recovery boundaries, separately identified Guided OFF, and correlated terminal completion; confirmed Guided OFF does not itself globally lock an unlocked Gateway. See [SUCCESSOR.md](SUCCESSOR.md) for those semantics, the 255-byte encoded-program limit, workflow-version-9 configuration binding and pre-command evidence. Earlier compile/physical-status statements retain their dated scope.

## Source preparation
Accepted grammar is one function: `void experiment() { statements }`. Whitespace is accepted. Statements are `led(0);`, `led(1);`, `wait_ms(N);` (canonical decimal 10-1000), or `status();`. Source must be ASCII, 1-2048 bytes, 1-32 calls, and at most 5000 ms total waits. If LED calls occur, the last LED call must be off. Includes, comments, variables, loops, functions, filesystem/network calls, extra fields and trailing source are rejected.

Preparation maps those calls to `L0`, `L1`, `W<N>`, and `S0`, joined with commas. SHA-256 binds the source and program separately. No shell, dynamic evaluation, external compiler or user-controlled filename is invoked by the Gateway. Trusted firmware independently validates the program before accepting it. It holds one program in RAM, bounds execution to 5500 ms, and reports the LED off at completion/stop/reset or observed Wi-Fi loss. These are software behaviors awaiting physical validation.

## Workflow and authority
Student: submit -> CHECKED -> prepare -> PREPARED.
Instructor: review -> approve -> APPROVED; separately unlock after status.
Student: execute once -> COMMUNICATING -> DEVICE_REPORTED or INCOMPLETE.

The device may report RUNNING or COMPLETE; DEVICE_REPORTED means a valid report was received, not physical completion. Status correlation checks the run ID and prepared program digest. Student stop is limited to its current device run. Instructor stop/reset is the separate recovery authority. All stop requests lock the Gateway. There is no automatic retry following an uncertain response.

Every restart locks the Gateway, expires pending approvals and marks interrupted transmission INCOMPLETE. The running service takes a single-instance process lock. The workflow lock serializes requests; an absolute HTTP exchange deadline bounds network delays. One cohort credential cannot establish per-person attribution.

## Wire format SCPS1
HTTP is direct to a fixed private IPv4 address and port selected by instructor configuration. Redirects and environment proxies are not followed. A hardware request first verifies the Linux Wi-Fi route. Firmware listens only in Wi-Fi station mode, filters the configured Gateway source IP, limits header/body buffers and times incomplete requests out. Each HTTP response uses a fixed 768-byte buffer and one nonblocking send. Partial or failed sends close the connection without retry; the Gateway treats an unconfirmed POST as uncertain. This prevents a response retry loop from holding up the execution loop, but physical timing still requires lab measurement. No Hub, ESP-NOW or serial command reader is present.

A GET `/v1/status?nonce=<32 lowercase hex>` returns:
```text
SCPS1|boot_nonce|next_sequence|last_run_id|state|led_reported|gpio_enabled|program_sha256|DEVICE
```
The response signature header is HMAC-SHA256(key, `STATUS\n<nonce>\n` + response bytes). A fresh nonce binds the response to this request.

POST `/v1/work` body:
```text
SCPS1|boot_nonce|sequence|run_id|RUN|L1,W200,L0,S0
SCPS1|boot_nonce|sequence|run_id|STOP|
SCPS1|boot_nonce|sequence|run_id|RESET|
```
The request header `X-Sentinel-Signature` is HMAC-SHA256(key, `POST\n/v1/work\n` + body).
The boot nonce must match this boot and the exact next sequence must be used. Successful mutations increment the sequence. Old boot nonces, repeated commands, malformed programs and unauthenticated requests are rejected. No replay is automatically retried. Commands are refused after sequence 99999998; an instructor-controlled reboot starts a new boot nonce, and the Gateway must recover before a new attempt.

The result body has the same status fields. Its HMAC context is `RESULT\n<SHA256(request body)>\n`. The Gateway checks signature, run ID, boot, sequence, origin, expected program digest and action-specific state. A RUN must report RUNNING or COMPLETE, and LED programs require enabled GPIO. An LED-on report is rejected unless GPIO is enabled and state is RUNNING. This authenticates an ESP32 report; it is not remote attestation or proof of physical execution. The shared device key resides in trusted firmware and is not protected against physical extraction.

The in-process/HTTP fixture uses origin SIMULATOR. HTTP fixture requests have a one-second absolute deadline covering headers and body, reject duplicate framing headers and unsupported transfer modes, and use the firmware sequence limit. The fixture is not a byte-for-byte implementation of the ESP32 networking stack. Wi-Fi mode rejects that origin. The unauthenticated `/health` diagnostic returns only a fixed service/protocol marker and is not a policy decision input.

## Evidence
The SQLite event ledger rejects application UPDATE/DELETE of event rows and commits dispatch intent before sending a command. It records UUID run references, UTC host timestamps, opaque configuration references, role, source/program hashes, preparation, separate simulator/Wi-Fi exchanges, separate reported-device outcomes, recovery and observation references. The private route is included through a keyed opaque configuration binding, not exposed directly. Timeout and run/event quotas also contribute to that reference. Device-response events retain the reported run ID and correlation with the requested run.

Rejected source is not retained. Accepted source is restricted to the documented language. Evidence downloads omit source, raw HTTP content, private network identifiers, boot nonces and credentials. Status has no device address, MAC, host paths, arbitrary device strings or unobserved safety claims. Raw external exceptions are not displayed.

Storage/quota failure locks the workflow and prevents further actions. If stored records remain readable, authenticated instructors may still list/review/export them. Those reads return audit_logging=UNAVAILABLE and workflow_locked=true and do not create events. They do not permit workstation experiment actions or recovery commands. Repair storage under instructor control, preserve the old store, then restart locked. The bounded store is not an archival service; use instructor backups and distinct session directories rather than deleting earlier attempts. Filesystem administrators can alter the store: the append-only behavior is not cryptographic tamper evidence. Host clock correctness and disk durability require lab review.

Historical runs remain reviewable after a configuration change, while further actions and observation attachments require the original active configuration. The revised configuration fingerprint therefore makes older Core 1.0.0 runs historical. An attached observation SHA-256 remains an unverified reference; values equal to configured credentials are rejected. The software does not infer a physical PASS from it. Optional host observability and offline model analysis are not live control inputs.

## References
- [Flask security guidance](https://flask.palletsprojects.com/en/stable/web-security/)
- [Waitress deployment documentation](https://docs.pylonsproject.org/projects/waitress/en/latest/)
- [Espressif Network API](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/network.html)
- [Espressif Wi-Fi API](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/wifi.html)
- [AI Thinker camera/LED mapping in Espressif core 3.3.7](https://github.com/espressif/arduino-esp32/blob/3.3.7/libraries/ESP32/examples/Camera/CameraWebServer/camera_pins.h)
