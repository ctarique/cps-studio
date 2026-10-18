#!/usr/bin/env bash
set -euo pipefail

GATEWAY_SERVICE="sentinel-cps-final.service"
OBSERVER_SERVICE="cps-studio-observer.service"

ASSUME_YES=0

if [ "${1:-}" = "--yes" ]; then
    ASSUME_YES=1
fi

if [ "$EUID" -ne 0 ]; then
    exec sudo -- "$0" "$@"
fi

printf '\n=== CPS STUDIO — STOP ===\n\n'

if [ "$ASSUME_YES" -ne 1 ]; then
    printf 'Stop CPS Studio and any active research capture? [y/N] '

    read -r ANSWER

    case "$ANSWER" in
        y|Y|yes|YES)
            ;;
        *)
            echo "Cancelled."
            exit 0
            ;;
    esac
fi

if systemctl is-active \
    --quiet "$OBSERVER_SERVICE"; then

    echo "Stopping eBPF Observer..."
    systemctl stop "$OBSERVER_SERVICE"
fi

if systemctl is-active \
    --quiet "$GATEWAY_SERVICE"; then

    echo "Stopping CPS Studio..."
    systemctl stop "$GATEWAY_SERVICE"
fi

echo
printf 'Gateway:  '
systemctl is-active "$GATEWAY_SERVICE" || true

printf 'Observer: '
systemctl is-active "$OBSERVER_SERVICE" || true

echo
echo "CPS Studio stopped."
