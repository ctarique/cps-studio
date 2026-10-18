#!/usr/bin/env bash
set -euo pipefail

ROOT="/var/lib/cps-studio-observer/captures"


if [ "$EUID" -ne 0 ]; then
    exec sudo -- "$0" "$@"
fi


usage() {
    cat <<'TXT'
CPS Studio Research Captures

Usage:
  cps-captures
  cps-captures --verify CAPTURE-ID
  cps-captures --verify-all

Examples:
  cps-captures
  cps-captures --verify LAB-TRAIN-01
  cps-captures --verify-all

When more than one directory shares the same capture ID,
--verify selects the newest matching capture.
TXT
}


ACTION="list"
TARGET=""


while [ "$#" -gt 0 ]; do
    case "$1" in
        --verify)
            ACTION="verify"
            TARGET="${2:-}"
            shift 2
            ;;

        --verify-all)
            ACTION="verify-all"
            shift
            ;;

        -h|--help)
            usage
            exit 0
            ;;

        *)
            echo "Unknown argument: $1"
            echo
            usage
            exit 2
            ;;
    esac
done


if [ ! -d "$ROOT" ]; then
    echo "No CPS Studio capture directory exists yet."
    exit 0
fi


list_captures() {
    python3 - "$ROOT" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])

dirs = sorted(
    [
        p
        for p in root.iterdir()
        if p.is_dir()
        and not p.name.startswith("_")
    ],
    reverse=True,
)

print()
print("CPS Studio Research Captures")
print("=" * 112)

if not dirs:
    print("No retained research captures.")
    raise SystemExit(0)

header = (
    f"{'CAPTURE ID':<24} "
    f"{'PURPOSE':<26} "
    f"{'SECONDS':>8} "
    f"{'WINDOWS':>8} "
    f"{'CONN':>5} "
    f"{'EXEC':>5} "
    f"{'INTR':>5} "
    f"{'INTEGRITY':<10}"
)

print(header)
print("-" * 112)

for directory in dirs:
    manifest_path = directory / "capture-manifest.json"
    sums_path = directory / "SHA256SUMS"

    if manifest_path.exists():
        try:
            manifest = json.loads(
                manifest_path.read_text()
            )
        except Exception:
            manifest = {}
    else:
        manifest = {}

    if sums_path.exists():
        result = subprocess.run(
            [
                "sha256sum",
                "-c",
                "--quiet",
                "SHA256SUMS",
            ],
            cwd=directory,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        integrity = (
            "VERIFIED"
            if result.returncode == 0
            else "FAILED"
        )
    else:
        integrity = "NO-SUMS"

    capture_id = manifest.get(
        "capture_id",
        directory.name,
    )

    purpose = str(
        manifest.get("purpose", "UNKNOWN")
    )

    seconds = manifest.get(
        "actual_observation_seconds"
    )

    if isinstance(seconds, (int, float)):
        seconds_text = f"{seconds:.1f}"
    else:
        seconds_text = "?"

    windows = manifest.get(
        "complete_feature_windows",
        "?",
    )

    conn = manifest.get(
        "unexpected_connection_windows",
        "?",
    )

    execs = manifest.get(
        "unexpected_exec_windows",
        "?",
    )

    interrupted = manifest.get(
        "interrupted",
        "?",
    )

    if interrupted is True:
        intr = "YES"
    elif interrupted is False:
        intr = "NO"
    else:
        intr = "?"

    print(
        f"{str(capture_id)[:24]:<24} "
        f"{purpose[:26]:<26} "
        f"{seconds_text:>8} "
        f"{str(windows):>8} "
        f"{str(conn):>5} "
        f"{str(execs):>5} "
        f"{intr:>5} "
        f"{integrity:<10}"
    )

    print(
        f"  directory: {directory.name}"
    )

print("=" * 112)
PY
}


verify_directory() {
    local directory="$1"

    echo
    echo "Capture:"
    echo "  $directory"
    echo

    if [ ! -f "$directory/SHA256SUMS" ]; then
        echo "ERROR: SHA256SUMS is missing."
        return 1
    fi

    (
        cd "$directory"

        sha256sum -c SHA256SUMS
    )
}


case "$ACTION" in
    list)
        list_captures
        ;;

    verify)
        if [ -z "$TARGET" ]; then
            echo "ERROR: --verify requires a capture ID."
            exit 2
        fi

        MATCH="$(
            find "$ROOT" \
                -mindepth 1 \
                -maxdepth 1 \
                -type d \
                -name "${TARGET}-*" \
                ! -name '_*' \
                -print \
                | sort \
                | tail -1
        )"

        if [ -z "$MATCH" ]; then
            echo "ERROR: no capture found for ID:"
            echo "  $TARGET"
            exit 1
        fi

        verify_directory "$MATCH"
        ;;

    verify-all)
        FAILED=0

        while IFS= read -r directory; do
            [ -n "$directory" ] || continue

            if ! verify_directory "$directory"; then
                FAILED=1
            fi
        done < <(
            find "$ROOT" \
                -mindepth 1 \
                -maxdepth 1 \
                -type d \
                ! -name '_*' \
                -print \
                | sort
        )

        if [ "$FAILED" -eq 1 ]; then
            echo
            echo "One or more captures failed verification."
            exit 1
        fi

        echo
        echo "All retained captures verified."
        ;;
esac
