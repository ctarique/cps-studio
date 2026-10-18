#!/usr/bin/env bash

cat <<'TXT'

============================================================
              CPS STUDIO — INSTRUCTOR TOOLKIT
============================================================

SYSTEM STATUS

  cps-status

      Read-only system overview.


LAB READINESS

  cps-check

      Pre-lab readiness assessment.

      Checks:
        CPS Studio
        device connectivity
        component versions
        clock synchronization
        network boundaries
        forwarding state
        nftables
        disk capacity
        Observer state


START / RESTART / STOP

  cps-start

      Start CPS Studio and verify health.

  cps-restart

      Controlled Gateway restart and health check.

  cps-stop

      Confirm and stop CPS Studio.
      Stops an active Observer first.


RESEARCH CAPTURE

  cps-capture \
    --id LAB-TRAIN-01 \
    --purpose BENIGN_TRAINING \
    --duration 30m

      Start eBPF collection, wait for observer_ready,
      collect telemetry, generate complete 10-second
      windows, and retain checksums/metadata.

      This command does NOT train the AI model.


CAPTURE INVENTORY

  cps-captures

      List retained research captures.

  cps-captures --verify LAB-TRAIN-01

      Verify the newest matching capture against its
      retained SHA-256 manifest.

  cps-captures --verify-all

      Verify all retained research captures.


TROUBLESHOOTING

  cps-diagnostics

      Create a sanitized diagnostic bundle containing
      service, network, health, version, and recent-log
      information.

      No service is restarted or changed.

      Review the bundle before sharing it outside the
      project team.


RELEASE-CANDIDATE BASELINE (NOT DEPLOYED)

  CPS Studio           1.0.8
  eBPF Observer         0.1.3
  Feature Analytics     0.1.2
  AI Analysis           0.1.3


IMPORTANT

  These tools do not provide a second actuator-control
  path.

  eBPF and AI analysis have no authority over:
    authorization
    device commands
    STOP/recovery
    firewall policy
    CPS safety decisions

============================================================

TXT
