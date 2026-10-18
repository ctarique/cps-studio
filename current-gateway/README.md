# CPS Studio Gateway

The Gateway mediates browser access to bounded LED programs and vehicle operations, authenticates device exchanges, maintains an evidence ledger, and provides instructor recovery and presentation controls.

This is the Gateway subtree of a sanitized source snapshot. The included `VERSION` says `1.0.9-RC`; the supplied reference used an installed source-directory label of `1.1.0-rc5-20261016`. See [source status](../SOURCE-STATUS.md) for that mismatch and known limitations.

For a local software demonstration, follow [docs/HOME.md](docs/HOME.md). The simulator uses loopback and generates private local state. Software results remain separate from hardware behavior and formal research outcomes.

Run `python tools/test.py` in this directory after installing the pinned dependencies. See [the public-copy verification record](../VERIFICATION.md) for recorded checks.

The other retained engineering documents contain historical release and deployment context. They are not installation instructions for this public snapshot. The original fresh installer is not an upgrade tool, and this copy omits the private environment and external assets needed for the captured installation.
