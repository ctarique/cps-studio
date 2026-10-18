#!/usr/bin/env bash
set -euo pipefail


if [ "$EUID" -ne 0 ]; then
    exec sudo -- "$0" "$@"
fi


INVOKING_USER="${SUDO_USER:-root}"

if [ "$INVOKING_USER" != "root" ]; then
    INVOKING_HOME="$(
        getent passwd "$INVOKING_USER" \
            | cut -d: -f6
    )"
else
    INVOKING_HOME="/root"
fi


STAMP="$(
    date -u +%Y%m%dT%H%M%SZ
)"

NAME="CPS-Studio-Diagnostics-$STAMP"

WORK="/var/tmp/$NAME"
DEST_ROOT="$INVOKING_HOME/CPS-Studio-Diagnostics"

ARCHIVE="$DEST_ROOT/${NAME}.tar.gz"
SIDECAR="${ARCHIVE}.sha256"


cleanup() {
    rm -rf "$WORK"
}

trap cleanup EXIT


install -d -m 0700 "$WORK"
install -d -m 0700 "$WORK/services"
install -d -m 0700 "$WORK/network"
install -d -m 0700 "$WORK/platform"
install -d -m 0700 "$WORK/config"
install -d -m 0700 "$WORK/logs"
install -d -m 0700 "$WORK/captures"

install -d -m 0700 "$DEST_ROOT"


printf '\n============================================================\n'
printf '           CPS STUDIO — DIAGNOSTIC COLLECTION\n'
printf '============================================================\n\n'

echo "Collecting read-only diagnostic information..."
echo


#
# Toolkit status / readiness
#
/opt/cps-studio-tools/CPS-Studio-Status.sh \
    > "$WORK/status.txt" \
    2>&1 || true

/opt/cps-studio-tools/CPS-Studio-Check.sh \
    > "$WORK/readiness.txt" \
    2>&1 || true

/opt/cps-studio-tools/CPS-Studio-Captures.sh \
    > "$WORK/captures/inventory.txt" \
    2>&1 || true


#
# Health endpoint
#
curl -fsS \
    --max-time 4 \
    http://127.0.0.1:8080/api/health \
    > "$WORK/gateway-health.json" \
    2>/dev/null || true


#
# Component versions
#
{
    printf 'CPS Studio release: '

    readlink -f \
        /opt/sentinel-cps-final/current \
        2>/dev/null || true

    printf 'Observer: '
    cat /opt/cps-studio-observer/VERSION \
        2>/dev/null || true

    printf 'Analytics: '
    cat /opt/cps-studio-analytics/VERSION \
        2>/dev/null || true

    printf 'AI: '
    cat /opt/cps-studio-ai/VERSION \
        2>/dev/null || true

} > "$WORK/platform/component-versions.txt"


#
# Platform
#
{
    echo "=== date ==="
    date -Is

    echo
    echo "=== uname ==="
    uname -a

    echo
    echo "=== os-release ==="
    cat /etc/os-release

    echo
    echo "=== systemd ==="
    systemctl --version | head -1

    echo
    echo "=== uptime ==="
    uptime

    echo
    echo "=== time ==="
    timedatectl 2>/dev/null || true

    echo
    echo "=== disk ==="
    df -h

    echo
    echo "=== memory ==="
    free -h

} > "$WORK/platform/host.txt"


#
# Services
#
UNITS=(
    sentinel-cps-final.service
    cps-studio-observer.service
    sentinel-cps-dhcp.service
    sentinel-cps-web.service
    sentinel-cps-web.socket
    display-manager.service
)

for unit in "${UNITS[@]}"; do
    SAFE="${unit//\//_}"

    systemctl status \
        "$unit" \
        --no-pager \
        > "$WORK/services/${SAFE}-status.txt" \
        2>&1 || true

    systemctl cat \
        "$unit" \
        > "$WORK/services/${SAFE}-definition.txt" \
        2>&1 || true

    systemctl show \
        "$unit" \
        -p Id \
        -p Description \
        -p LoadState \
        -p ActiveState \
        -p SubState \
        -p UnitFileState \
        -p FragmentPath \
        -p DropInPaths \
        -p User \
        -p Group \
        -p WorkingDirectory \
        -p ExecStart \
        -p Requires \
        -p Wants \
        -p After \
        -p Before \
        -p PartOf \
        > "$WORK/services/${SAFE}-properties.txt" \
        2>&1 || true
done


#
# Journals
#
for unit in \
    sentinel-cps-final.service \
    cps-studio-observer.service \
    sentinel-cps-dhcp.service
do
    SAFE="${unit//\//_}"

    journalctl \
        -u "$unit" \
        -n 250 \
        --no-pager \
        > "$WORK/logs/${SAFE}.log" \
        2>&1 || true
done


#
# Relevant kernel messages
#
dmesg --ctime 2>/dev/null \
    | grep -Ei \
        'brcmfmac|wlan0|eth0|firmware|under-voltage|voltage|mmc|network' \
    | tail -400 \
    > "$WORK/logs/kernel-relevant.log" \
    || true


#
# Network state
#
ip -details addr \
    > "$WORK/network/ip-addresses.txt"

ip route show table all \
    > "$WORK/network/routes.txt"

ip rule show \
    > "$WORK/network/ip-rules.txt"

sysctl net.ipv4.ip_forward \
    > "$WORK/network/ip-forwarding.txt" \
    2>&1 || true

nft list ruleset \
    > "$WORK/network/nftables.txt" \
    2>&1 || true

nmcli device status \
    > "$WORK/network/nmcli-devices.txt" \
    2>&1 || true

nmcli -f NAME,UUID,TYPE,DEVICE \
    connection show \
    > "$WORK/network/nmcli-connections.txt" \
    2>&1 || true


#
# Sanitized Gateway JSON.
#
if [ -f /etc/sentinel-cps-final/gateway.json ]; then
    python3 - \
        /etc/sentinel-cps-final/gateway.json \
        "$WORK/config/gateway.json.REDACTED" <<'PY'
import json
import sys
from pathlib import Path

source = Path(sys.argv[1])
output = Path(sys.argv[2])

data = json.loads(source.read_text())

secret_words = (
    "token",
    "secret",
    "password",
    "credential",
    "device_key",
    "api_key",
    "private_key",
    "psk",
)

def redact(value, key=""):
    if any(
        word in key.lower()
        for word in secret_words
    ):
        return "<REDACTED>"

    if isinstance(value, dict):
        return {
            k: redact(v, k)
            for k, v in value.items()
        }

    if isinstance(value, list):
        return [
            redact(v, key)
            for v in value
        ]

    return value

output.write_text(
    json.dumps(
        redact(data),
        indent=2,
        sort_keys=True,
    ) + "\n"
)
PY
fi


#
# Environment variable names only.
#
if [ -f /etc/sentinel-cps-final/gateway.env ]; then
    awk '
        /^[[:space:]]*#/ {
            print;
            next
        }

        /^[A-Za-z_][A-Za-z0-9_]*=/ {
            split($0,a,"=");
            print a[1] "=<REDACTED>";
            next
        }

        {
            print
        }
    ' /etc/sentinel-cps-final/gateway.env \
        > "$WORK/config/gateway.env.REDACTED"
fi


#
# Relevant package versions.
#
dpkg-query -W \
    -f='${Package}\t${Version}\t${Architecture}\n' \
    'python3-bpfcc' \
    'bpfcc-tools' \
    'python3-numpy' \
    'python3-scipy' \
    'python3-sklearn' \
    'python3-joblib' \
    2>/dev/null \
    > "$WORK/platform/relevant-packages.tsv" \
    || true


#
# Best-effort secondary scrub of collected textual output.
#
python3 - "$WORK" <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])

extensions = {
    ".txt",
    ".log",
    ".json",
    ".tsv",
    ".conf",
    ".service",
}

patterns = [
    re.compile(
        r'(?i)'
        r'(token|password|passwd|secret|'
        r'api[_-]?key|device[_-]?key|psk)'
        r'(\s*[:=]\s*)'
        r'([^\s,"\'}]+)'
    ),
    re.compile(
        r'(?i)'
        r'(authorization)'
        r'(\s*[:=]\s*)'
        r'([^\s]+)'
    ),
]

for path in root.rglob("*"):
    if not path.is_file():
        continue

    if path.suffix.lower() not in extensions:
        continue

    try:
        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        continue

    for pattern in patterns:
        text = pattern.sub(
            lambda m:
                f"{m.group(1)}"
                f"{m.group(2)}"
                "<REDACTED>",
            text,
        )

    text = re.sub(
        r'-----BEGIN [^-]*PRIVATE KEY-----'
        r'.*?'
        r'-----END [^-]*PRIVATE KEY-----',
        '<PRIVATE KEY REDACTED>',
        text,
        flags=re.S,
    )

    path.write_text(
        text,
        encoding="utf-8",
    )
PY


#
# Marker audit. This records filenames/line numbers only,
# not the matched values.
#
grep -RniE \
    '(token|password|passwd|secret|api[_-]?key|device[_-]?key|psk|authorization)[[:space:]]*[:=]' \
    "$WORK" \
    2>/dev/null \
    | sed -E \
        's/([:=])[[:space:]]*.*/\1 <VALUE SUPPRESSED>/' \
    > "$WORK/SECRET-MARKER-AUDIT.txt" \
    || true


#
# README
#
cat > "$WORK/README.txt" <<EOF2
CPS Studio Diagnostic Bundle
============================

Created:
$(date -Is)

Purpose:
Read-only troubleshooting snapshot for CPS Studio.

Includes:
- Gateway health/status
- lab readiness output
- service state/definitions
- recent service journals
- selected relevant kernel messages
- interface/routing/firewall state
- component versions
- package versions
- sanitized Gateway configuration
- research capture inventory

Does not intentionally include:
- SSH private keys
- live Gateway/admin tokens
- ESP32 device keys
- Wi-Fi passwords
- raw AI training datasets
- raw research capture telemetry

IMPORTANT:
Sanitization is best-effort. Review the diagnostic bundle
before sharing it outside the project team.
EOF2


#
# Internal checksums.
#
(
    cd "$WORK"

    find . \
        -type f \
        ! -name SHA256SUMS \
        -print0 \
        | sort -z \
        | xargs -0 sha256sum \
        > SHA256SUMS
)


#
# Archive.
#
tar -C "$(dirname "$WORK")" \
    -czf "$ARCHIVE" \
    "$(basename "$WORK")"

chmod 0600 "$ARCHIVE"

sha256sum "$ARCHIVE" \
    > "$SIDECAR"

chmod 0644 "$SIDECAR"


#
# Give the invoking user access to the result.
#
if [ "$INVOKING_USER" != "root" ]; then
    chown -R \
        "$INVOKING_USER:$INVOKING_USER" \
        "$DEST_ROOT"
fi


printf 'Diagnostic bundle created.\n\n'

printf 'Archive:\n  %s\n\n' "$ARCHIVE"

printf 'SHA-256:\n'
cat "$SIDECAR"

printf '\nPotential secret-marker audit entries: '

AUDIT_COUNT="$(
    wc -l \
        < "$WORK/SECRET-MARKER-AUDIT.txt" \
        2>/dev/null \
        || printf '0'
)"

printf '%s\n' "$AUDIT_COUNT"

printf '\nCPS Studio was not restarted or modified.\n'
