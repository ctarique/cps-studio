#!/usr/bin/env bash
set -euo pipefail

GATEWAY_SERVICE="sentinel-cps-final.service"
OBSERVER_SERVICE="cps-studio-observer.service"

HEALTH_URL="http://127.0.0.1:8080/api/health"
STATUS="/opt/cps-studio-tools/CPS-Studio-Status.sh"

if [ "$EUID" -ne 0 ]; then
    exec sudo -- "$0" "$@"
fi

printf '\n=== CPS STUDIO — CONTROLLED RESTART ===\n\n'

if systemctl is-active \
    --quiet "$OBSERVER_SERVICE"; then

    echo "An eBPF capture is currently active."
    echo "Stopping the Observer before restarting CPS Studio..."
    systemctl stop "$OBSERVER_SERVICE"
    echo
fi

echo "Restarting CPS Studio..."

systemctl restart "$GATEWAY_SERVICE"

printf 'Waiting for Gateway health'

HEALTH_OK=0

for _ in $(seq 1 25); do
    if curl -fsS \
        --max-time 2 \
        "$HEALTH_URL" \
        >/dev/null 2>&1; then

        HEALTH_OK=1
        break
    fi

    printf '.'
    sleep 1
done

printf '\n\n'

if [ "$HEALTH_OK" -ne 1 ]; then
    echo "ERROR: CPS Studio did not recover after restart."
    echo

    journalctl \
        -u "$GATEWAY_SERVICE" \
        -n 30 \
        --no-pager

    exit 1
fi

echo "Restart complete."
echo

"$STATUS"
