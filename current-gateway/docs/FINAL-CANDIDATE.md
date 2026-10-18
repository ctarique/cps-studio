> Retained engineering background from the supplied source reference. Version-specific test totals, hardware observations, deployment steps, and linked records are historical; some referenced files were not supplied. For this public copy, start with [the repository README](../../README.md) and [source status](../../SOURCE-STATUS.md).

# Final development candidate 1.0.9-RC

Foundation: completed offline Phase 2 Gateway 1.0.8. Supporting component versions and all CAM/CAR firmware bytes are retained. No live release identity is inferred from the October 13 capture.

The Portal imports approved content, artwork and responsive CSS into server templates. Real sessions, CSRF, bounded programming, device validation, dynamic capture ownership, evidence and recovery govern every action. Simulator bridges and simulated authentication are excluded. A diagnostic CAR notice remains visible because autonomous track following is unvalidated. ESP32-CAM remains the primary physical experiment target; no new global CAR LOCK_STOP authority exists.

CAR status_rtt is transient, read-only application-level monotonic timing of the existing authenticated CAR status exchange, including authentication/response validation. It is neither ICMP latency nor browser-to-Gateway timing. SUCCESS has fresh milliseconds; STALE, FAILED and UNAVAILABLE suppress the numeric result. No timing is inserted into physical evidence or device reports. No firmware or additional polling is required.

Prepared Caddy uses private TLS, a fixed approved hostname, an exact immediate-peer workstation gate, loopback backend, and fresh firewall guard admission. Existing Waitress trusts only loopback X-Forwarded-Proto and clears untrusted forwarding headers. Gateway trusts the scheme, not forwarded host; Caddy pins Host and HTTPS scheme and removes forwarded host/prefix. Authentication/CSRF code is unchanged. The HDMI display may continue through the existing loopback HTTP path without sharing HTTPS cookies.

Use the outer package current runbook, HTTPS instructions and firewall design. The original deploy/install.sh, nginx example and historical verification records are retained baseline artifacts, not the 1.0.9 upgrade procedure or new test claims. The release package does not contain private credentials, real ledgers, production certificates or provisioned firmware secrets.
