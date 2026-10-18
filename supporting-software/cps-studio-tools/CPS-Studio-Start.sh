#!/usr/bin/env bash
set -euo pipefail

GATEWAY_SERVICE="sentinel-cps-final.service"
HEALTH_URL="http://127.0.0.1:8080/api/health"
STATUS="/opt/cps-studio-tools/CPS-Studio-Status.sh"

if [ "$EUID" -ne 0 ]; then
    exec sudo -- "$0" "$@"
fi

printf '\n=== CPS STUDIO — START ===\n\n'

if systemctl is-active \
    --quiet "$GATEWAY_SERVICE"; then

    echo "CPS Studio is already active."

else
    echo "Starting CPS Studio..."

    systemctl start "$GATEWAY_SERVICE"
fi

printf 'Waiting for Gateway health'

HEALTH_OK=0

for _ in $(seq 1 20); do
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
    echo "ERROR: Gateway did not become healthy."
    echo
    journalctl \
        -u "$GATEWAY_SERVICE" \
        -n 20 \
        --no-pager
    exit 1
fi

echo "CPS Studio started successfully."
echo

"$STATUS"
