#!/usr/bin/env bash
set -u

GATEWAY_SERVICE="sentinel-cps-final.service"
OBSERVER_SERVICE="cps-studio-observer.service"

HEALTH_URL="http://127.0.0.1:8080/api/health"

EXPECTED_OBSERVER="0.1.3"
EXPECTED_ANALYTICS="0.1.2"
EXPECTED_AI="0.1.3"

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0


if [ "$EUID" -ne 0 ]; then
    exec sudo --preserve-env=CPS_EXPECTED_WLAN_CIDR -- "$0" "$@"
fi


line() {
    printf '%*s\n' 68 '' | tr ' ' '='
}


pass() {
    PASS_COUNT=$((PASS_COUNT + 1))
    printf '[PASS] %-26s %s\n' "$1" "$2"
}


warn() {
    WARN_COUNT=$((WARN_COUNT + 1))
    printf '[WARN] %-26s %s\n' "$1" "$2"
}


fail() {
    FAIL_COUNT=$((FAIL_COUNT + 1))
    printf '[FAIL] %-26s %s\n' "$1" "$2"
}


line
printf '                 CPS STUDIO — LAB READINESS CHECK\n'
line
printf '\n'


#
# Production release
#
CURRENT="/opt/sentinel-cps-final/current"

if [ -L "$CURRENT" ]; then
    RELEASE="$(
        basename "$(readlink -f "$CURRENT")"
    )"

    case "$RELEASE" in
        1.0.8-*)
            pass "CPS Studio release" "$RELEASE"
            ;;
        *)
            warn "CPS Studio release" "$RELEASE"
            ;;
    esac
else
    fail "CPS Studio release" "current release link missing"
fi


#
# Gateway service
#
GATEWAY_STATE="$(
    systemctl is-active "$GATEWAY_SERVICE" 2>/dev/null || true
)"

if [ "$GATEWAY_STATE" = "active" ]; then
    pass "Gateway service" "active"
else
    fail "Gateway service" "$GATEWAY_STATE"
fi


GATEWAY_ENABLED="$(
    systemctl is-enabled "$GATEWAY_SERVICE" 2>/dev/null || true
)"

if [ "$GATEWAY_ENABLED" = "enabled" ]; then
    pass "Gateway boot enablement" "enabled"
else
    warn "Gateway boot enablement" "$GATEWAY_ENABLED"
fi


#
# Observer should normally be off outside a capture.
#
OBSERVER_STATE="$(
    systemctl is-active "$OBSERVER_SERVICE" 2>/dev/null || true
)"

if [ "$OBSERVER_STATE" = "inactive" ]; then
    pass "Research Observer" "inactive"
elif [ "$OBSERVER_STATE" = "active" ]; then
    warn "Research Observer" "ACTIVE — capture may be in progress"
else
    warn "Research Observer" "$OBSERVER_STATE"
fi


#
# Component versions
#
check_version() {
    local label="$1"
    local file="$2"
    local expected="$3"

    if [ ! -r "$file" ]; then
        fail "$label" "version file unavailable"
        return
    fi

    local actual
    actual="$(cat "$file")"

    if [ "$actual" = "$expected" ]; then
        pass "$label" "$actual"
    else
        warn "$label" "$actual (expected $expected)"
    fi
}


check_version \
    "Observer version" \
    /opt/cps-studio-observer/VERSION \
    "$EXPECTED_OBSERVER"

check_version \
    "Analytics version" \
    /opt/cps-studio-analytics/VERSION \
    "$EXPECTED_ANALYTICS"

check_version \
    "AI Analysis version" \
    /opt/cps-studio-ai/VERSION \
    "$EXPECTED_AI"


#
# Gateway health and devices
#
printf '\n--- Gateway / Devices ----------------------------------------------\n'

HEALTH="$(
    curl -fsS \
        --max-time 4 \
        "$HEALTH_URL" \
        2>/dev/null \
        || true
)"

if [ -z "$HEALTH" ]; then
    fail "Gateway health" "endpoint unavailable"
else
    HEALTH_VALUES="$(
        python3 - "$HEALTH" <<'PY'
import json
import sys

try:
    data = json.loads(sys.argv[1])
except Exception:
    raise SystemExit(1)

print(data.get("stage", "UNKNOWN"))
print(data.get("transport", "UNKNOWN"))
print(data.get("esp32_cam_health", "UNKNOWN"))
print(data.get("esp32_wrover_health", "UNKNOWN"))
print(data.get("evidence_available", False))
PY
    )"

    if [ "$?" -ne 0 ]; then
        fail "Gateway health" "invalid health response"
    else
        mapfile -t H <<< "$HEALTH_VALUES"

        STAGE="${H[0]:-UNKNOWN}"
        TRANSPORT="${H[1]:-UNKNOWN}"
        CAM="${H[2]:-UNKNOWN}"
        CAR="${H[3]:-UNKNOWN}"
        EVIDENCE="${H[4]:-False}"

        pass "Gateway health" "responsive"
        pass "Gateway stage" "$STAGE"

        if [ "$TRANSPORT" = "wifi" ]; then
            pass "Device transport" "wifi"
        else
            warn "Device transport" "$TRANSPORT"
        fi

        if [ "$CAM" = "CONNECTED" ]; then
            pass "ESP32-CAM" "CONNECTED"
        else
            fail "ESP32-CAM" "$CAM"
        fi

        if [ "$CAR" = "CONNECTED" ]; then
            pass "ESP32-WROVER" "CONNECTED"
        else
            fail "ESP32-WROVER" "$CAR"
        fi

        if [ "$EVIDENCE" = "True" ] \
           || [ "$EVIDENCE" = "true" ]; then
            pass "Evidence storage" "available"
        else
            warn "Evidence storage" "reported unavailable"
        fi
    fi
fi


#
# Time quality
#
printf '\n--- Host / Network -------------------------------------------------\n'

NTP="$(
    timedatectl show \
        -p NTPSynchronized \
        --value \
        2>/dev/null \
        || true
)"

if [ "$NTP" = "yes" ]; then
    pass "Clock synchronization" "synchronized"
else
    warn "Clock synchronization" "${NTP:-unknown}"
fi


#
# WLAN/AP address
#
if ip link show wlan0 >/dev/null 2>&1; then
    WLAN_STATE="$(
        cat /sys/class/net/wlan0/operstate 2>/dev/null || true
    )"

    WLAN_ADDR="$(
        ip -4 -o addr show dev wlan0 \
            | awk '{print $4}'
    )"

    if [ -z "${CPS_EXPECTED_WLAN_CIDR:-}" ]; then
        warn "Private CPS WLAN" \
            "Set CPS_EXPECTED_WLAN_CIDR to verify the configured AP address."
    elif printf '%s\n' "$WLAN_ADDR" \
        | grep -Fxq -- "$CPS_EXPECTED_WLAN_CIDR"; then

        pass "Private CPS WLAN" \
            "wlan0 ${CPS_EXPECTED_WLAN_CIDR} (${WLAN_STATE:-unknown})"
    else
        fail "Private CPS WLAN" \
            "${WLAN_ADDR:-no IPv4 address}"
    fi
else
    fail "Private CPS WLAN" "wlan0 missing"
fi


#
# Human/lab Ethernet boundary.
#
if ip link show eth0 >/dev/null 2>&1; then
    ETH_STATE="$(
        cat /sys/class/net/eth0/operstate 2>/dev/null || true
    )"

    ETH_ADDR="$(
        ip -4 -o addr show dev eth0 \
            | awk '{print $4}' \
            | paste -sd ',' -
    )"

    if [ "$ETH_STATE" = "up" ]; then
        pass "Lab Ethernet" \
            "${ETH_ADDR:-up, no IPv4 shown}"
    else
        warn "Lab Ethernet" \
            "${ETH_STATE:-unknown} ${ETH_ADDR:-}"
    fi
else
    warn "Lab Ethernet" "eth0 missing"
fi


#
# Forwarding must remain disabled.
#
IP_FORWARD="$(
    sysctl -n net.ipv4.ip_forward 2>/dev/null || true
)"

if [ "$IP_FORWARD" = "0" ]; then
    pass "IPv4 forwarding" "disabled"
else
    fail "IPv4 forwarding" "${IP_FORWARD:-unknown}"
fi


#
# Firewall existence / default-drop evidence.
#
NFT="$(
    nft list ruleset 2>/dev/null || true
)"

if [ -z "$NFT" ]; then
    fail "nftables" "ruleset unavailable"
else
    pass "nftables" "ruleset loaded"

    if printf '%s\n' "$NFT" \
        | grep -Eq 'hook input .*policy drop'; then
        pass "Input default policy" "drop"
    else
        warn "Input default policy" \
            "no input policy-drop line recognized"
    fi
fi


#
# Disk capacity
#
AVAILABLE_KB="$(
    df -Pk / \
        | awk 'NR==2 {print $4}'
)"

AVAILABLE_HUMAN="$(
    df -h --output=avail / \
        | tail -1 \
        | xargs
)"

if [ "$AVAILABLE_KB" -lt 1048576 ]; then
    fail "Disk free" "$AVAILABLE_HUMAN"
elif [ "$AVAILABLE_KB" -lt 2097152 ]; then
    warn "Disk free" "$AVAILABLE_HUMAN"
else
    pass "Disk free" "$AVAILABLE_HUMAN"
fi


printf '\n'
line

printf 'Passed:   %d\n' "$PASS_COUNT"
printf 'Warnings: %d\n' "$WARN_COUNT"
printf 'Failures: %d\n' "$FAIL_COUNT"
printf '\n'

if [ "$FAIL_COUNT" -gt 0 ]; then
    printf 'LAB READINESS: ATTENTION REQUIRED\n'
    RESULT=1
elif [ "$WARN_COUNT" -gt 0 ]; then
    printf 'LAB READINESS: READY WITH WARNINGS\n'
    RESULT=0
else
    printf 'LAB READINESS: PASS\n'
    RESULT=0
fi

line

exit "$RESULT"
