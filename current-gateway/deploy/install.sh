#!/bin/sh
# Run locally on the Pi only after reading DEPLOYMENT.md. No firmware operation.
set -eu
[ "$(id -u)" -eq 0 ] || { echo "Run this installer as root on the Pi."; exit 1; }
[ "$(uname -s)" = Linux ] && [ "$(uname -m)" = aarch64 ] || { echo "64-bit Raspberry Pi OS required."; exit 1; }
command -v python3 >/dev/null
command -v systemctl >/dev/null
command -v ip >/dev/null
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BUNDLE_DIR=$(dirname -- "$SCRIPT_DIR")
cd "$BUNDLE_DIR"
python3 tools/verify_bundle.py
python3 -c 'import sys; assert sys.version_info[:2] in [(3,11),(3,13)], "Offline bundle supports Python 3.11 or 3.13"'
python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",8080)); s.close()' || {
  echo "Port 8080 is occupied. Preserve the old service/evidence and follow the retirement runbook."; exit 1;
}
RELEASE_VERSION=$(python3 tools/install_preflight.py)
RELEASE_DIR=/opt/sentinel-cps-final/releases/$RELEASE_VERSION
python3 -m venv --help >/dev/null
python3 -c 'import ensurepip'
useradd --system --user-group --home-dir /var/lib/sentinel-cps-final --shell /usr/sbin/nologin sentinel-final
install -d -m 0755 /opt/sentinel-cps-final/releases
install -d -m 0750 -o root -g sentinel-final /etc/sentinel-cps-final
install -d -m 0700 -o sentinel-final -g sentinel-final /var/lib/sentinel-cps-final
mkdir "$RELEASE_DIR"
python3 -c 'import pathlib,sys,shutil; sys.path.insert(0,"tools"); from verify_bundle import verified_files; dst=pathlib.Path(sys.argv[1]); files=verified_files(pathlib.Path.cwd()); [( (dst/n).parent.mkdir(parents=True,exist_ok=True), shutil.copy2(n,dst/n)) for n in files]; shutil.copy2("MANIFEST.json",dst/"MANIFEST.json")' "$RELEASE_DIR"
python3 -m venv "$RELEASE_DIR/.venv"
"$RELEASE_DIR/.venv/bin/python" -m pip install --no-index --find-links "$BUNDLE_DIR/wheelhouse" --require-hashes -r requirements.lock
install -m 0640 -o root -g sentinel-final config/gateway.simulator.json /etc/sentinel-cps-final/gateway.json
python3 -c 'import pathlib,secrets; p=pathlib.Path("/etc/sentinel-cps-final/gateway.env"); p.write_text("SENTINEL_CONFIG=/etc/sentinel-cps-final/gateway.json\nSENTINEL_DATA_DIR=/var/lib/sentinel-cps-final\n"+"".join(k+"="+secrets.token_hex(32)+"\n" for k in ["SENTINEL_ADMIN_TOKEN","SENTINEL_DEVICE_KEY"])); p.chmod(0o600)'
chown -R root:root "$RELEASE_DIR"
chmod -R go-w "$RELEASE_DIR"
ln -s "$RELEASE_DIR" /opt/sentinel-cps-final/current
install -m 0644 deploy/sentinel-cps-final.service /etc/systemd/system/sentinel-cps-final.service
systemctl daemon-reload
systemctl enable --now sentinel-cps-final.service
echo "Installed in SIMULATOR mode, locked, on loopback port 8080. This is not Wi-Fi or physical validation."
echo "Private credentials: /etc/sentinel-cps-final/gateway.env. Follow DEPLOYMENT.md before changing transport."
