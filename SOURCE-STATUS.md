# Source status and limitations

## Source identity

This public source copy derives from the supplied October 16, 2026 engineering reference. The reference identifies its installed source directory as `1.1.0-rc5-20261016`, while the included Gateway `VERSION` file and retained source labels say `1.0.9-RC`.

Those identifiers describe different records in the supplied material. The directory label does not resolve the embedded version mismatch. This repository preserves the included version rather than assigning a new qualified release identity.

Historical test totals and deployment observations from earlier documentation are not results for this sanitized copy. See [VERIFICATION.md](VERIFICATION.md) for checks of the public copy. Run `python tools/test.py` from `current-gateway/` to run Python tests followed by two native host firmware checks.

## Public-copy scope

Private deployment configuration, credentials, operational inventories, runtime evidence, captures, fitted models, photographs, and institutional logo assets are excluded. Generic hand-authored SVG presentation assets replace omitted image references. The public interface therefore differs from the installed laboratory interface.

This source copy is not a restorable installation. Retained engineering notes describe their original releases and operating contexts. Source checks and simulator behavior do not establish physical execution or research acceptance.

## Observer 0.1.3

The supplied reference records an unresolved eBPF event decoding mismatch:

```text
received_size=60 expected_size=56
```

The kernel event and Python decoder disagree on event size. Observer output must not be treated as quality-accepted telemetry until this defect is corrected and capture quality is verified. Proposed Observer `0.1.4` work in the reference is not an included completed release.

The public Observer requires explicit `--cam-ip` and `--car-ip` arguments instead of embedded laboratory device addresses. Configure these privately for the actual environment. No real capture data is included.

## Seasonal slideshow

The seasonal slideshow expects separately provisioned images under:

```text
/var/lib/cps-studio-slideshows/seasons
```

Its presentation state is expected under:

```text
/var/lib/sentinel-cps-final/presentation-slideshow
```

These assets and runtime state are not included. Seasonal slideshow controls may report unavailable in the local simulator.

## Instructor readiness check

`cps-check` needs `CPS_EXPECTED_WLAN_CIDR` set to the expected AP IPv4 address and prefix. When running through sudo, preserve that variable explicitly:

```sh
sudo --preserve-env=CPS_EXPECTED_WLAN_CIDR cps-check
```

Set the value privately before invoking the command. The check is for a reviewed Linux deployment; it does not provision a network.

## Evidence boundaries

Authenticated device reports describe what the Gateway received. Simulator results, device reports, direct physical observations, and formal research outcomes remain separate evidence classes. Offline AI scores do not establish intrusion detection effectiveness.
