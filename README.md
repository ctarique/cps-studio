# CPS Studio

CPS Studio is a research platform for Gateway-mediated experiments with ESP32 devices. The Gateway provides browser workflows, bounded LED programs, authenticated device communication, instructor recovery controls, a local display, and an evidence ledger.

This repository is a sanitized source copy of the supplied October 16, 2026 engineering reference. It includes a local software simulator and supporting observation and analysis code. See [SOURCE-STATUS.md](SOURCE-STATUS.md) for source identity and limitations, and [VERIFICATION.md](VERIFICATION.md) for checks of this public copy.

## Local simulator

Requires macOS or Linux, Python 3.11 or newer, and a C++17 compiler for the native firmware checks. Initial dependency installation requires Internet access.

From the repository root:

```sh
cd current-gateway
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
python tools/verify_bundle.py
python tools/test.py
python tools/home.py
```

Open `http://127.0.0.1:8080` and Administration at `http://127.0.0.1:8080/admin`.

The launcher generates private local credentials in `current-gateway/.local/home.env`. Read the administrator credential privately and enter it on the Administration page. Establish the simulator's default state through recovery if needed, then Unlock. On the LED Flasher page, use Guided ON/OFF or Check a permitted Custom Program before selecting Run. An Unlock invalidates earlier preparation.

Stop the server with Ctrl-C. Local credentials and simulator evidence remain under `current-gateway/.local/`; keep that directory out of Git. The local launcher does not configure a vehicle device.

Simulator results are synthetic. They do not demonstrate device behavior, physical timing, HDMI operation, or research validation.

## Repository structure

| Path | Contents |
| --- | --- |
| `current-gateway/gateway/` | Python backend, browser templates, and static assets |
| `current-gateway/esp32/` | Trusted LED and vehicle firmware source |
| `current-gateway/tests/` | Software and host firmware checks |
| `current-gateway/config/` | Examples with blank credentials or placeholders |
| `current-gateway/tools/` | Simulator, verification, packaging, and firmware build helpers |
| `current-gateway/docs/` | Current local setup and retained historical engineering notes |
| `supporting-software/` | Observer, feature analytics, offline AI analysis, and instructor utilities |
| `deployment/instructor-tools/` | Installed instructor utility scripts retained as source references |

The Gateway dependency lock covers the Gateway. Observer requires a compatible Linux/BCC environment and explicit `--cam-ip` and `--car-ip` arguments. AI analysis requires NumPy, scikit-learn, and Joblib. These components have no actuator authority.

Instructor utilities assume an administrator-provisioned Linux installation. The readiness check requires the expected AP IPv4 address and prefix in `CPS_EXPECTED_WLAN_CIDR`; preserve that variable when invoking the check through sudo. These utilities are not part of the local simulator setup.

The local simulator workflow is the starting point for this public copy. Deployment and hardware provisioning require a separately reviewed environment and private configuration.

## Publication

See [PUBLICATION.md](PUBLICATION.md) for sharing checks and project license status.
