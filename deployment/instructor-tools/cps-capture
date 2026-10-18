#!/usr/bin/env bash
set -euo pipefail

GATEWAY_SERVICE="sentinel-cps-final.service"
OBSERVER_SERVICE="cps-studio-observer.service"

HEALTH_URL="http://127.0.0.1:8080/api/health"

OBSERVER_VERSION_FILE="/opt/cps-studio-observer/VERSION"
ANALYTICS_VERSION_FILE="/opt/cps-studio-analytics/VERSION"
AI_VERSION_FILE="/opt/cps-studio-ai/VERSION"

ANALYTICS="/opt/cps-studio-analytics/feature_windows.py"

LIVE_EVENTS="/var/lib/cps-studio-observer/telemetry/events.jsonl"

CAPTURE_ROOT="/var/lib/cps-studio-observer/captures"
PRIOR_ROOT="$CAPTURE_ROOT/_prior"

LOCK_FILE="/run/cps-studio-capture.lock"
umask 077
OBSERVER_STARTED=0
INTERRUPTED=0
CAPTURE_DIR=""
CURRENT_STAGE="preflight"

CAPTURE_ID=""
PURPOSE=""
DURATION_INPUT=""

usage() {
    cat <<'TXT'
CPS Studio Research Capture

Usage:
  cps-capture --id CAPTURE-ID --purpose PURPOSE --duration DURATION

Examples:
  cps-capture \
    --id LAB-TRAIN-01 \
    --purpose BENIGN_TRAINING \
    --duration 30m

  cps-capture \
    --id TOOLKIT-TEST-01 \
    --purpose TOOLKIT_TEST \
    --duration 45s

Duration forms:
  90      seconds
  90s     seconds
  20m     minutes
  1h      hours

The capture script:
  - requires CPS Studio to already be running
  - starts only the eBPF Observer
  - waits for observer_ready
  - collects for the requested observation duration
  - stops the Observer
  - produces complete 10-second feature windows
  - retains metadata and SHA-256 checksums
  - does NOT train or modify the AI model
TXT
}


while [ "$#" -gt 0 ]; do
    case "$1" in
        --id)
            CAPTURE_ID="${2:-}"
            shift 2
            ;;

        --purpose)
            PURPOSE="${2:-}"
            shift 2
            ;;

        --duration)
            DURATION_INPUT="${2:-}"
            shift 2
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


if [ "$EUID" -ne 0 ]; then
    ARGS=()

    [ -n "$CAPTURE_ID" ] \
        && ARGS+=(--id "$CAPTURE_ID")

    [ -n "$PURPOSE" ] \
        && ARGS+=(--purpose "$PURPOSE")

    [ -n "$DURATION_INPUT" ] \
        && ARGS+=(--duration "$DURATION_INPUT")

    exec sudo -- "$0" "${ARGS[@]}"
fi


if [ -z "$CAPTURE_ID" ]; then
    printf 'Capture ID: '
    read -r CAPTURE_ID
fi

if [ -z "$PURPOSE" ]; then
    printf 'Purpose: '
    read -r PURPOSE
fi

if [ -z "$DURATION_INPUT" ]; then
    printf 'Duration (for example 30m or 90s): '
    read -r DURATION_INPUT
fi


if ! [[ "$CAPTURE_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]; then
    echo "ERROR: invalid capture ID."
    echo "Use letters, digits, periods, underscores, or hyphens."
    exit 2
fi

PURPOSE="${PURPOSE//$'\n'/ }"

if [[ "$DURATION_INPUT" =~ ^([0-9]+)([smh]?)$ ]]; then
    NUMBER="${BASH_REMATCH[1]}"
    UNIT="${BASH_REMATCH[2]}"

    case "$UNIT" in
        ""|s)
            DURATION_SECONDS="$NUMBER"
            ;;
        m)
            DURATION_SECONDS="$(( NUMBER * 60 ))"
            ;;
        h)
            DURATION_SECONDS="$(( NUMBER * 3600 ))"
            ;;
    esac
else
    echo "ERROR: invalid duration."
    exit 2
fi

if [ "$DURATION_SECONDS" -lt 20 ]; then
    echo "ERROR: duration must be at least 20 seconds."
    exit 2
fi


printf '\n============================================================\n'
printf '              CPS STUDIO — RESEARCH CAPTURE\n'
printf '============================================================\n\n'

printf '%-20s %s\n' \
    "Capture ID" "$CAPTURE_ID"

printf '%-20s %s\n' \
    "Purpose" "$PURPOSE"

printf '%-20s %s seconds\n' \
    "Duration" "$DURATION_SECONDS"

printf '\n'


# Acquire before testing/starting Observer or rotating shared telemetry.
# The lock remains held through stop, retention, metadata and checksums.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "ERROR: another research capture owns the capture lock."
    exit 1
fi

cleanup() {
    local status="$?"
    local stopped=1
    trap - EXIT INT TERM
    set +e
    if [ "$OBSERVER_STARTED" -eq 1 ]; then
        if ! systemctl stop "$OBSERVER_SERVICE"; then
            stopped=0
        elif systemctl is-active --quiet "$OBSERVER_SERVICE"; then
            stopped=0
        fi
    fi
    if [ "$status" -ne 0 ] && [ -n "$CAPTURE_DIR" ] && [ -d "$CAPTURE_DIR" ]; then
        if [ -e "$LIVE_EVENTS" ] && [ ! -e "$RAW" ]; then
            # A failed stop may leave a live writer: preserve a partial snapshot,
            # rather than moving its open file away or pretending it is final.
            cp "$LIVE_EVENTS" "$RAW"
            chmod 0600 "$RAW"
        fi
        if [ ! -e "$METADATA" ]; then
            python3 - "$METADATA" "$CAPTURE_ID" "$CURRENT_STAGE" "$INTERRUPTED" "$stopped" "$RAW" <<'PY'
import datetime
import hashlib
import json
import sys
from pathlib import Path
metadata, capture_id, stage, interrupted, stopped, raw = sys.argv[1:]
raw_path = Path(raw)
manifest = {
    "capture_id": capture_id,
    "capture_class": "RESEARCH_CAPTURE",
    "capture_success": False,
    "status": "INCOMPLETE",
    "failure_stage": stage,
    "interrupted": bool(int(interrupted)),
    "cleanup_observer_stopped": bool(int(stopped)),
    "raw_snapshot_final": bool(int(stopped)),
    "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest() if raw_path.exists() else None,
    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "interpretation": "Incomplete capture retained for diagnosis; it is not valid research acceptance evidence.",
}
Path(metadata).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
PY
        fi
        (
            cd "$CAPTURE_DIR"
            for file in raw-events.jsonl features-10s.jsonl capture-manifest.json; do
                [ ! -e "$file" ] || sha256sum "$file"
            done > SHA256SUMS
        )
        echo "Capture failed; partial data retained: $CAPTURE_DIR"
    fi
    exit "$status"
}
interrupt_capture() {
    INTERRUPTED=1
    echo "Capture interrupted by operator."
    exit 130
}
trap cleanup EXIT
trap interrupt_capture INT TERM

if ! systemctl is-active \
    --quiet "$GATEWAY_SERVICE"; then

    echo "ERROR: CPS Studio is not active."
    echo "Run cps-start first."
    exit 1
fi


if ! curl -fsS \
    --max-time 3 \
    "$HEALTH_URL" \
    >/dev/null 2>&1; then

    echo "ERROR: Gateway health endpoint is unavailable."
    exit 1
fi


if systemctl is-active \
    --quiet "$OBSERVER_SERVICE"; then

    echo "ERROR: Observer is already active."
    echo "An existing capture may be in progress."
    exit 1
fi


OBSERVER_VERSION="$(
    cat "$OBSERVER_VERSION_FILE"
)"

ANALYTICS_VERSION="$(
    cat "$ANALYTICS_VERSION_FILE"
)"

AI_VERSION="$(
    cat "$AI_VERSION_FILE"
)"

if [ "$OBSERVER_VERSION" != "0.1.3" ]; then
    echo "ERROR: expected Observer 0.1.3."
    exit 1
fi

if [ "$ANALYTICS_VERSION" != "0.1.2" ]; then
    echo "ERROR: expected Analytics 0.1.2."
    exit 1
fi


STAMP="$(
    date -u +%Y%m%dT%H%M%SZ
)"

CAPTURE_DIR="$CAPTURE_ROOT/${CAPTURE_ID}-${STAMP}"

RAW="$CAPTURE_DIR/raw-events.jsonl"
FEATURES="$CAPTURE_DIR/features-10s.jsonl"
METADATA="$CAPTURE_DIR/capture-manifest.json"
CHECKSUMS="$CAPTURE_DIR/SHA256SUMS"


install -d -m 0700 \
    "$CAPTURE_ROOT" \
    "$PRIOR_ROOT"

# Same-ID captures within one timestamp must never overwrite retained data.
if ! mkdir -m 0700 "$CAPTURE_DIR"; then
    echo "ERROR: capture directory already exists or cannot be created."
    CAPTURE_DIR=""
    exit 1
fi


if [ -s "$LIVE_EVENTS" ]; then
    PRIOR="$PRIOR_ROOT/events-before-${CAPTURE_ID}-${STAMP}.jsonl"

    echo "Preserving pre-existing observer telemetry:"
    echo "  $PRIOR"

    mv "$LIVE_EVENTS" "$PRIOR"
    chmod 0600 "$PRIOR"

elif [ -e "$LIVE_EVENTS" ]; then
    rm -f "$LIVE_EVENTS"
fi


printf '\nStarting Observer %s...\n' \
    "$OBSERVER_VERSION"

CURRENT_STAGE="observer_start"
OBSERVER_STARTED=1
systemctl start "$OBSERVER_SERVICE"


READY_TS=""

printf 'Waiting for eBPF probes to become ready'

for _ in $(seq 1 40); do
    if ! systemctl is-active \
        --quiet "$OBSERVER_SERVICE"; then

        printf '\n'
        echo "ERROR: Observer stopped before becoming ready."

        journalctl \
            -u "$OBSERVER_SERVICE" \
            -n 30 \
            --no-pager

        exit 1
    fi

    if [ -s "$LIVE_EVENTS" ]; then
        READY_TS="$(
            python3 - "$LIVE_EVENTS" <<'PY' 2>/dev/null || true
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])

ready = []

for line in path.read_text().splitlines():
    if not line.strip():
        continue

    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        continue

    if (
        isinstance(row, dict)
        and row.get("event_type") == "observer_ready"
        and row.get("observer_version") == "0.1.3"
    ):
        ready.append(row)

if ready:
    print(ready[-1]["timestamp"])
PY
        )"
    fi

    if [ -n "$READY_TS" ]; then
        break
    fi

    printf '.'
    sleep 1
done

printf '\n'


if [ -z "$READY_TS" ]; then
    echo "ERROR: observer_ready was not observed within 40 seconds."

    exit 1
fi


printf 'Observer ready: %s\n' "$READY_TS"
printf 'Collection begins now.\n\n'


CURRENT_STAGE="collection"

printf 'Collecting'

ELAPSED=0

while [ "$ELAPSED" -lt "$DURATION_SECONDS" ]; do
    REMAINING="$(( DURATION_SECONDS - ELAPSED ))"

    if [ "$REMAINING" -gt 10 ]; then
        STEP=10
    else
        STEP="$REMAINING"
    fi

    sleep "$STEP" || true

    if [ "$INTERRUPTED" -eq 1 ]; then
        break
    fi

    ELAPSED="$(( ELAPSED + STEP ))"
    printf '.'

    if ! systemctl is-active \
        --quiet "$GATEWAY_SERVICE"; then

        printf '\n'
        echo "WARNING: Gateway stopped during capture."
        INTERRUPTED=1
        break
    fi

    if ! systemctl is-active \
        --quiet "$OBSERVER_SERVICE"; then

        printf '\n'
        echo "WARNING: Observer stopped during capture."
        INTERRUPTED=1
        break
    fi
done


printf '\n\nStopping Observer...\n'

CURRENT_STAGE="observer_stop"
systemctl stop "$OBSERVER_SERVICE"
if systemctl is-active --quiet "$OBSERVER_SERVICE"; then
    echo "ERROR: Observer remains active after stop."
    exit 1
fi
OBSERVER_STARTED=0


if [ ! -s "$LIVE_EVENTS" ]; then
    echo "ERROR: no observer telemetry was produced."
    exit 1
fi


mv "$LIVE_EVENTS" "$RAW"
chmod 0600 "$RAW"


printf '\nGenerating complete 10-second feature windows...\n\n'

CURRENT_STAGE="analytics"
ANALYTICS_STATUS=0
python3 \
    "$ANALYTICS" \
    --input "$RAW" \
    --output "$FEATURES" \
    --window-seconds 10 || ANALYTICS_STATUS="$?"

if [ ! -e "$FEATURES" ]; then
    : > "$FEATURES"
fi
chmod 0600 "$FEATURES"


PRODUCTION_RELEASE="$(
    readlink -f /opt/sentinel-cps-final/current 2>/dev/null \
        || printf 'UNKNOWN'
)"


python3 - \
    "$RAW" \
    "$FEATURES" \
    "$METADATA" \
    "$CAPTURE_ID" \
    "$PURPOSE" \
    "$DURATION_SECONDS" \
    "$OBSERVER_VERSION" \
    "$ANALYTICS_VERSION" \
    "$AI_VERSION" \
    "$PRODUCTION_RELEASE" \
    "$INTERRUPTED" "$ANALYTICS_STATUS" <<'PY'
import datetime
import hashlib
import json
import socket
import sys
from collections import Counter
from pathlib import Path


(
    raw_name,
    feature_name,
    metadata_name,
    capture_id,
    purpose,
    duration_seconds,
    observer_version,
    analytics_version,
    ai_version,
    production_release,
    interrupted,
    analytics_status,
) = sys.argv[1:]


raw_path = Path(raw_name)
feature_path = Path(feature_name)
metadata_path = Path(metadata_name)


def sha256(path):
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


invalid_rows = 0

def read_jsonl(path):
    global invalid_rows
    rows = []

    for line in path.read_text().splitlines():
        if not line.strip():
            continue

        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("non-object row")
            rows.append(row)
        except (json.JSONDecodeError, ValueError):
            invalid_rows += 1

    return rows


def parse(value):
    value = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("missing timezone")
    return value


raw = read_jsonl(raw_path)
features = read_jsonl(feature_path)


ready = [
    row
    for row in raw
    if row.get("event_type") == "observer_ready"
]

stops = [
    row
    for row in raw
    if row.get("event_type") == "observer_stop"
]


ready_ts = (
    ready[-1].get("timestamp")
    if ready
    else None
)

stop_ts = (
    stops[-1].get("timestamp")
    if stops
    else None
)


actual_seconds = None

observation_end = stops[-1].get("observation_end") if stops else None

if ready_ts and stop_ts and observation_end:
    try:
        end = parse(observation_end)
        if not parse(ready_ts) < end <= parse(stop_ts):
            raise ValueError("invalid observation end")
        actual_seconds = (end - parse(ready_ts)).total_seconds()
    except (ValueError, TypeError, AttributeError):
        invalid_rows += 1


errors = []
if bool(int(interrupted)):
    errors.append("capture_interrupted")
if int(analytics_status) != 0:
    errors.append("analytics_failed")
if invalid_rows:
    errors.append("invalid_jsonl_records")
if len(ready) != 1 or len(stops) != 1:
    errors.append("missing_or_multiple_observer_intervals")
if actual_seconds is None or actual_seconds < int(duration_seconds):
    errors.append("requested_observation_duration_not_covered")
if not features:
    errors.append("no_feature_windows")
if not features or not all(row.get("window_complete") is True for row in features):
    errors.append("incomplete_or_unknown_telemetry")
if ready and stops:
    if not ready[0].get("observation_id") or ready[0].get("observation_id") != stops[0].get("observation_id"):
        errors.append("observation_identity_mismatch")
    if stops[0].get("collection_error") is not False or stops[0].get("buffers_drained") is not True:
        errors.append("unclean_observer_stop")



manifest = {
    "capture_success":
        not errors,

    "status":
        "COMPLETE" if not errors else "INCOMPLETE",

    "acceptance_errors":
        errors,

    "observation_id":
        ready[0].get("observation_id") if len(ready) == 1 else None,

    "capture_id":
        capture_id,

    "purpose":
        purpose,

    "capture_class":
        "RESEARCH_CAPTURE",

    "created_at":
        datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z"),

    "hostname":
        socket.gethostname(),

    "production_release":
        production_release,

    "observer_version":
        observer_version,

    "analytics_version":
        analytics_version,

    "ai_version_present":
        ai_version,

    "ai_training_performed":
        False,

    "requested_duration_seconds":
        int(duration_seconds),

    "interrupted":
        bool(int(interrupted)),

    "observer_ready":
        ready_ts,

    "observer_stop":
        stop_ts,

    "observation_end":
        observation_end,

    "actual_observation_seconds":
        actual_seconds,

    "raw_records":
        len(raw),

    "raw_event_types":
        dict(
            Counter(
                row.get("event_type")
                for row in raw
            )
        ),

    "feature_windows":
        len(features),

    "complete_feature_windows":
        sum(row.get("window_complete") is True for row in features),

    "all_windows_complete":
        bool(features) and all(
            row.get("window_complete") is True
            for row in features
        ),

    "unexpected_connection_windows":
        sum(
            row.get(
                "unexpected_connections",
                0,
            ) > 0
            for row in features
        ),

    "unexpected_exec_windows":
        sum(
            row.get(
                "unexpected_execs",
                0,
            ) > 0
            for row in features
        ),

    "raw_sha256":
        sha256(raw_path),

    "features_sha256":
        sha256(feature_path),

    "interpretation": (
        "This capture contains host-observability "
        "telemetry and derived complete feature windows. "
        "It does not by itself establish physical behavior "
        "or malicious intent."
    ),
}


metadata_path.write_text(
    json.dumps(
        manifest,
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)


print()
print("Capture summary")
print("---------------")
print("Capture ID:              ", manifest["capture_id"])
print("Purpose:                 ", manifest["purpose"])
print("Observation seconds:     ", manifest["actual_observation_seconds"])
print("Raw records:             ", manifest["raw_records"])
print("Complete feature windows:", manifest["complete_feature_windows"])
print("Unexpected conn windows: ", manifest["unexpected_connection_windows"])
print("Unexpected exec windows: ", manifest["unexpected_exec_windows"])
print("Interrupted:             ", manifest["interrupted"])
print("Capture status:          ", manifest["status"])
if errors:
    print("Acceptance errors:       ", ", ".join(errors))
    raise SystemExit(1)
PY


chmod 0600 "$METADATA"

(
    cd "$CAPTURE_DIR"

    sha256sum \
        raw-events.jsonl \
        features-10s.jsonl \
        capture-manifest.json \
        > SHA256SUMS
)

chmod 0600 "$CHECKSUMS"


printf '\nSHA-256 manifest:\n'
cat "$CHECKSUMS"

printf '\nCapture saved:\n'
printf '  %s\n' "$CAPTURE_DIR"

printf '\nObserver: '
systemctl is-active "$OBSERVER_SERVICE" || true

printf 'Gateway:  '
systemctl is-active "$GATEWAY_SERVICE" || true

printf '\n'

CURRENT_STAGE="complete"
echo "Capture completed successfully."
