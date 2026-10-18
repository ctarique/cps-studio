#!/usr/bin/env bash
set -u

GATEWAY_SERVICE="sentinel-cps-final.service"
OBSERVER_SERVICE="cps-studio-observer.service"

HEALTH_URL="http://127.0.0.1:8080/api/health"

OBSERVER_VERSION="/opt/cps-studio-observer/VERSION"
ANALYTICS_VERSION="/opt/cps-studio-analytics/VERSION"
AI_VERSION="/opt/cps-studio-ai/VERSION"

CURRENT_RELEASE="/opt/sentinel-cps-final/current"

line() {
    printf '%*s\n' 60 '' | tr ' ' '='
}

value_or_unknown() {
    if [ -r "$1" ]; then
        cat "$1"
    else
        printf 'UNKNOWN\n'
    fi
}

line
printf '                CPS STUDIO — SYSTEM STATUS\n'
line
printf '\n'

GATEWAY_STATE="$(
    systemctl is-active "$GATEWAY_SERVICE" 2>/dev/null || true
)"

GATEWAY_ENABLED="$(
    systemctl is-enabled "$GATEWAY_SERVICE" 2>/dev/null || true
)"

OBSERVER_STATE="$(
    systemctl is-active "$OBSERVER_SERVICE" 2>/dev/null || true
)"

OBSERVER_ENABLED="$(
    systemctl is-enabled "$OBSERVER_SERVICE" 2>/dev/null || true
)"

if [ -L "$CURRENT_RELEASE" ]; then
    RELEASE="$(
        basename "$(readlink -f "$CURRENT_RELEASE")"
    )"
else
    RELEASE="UNKNOWN"
fi

printf '%-24s %s\n' \
    "CPS Studio release" "$RELEASE"

printf '%-24s %s\n' \
    "Gateway service" "$GATEWAY_STATE"

printf '%-24s %s\n' \
    "Gateway enabled" "$GATEWAY_ENABLED"

printf '%-24s %s\n' \
    "Observer version" "$(value_or_unknown "$OBSERVER_VERSION")"

printf '%-24s %s\n' \
    "Analytics version" "$(value_or_unknown "$ANALYTICS_VERSION")"

printf '%-24s %s\n' \
    "AI Analysis version" "$(value_or_unknown "$AI_VERSION")"

printf '%-24s %s\n' \
    "Observer service" "$OBSERVER_STATE"

printf '%-24s %s\n' \
    "Observer enabled" "$OBSERVER_ENABLED"

printf '\n--- Gateway Health -----------------------------------------\n'

HEALTH=""

if HEALTH="$(
    curl -fsS \
        --max-time 3 \
        "$HEALTH_URL" \
        2>/dev/null
)"; then

    printf '%s' "$HEALTH" | python3 -c '
import json
import sys

data = json.load(sys.stdin)

fields = [
    ("Stage", "stage"),
    ("Transport", "transport"),
    ("ESP32-CAM", "esp32_cam_health"),
    ("ESP32-WROVER", "esp32_wrover_health"),
    ("Evidence", "evidence_available"),
    ("Physical validation", "physical_validation"),
]

for label, key in fields:
    value = data.get(key, "UNKNOWN")

    if isinstance(value, bool):
        value = "AVAILABLE" if value else "UNAVAILABLE"

    print(f"{label:<24} {value}")
'

    HEALTH_OK=1

else
    printf '%-24s %s\n' \
        "Health endpoint" "UNAVAILABLE"

    HEALTH_OK=0
fi

printf '\n--- Host ---------------------------------------------------\n'

printf '%-24s %s\n' \
    "Hostname" "$(hostname)"

printf '%-24s %s\n' \
    "Kernel" "$(uname -r)"

DISK_FREE="$(
    df -h --output=avail / \
        | tail -1 \
        | xargs
)"

printf '%-24s %s\n' \
    "Root filesystem free" "$DISK_FREE"

printf '\n'

if [ "$GATEWAY_STATE" = "active" ] \
   && [ "$HEALTH_OK" -eq 1 ]; then
    printf 'Status: READY\n'
else
    printf 'Status: ATTENTION REQUIRED\n'
fi

line
