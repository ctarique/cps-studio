CPS Studio Instructor Toolkit
=============================

Primary commands
----------------

cps-status
    Read-only CPS Studio system status.

cps-check
    Read-only pre-lab readiness assessment.

cps-start
    Start CPS Studio and verify Gateway health.

cps-restart
    Controlled CPS Studio restart and health check.

cps-stop
    Confirm and stop CPS Studio.

cps-capture
    Perform a versioned eBPF research capture and
    generate complete 10-second analytics windows.

cps-captures
    List and verify retained research captures.

cps-diagnostics
    Create a sanitized troubleshooting bundle.

cps-help
    Display the instructor command reference.


Release-candidate engineering baseline (not deployed)
----------------------------------------------------

CPS Studio:
    1.0.8

eBPF Observer:
    0.1.3

Feature Analytics:
    0.1.2

AI Analysis:
    0.1.3


Common instructor workflow
--------------------------

Before a lab:

    cps-check

For a quick status view:

    cps-status

If CPS Studio is stopped:

    cps-start

If a controlled restart is needed:

    cps-restart

For an approved research capture:

    cps-capture \
      --id LAB-TRAIN-01 \
      --purpose BENIGN_TRAINING \
      --duration 30m

Review retained captures:

    cps-captures

Verify a capture:

    cps-captures --verify LAB-TRAIN-01

When troubleshooting:

    cps-diagnostics

For command help:

    cps-help


Security boundary
-----------------

The toolkit contains no intentionally embedded:

    Gateway/admin tokens
    ESP32 device keys
    Wi-Fi passwords
    SSH private keys

The toolkit does not create a second CPS actuator path.

eBPF and AI components remain observational/offline and
have no live authorization, command, STOP, recovery, or
safety authority.
