> Retained engineering background from the supplied source reference. Version-specific test totals, hardware observations, deployment steps, and linked records are historical; some referenced files were not supplied. For this public copy, start with [the repository README](../../README.md) and [source status](../../SOURCE-STATUS.md).

# Raspberry Pi and ESP32 deployment

> Historical deployment guidance, 23 September 2026: this document records the Core 1.0.1 fresh-install design and its then-pending lab work. It does not describe the later captured 1.0.3 installation or prove candidate 1.0.4 deployment. The TLS frontend is a supplied option, not evidence that the recorded HTTP socket-proxy deployment used TLS. Preserve the actual site's private settings and use [the staged 1.0.4 upgrade procedure](SUCCESSOR.md#staged-upgrade-for-an-existing-pi-installation) for an existing installation. The installer below is fresh-install-only; the successor changes no firmware source and requires no automatic reflash.

Core 1.0.1 is a software baseline for controlled lab deployment. The installer and network policy have not been executed on the lab Pi. Keep the current diagnostic firmware until its pending output is captured. Preserve the existing flash backup and its recorded hash.

## Raspberry Pi prerequisites
Use 64-bit Raspberry Pi OS with Python 3.11 or 3.13, python3-venv, systemd and iproute2. The offline wheelhouse includes both supported Python ABIs. Provision these OS packages through the instructor's approved process before an offline lab session.

The installer uses a separate `sentinel-final` service account and `/opt/sentinel-cps-final`. It refuses an occupied port 8080, an existing final installation/configuration/evidence directory or service unit, and an existing sentinel-final user/group before changing the system. This installer supports fresh installation only. It does not overwrite the old Gateway. If the historical service owns that port, preserve its configuration/evidence first and stop that specific service under instructor control. Do not change the working SSH or firewall configuration just to bypass a failed install.

From the unpacked release:

```sh
python3 tools/verify_bundle.py
sudo sh deploy/install.sh
systemctl is-active sentinel-cps-final
curl --fail http://127.0.0.1:8080/api/health
```

The installer starts in **SIMULATOR mode**, locked and listening only on loopback. It uses the bundled wheels with a pinned hash-checked lockfile; no network dependency download is needed. This first check establishes only local service behavior.

Private configuration is `/etc/sentinel-cps-final/gateway.json`, root:sentinel-final, mode 0640. Its directory is mode 0750. The environment file `gateway.env` is root-only mode 0600; systemd reads it and passes distinct random browser/device credentials to the service. Evidence is in `/var/lib/sentinel-cps-final`, owned by the service, mode 0700. Ordinary students have no OS access to those files. The service has no dialout membership, hardware-device access, or capability grants.

## Student browser access
The direct loopback server is for local use only. On the instructor-controlled Pi, configure the supplied Nginx template with a lab-trusted TLS certificate and the documented workflow name `gateway.lab.example`. Configure lab DNS or workstation hosts records for that name. The template is not installed or enabled automatically. The app accepts forwarded HTTPS scheme only from its loopback frontend.

Restrict inbound HTTPS to the approved student network and instructor administration to its existing approved path. Preserve default-deny inbound/forwarding policy and disabled IP forwarding. Keep students off the private CPS Wi-Fi. Do not give students a Pi shell or SSH account as a browser-access workaround. Validate allowed and denied listeners in VAL-01. No public Internet exposure is part of this package.

## ESP32-CAM
The user confirmed AI Thinker ESP32-CAM. The build target is `esp32:esp32:esp32cam`; checked toolchain: Arduino CLI 1.5.1 and Espressif Arduino core 3.3.7. The GPIO4 white flash LED mapping comes from Espressif's CameraWebServer AI Thinker configuration. A red indicator is a different light; do not assume the same GPIO or polarity. Camera and SD functions are unused.

Copy `config/ai-thinker-esp32cam-led.example.h` to a private file outside the release. Fill the existing private AP SSID, PSK, the Pi's private Wi-Fi address and the Gateway's **device key**. Never use a browser credential as the device key. The device uses DHCP; reserve/confirm its private lease on the Pi and use that device address in the Gateway's private Wi-Fi configuration. Do not invent a new subnet or change the existing AP as part of application deployment.

The generic header has GPIO disabled (-1); the board-specific header selects GPIO4 active high. Blank credentials always refuse network/GPIO startup. The firmware has a minimal `/health` diagnostic and signed `/v1/status`; only the signed endpoint is used for workflow decisions. Both accept connections only from the configured Gateway IP.

Compile on the instructor's workstation with the existing approved toolchain:

```sh
python3 tools/build_firmware.py --board esp32cam --private-config /path/to/private/sentinel_config.local.h --output /path/to/private/esp32-build
```

This tool never uploads. The output must be a new directory outside the release. The build helper creates it with mode 0700 and refuses reuse, including a failed earlier build. A provisioned binary contains credentials and must remain private. The package includes compile-only results, not a ready-to-flash binary with real credentials. Preserve the current diagnostic output and pre-change backup before any instructor-led bootstrap operation. USB may be used for instructor bootstrap/diagnostics; it is not a runtime Gateway-to-Hub control path. After bootstrap, power the ESP32 independently for Wi-Fi trials.

The Gateway preparation stage does not require an Arduino toolchain on the Pi because the approved student source subset is prepared into bounded interaction bytecode. It is not a full C++ firmware compilation service. An offline ARM64 Arduino toolchain is not bundled or claimed installed; the trusted firmware was compile-tested on the home workstation.

## Enable real Wi-Fi mode
Only after association is diagnosed and the private lease confirmed, replace the private Gateway JSON with the fields from `config/gateway.wifi.example.json`. Set the actual private ESP32 address and `wlan0`, assign a new LAB-CONFIG number, keep proper ownership/mode, and restart the service.

The hardware transport verifies that Linux routes to the configured device over a wireless interface named wlan0-wlan9. It rejects a missing interface or wrong route and never switches to simulation. Signed payloads prevent unauthenticated mutation/replay; WPA-protected private Wi-Fi and access restrictions provide the documented network boundary. Application messages are authenticated, not encrypted by the HTTP layer. This is a controlled laboratory design, not public-network security.

Use instructor RESET, then UNLOCK with the available signed status. Record every result, including failures. A successful response still does not prove the LED changed. Follow LAB.md.

## HDMI
Connect Pi HDMI directly to the Smart TV and open `http://127.0.0.1:8080/display` in the Pi's local browser, fullscreen if appropriate. Record HDMI input, resolution/scaling and observation tied to a run. Do not configure a TV IP endpoint or use a TV browser as the control path.

## Evidence backup and rollback
Preserve the entire SQLite store consistently. Under instructor control, stop the service before copying the evidence directory, or use SQLite's online backup API while running. Copy the private configuration separately with its permissions preserved. Do not copy only the database file while WAL writes are active.

For a software rollback within the final architecture, stop the final service, preserve its evidence and config, and select a separately verified prior final release. Do not point the new service at the archived serial implementation. Start locked and use a new run for verification. The fresh-install script is not an upgrade/rollback manager; an existing final installation requires a separately reviewed instructor migration. Existing evidence remains historical even when a later version succeeds.

If the installer fails partway, it leaves a separate partial release and exits. Inspect the error and preserve any existing evidence; do not remove historical files or force an overwrite. Installation is not claimed transactional.
