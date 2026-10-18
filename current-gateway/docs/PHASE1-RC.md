> Retained engineering background from the supplied source reference. Version-specific test totals, hardware observations, deployment steps, and linked records are historical; some referenced files were not supplied. For this public copy, start with [the repository README](../../README.md) and [source status](../../SOURCE-STATUS.md).

# CPS Studio Phase 1 release candidate — 1.0.8

Status: development release candidate from the October 13, 2026 snapshot; **not deployed and not formally validated**. VERSION identifies the candidate source, not a production release. The original 1.0.7 README, successor documentation and verification/audit files are retained byte-for-byte as historical source records; their prior PASS/deployment statements are not this candidate's acceptance record. Current results and deployment limitations are in the separate candidate reports directory.

## Security and evidence changes

The same authorization, HMAC, nonce/sequence, device endpoint/route checks and firmware bounds remain. No trusted firmware source or physical behavior changed. Guided/custom vehicle/LED features and the twelve-track presentation are preserved.

Ordinary events and runs retain their configured limits. Additive immutable capacity-attribution tables provide a second bounded reserve with at most max_events recovery events and max_runs recovery runs; ordinary requests cannot consume it. Only existing authenticated instructor LOCK_STOP/RESET can use it when ordinary storage is degraded or lacks complete-attempt capacity. It uses the same WAL/FULL ledger and same export. A conservative pending-invalidation-count+16 budget must be available before dispatch; intent/preflight are committed before mutation. Events explicitly carry audit_capacity=recovery_reserve. Unlock and normal work remain blocked in recovery-only mode; underlying I/O failure or an exhausted reserve still refuses unlogged dispatch. Successful recovery does not repair storage or imply physical stopping. A write-ahead INCOMPLETE marker persists until the final result commits.

Known-secret filtering now covers the CAR key. Camera Content-Length conversion is bounded; malformed transport data returns normalized failure. CAR known refusals/failures are terminal REJECTED/FAILED; uncertain dispatch remains INCOMPLETE and locked. Configuration workflow version 10 prevents historical prepared authority from becoming current.

## Supporting quality contract

Observer 0.1.3, Analytics 0.1.2 and AI 0.1.3 preserve feature definitions and Isolation Forest parameters. Temporal coverage is separate from complete valid observation. Observation coverage ends before producer shutdown; post-cutoff callback receipts invalidate timing quality rather than becoming complete zero-event windows. Missing historical loss data is unknown, never zero; invalid/lost/unverified telemetry is ineligible for complete real-data windows. Capture locking/cleanup and stop/window checks preserve partial failure outputs instead of reporting success.

Models remain offline trusted executable inputs. New loading requires explicit operator trust plus validated independently retained manifest/hash/schema before deserialization of the exact checked bytes. Training/calibration provenance and numerical/threshold constraints are checked. Hashes/declared nonoverlap do not authenticate a model producer or physically verify acquisition independence.

## Verification and deployment boundary

The internal MANIFEST.json is regenerated only from the final release-policy-selected source. The public environment template contains placeholders only. Use tools/verify_bundle.py; do not bypass it. tools/test.py runs all unchanged existing tests plus new Gateway regressions and both unchanged native firmware cores. The candidate's separate verification runner also checks supporting regression cases and preservation.

No HTTPS frontend, firewall-service dependency, new student identity system or global actuator-STOP semantics were added. No autonomous course-following or physical timing claim is made. The original fresh installer is not a complete-system installer or upgrade tool. See the separate remediation report for current test commands/results, remaining concerns, manual staged deployment/rollback and required live acceptance tests.
