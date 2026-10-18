#!/usr/bin/python3

import argparse
import datetime
import json
import ipaddress
from collections import defaultdict
from pathlib import Path


ANALYTICS_VERSION = "0.1.2"
EXPECTED_OBSERVER_VERSION = "0.1.3"
SUPPORTED_OBSERVER_VERSIONS = {"0.1.2", EXPECTED_OBSERVER_VERSION}
LOSS_ACCOUNTING = "bcc_perf_lost_callback_and_submit_failures"


parser = argparse.ArgumentParser()

parser.add_argument(
    "--input",
    type=Path,
    required=True,
)

parser.add_argument(
    "--output",
    type=Path,
    required=True,
)

parser.add_argument(
    "--window-seconds",
    type=int,
    default=10,
)

args = parser.parse_args()


if args.input.resolve() == args.output.resolve():
    raise SystemExit("input and output must be different files")

if args.window_seconds <= 0:
    raise SystemExit(
        "window-seconds must be greater than zero"
    )


UTC = datetime.timezone.utc

WINDOW_DELTA = datetime.timedelta(
    seconds=args.window_seconds
)


def parse_timestamp(value):
    timestamp = datetime.datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    if timestamp.tzinfo is None:
        raise ValueError(
            "timestamp has no timezone"
        )

    return timestamp.astimezone(UTC)


def iso_z(value):
    return (
        value.astimezone(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def floor_window_start(timestamp):
    epoch = int(timestamp.timestamp())

    start_epoch = (
        epoch // args.window_seconds
    ) * args.window_seconds

    return datetime.datetime.fromtimestamp(
        start_epoch,
        tz=UTC,
    )


def first_complete_window_start(ready):
    start = floor_window_start(ready)

    if start < ready:
        start += WINDOW_DELTA

    return start


all_events = []

invalid_json = 0
invalid_timestamp = 0
wrong_version = 0
invalid_event = 0
invalid_lifecycle = 0

# A failed re-analysis must not leave stale complete features at the output path.
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text("", encoding="utf-8")

with args.input.open(
    "r",
    encoding="utf-8",
) as source:

    for number, line in enumerate(
        source,
        start=1,
    ):
        line = line.strip()

        if not line:
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            invalid_json += 1
            print(
                f"Skipping invalid JSON line {number}"
            )
            continue

        if not isinstance(event, dict):
            invalid_json += 1
            print(f"Skipping non-object JSON line {number}")
            continue

        if (not isinstance(event.get("observer_version"), str)
                or event["observer_version"] not in SUPPORTED_OBSERVER_VERSIONS):
            wrong_version += 1
            continue

        try:
            event["_timestamp"] = parse_timestamp(
                event["timestamp"]
            )
        except Exception:
            invalid_timestamp += 1
            print(
                f"Skipping invalid timestamp line {number}"
            )
            continue

        kind = event.get("event_type")
        try:
            if kind not in {"observer_start", "observer_ready", "observer_stop",
                            "observer_loss", "observer_event_error", "connect", "exec_success"}:
                raise ValueError("unknown event type")
            if kind == "observer_loss":
                if not all(type(event.get(field)) is int and event[field] >= 0
                           for field in ("cpu", "lost_events", "loss_count")):
                    raise ValueError("invalid loss metadata")
                if not isinstance(event.get("observation_id"), str) or not event["observation_id"]:
                    raise ValueError("missing loss observation identity")
            if kind in {"connect", "exec_success"}:
                if type(event.get("expected")) is not bool:
                    raise ValueError("invalid expected flag")
                if event.get("observer_version") == EXPECTED_OBSERVER_VERSION:
                    if not isinstance(event.get("observation_id"), str) or not event["observation_id"]:
                        raise ValueError("missing observation identity")
                if kind == "connect":
                    ipaddress.IPv4Address(event["destination_ip"])
                    port = event["destination_port"]
                    if type(port) is not int or not 0 <= port <= 65535:
                        raise ValueError("invalid destination port")
                    if event.get("asset") not in {"ESP32-CAM", "ESP32-WROVER", "LOOPBACK", "OTHER"}:
                        raise ValueError("invalid asset")
                    classification = event.get("classification")
                    if classification not in {"EXPECTED_DEVICE", "EXPECTED_LOCAL", "UNEXPECTED_DESTINATION"}:
                        raise ValueError("invalid connection classification")
                    allowed_assets = {
                        "EXPECTED_DEVICE": {"ESP32-CAM", "ESP32-WROVER"},
                        "EXPECTED_LOCAL": {"LOOPBACK"},
                        "UNEXPECTED_DESTINATION": {"OTHER"},
                    }
                    if (event["asset"] not in allowed_assets[classification]
                            or event["expected"] is not (classification != "UNEXPECTED_DESTINATION")):
                        raise ValueError("inconsistent connection classification")
                else:
                    if event.get("classification") not in {"EXPECTED_ROUTE_TOOL", "UNEXPECTED_EXEC"}:
                        raise ValueError("invalid exec classification")
                    if event["expected"] is not (event["classification"] == "EXPECTED_ROUTE_TOOL"):
                        raise ValueError("inconsistent exec classification")
                    if not isinstance(event.get("process"), str) or not event["process"]:
                        raise ValueError("missing exec process")
        except (KeyError, TypeError, ValueError):
            invalid_event += 1
            print(f"Skipping invalid event line {number}")
            continue

        all_events.append(event)


if not all_events:
    raise SystemExit(
        "No usable supported Observer telemetry found."
    )


all_events.sort(
    key=lambda event: event["_timestamp"]
)


#
# A complete observation interval begins only after
# observer_ready and ends at observer_stop.
#
# observer_start is deliberately not used because
# BCC/eBPF compilation and loading occur after it.
#
intervals = []

ready = None

for event in all_events:
    event_type = event.get("event_type")
    timestamp = event["_timestamp"]

    if event_type == "observer_ready":
        if ready is not None:
            invalid_lifecycle += 1
        ready = event

    elif event_type == "observer_stop":
        if (
            ready is not None
            and timestamp > ready["_timestamp"]
        ):
            intervals.append(
                (ready, event)
            )

        else:
            invalid_lifecycle += 1
        ready = None

if ready is not None:
    invalid_lifecycle += 1

parse_valid = not (invalid_json or invalid_timestamp or wrong_version or invalid_event or invalid_lifecycle)


data_events = [
    event
    for event in all_events
    if event.get("event_type") in {
        "connect",
        "exec_success",
    }
]


records = []

events_used = 0


def nonnegative_integer(value):
    return type(value) is int and value >= 0


def interval_quality(ready_event, stop_event):
    # Historical absent measurements are unknown, never inferred as zero.
    fields = ("lost_events", "submit_failures", "events_received")
    metadata = {
        "telemetry_quality_schema": 1,
        "window_temporal_coverage": True,
        "telemetry_parse_valid": parse_valid,
        "telemetry_loss_accounting": "unknown",
        "telemetry_lost_events": None,
        "telemetry_submit_failures": None,
        "observation_id": ready_event.get("observation_id"),
        "telemetry_lifecycle_valid": False,
        "telemetry_timing_valid": False,
        "telemetry_timing_reason": "observation_coverage_unknown_or_invalid",
        "observation_end": None,
    }
    known_ready = ready_event.get("loss_accounting")
    known_stop = stop_event.get("loss_accounting")
    if known_ready is None and known_stop is None:
        return metadata
    if stop_event.get("observation_end") is None:
        # An absent coverage cutoff cannot be reconstructed from final drain time.
        return metadata
    try:
        observation_end = parse_timestamp(stop_event["observation_end"])
    except (KeyError, TypeError, AttributeError, ValueError):
        metadata["telemetry_loss_accounting"] = "invalid"
        return metadata
    valid = (
        ready_event["_timestamp"] < observation_end <= stop_event["_timestamp"]
        and
        known_ready == known_stop == LOSS_ACCOUNTING
        and ready_event.get("observer_version") == stop_event.get("observer_version") == EXPECTED_OBSERVER_VERSION
        and isinstance(metadata["observation_id"], str)
        and bool(metadata["observation_id"])
        and metadata["observation_id"] == stop_event.get("observation_id")
        and stop_event.get("buffers_drained") is True
        and stop_event.get("collection_error") is False
        and all(nonnegative_integer(row.get(field)) for row in (ready_event, stop_event) for field in fields)
        and all(stop_event[field] >= ready_event[field] for field in fields)
    )
    if not valid:
        metadata["telemetry_loss_accounting"] = "invalid"
        return metadata
    observed = [
        event for event in data_events
        if ready_event["_timestamp"] <= event["_timestamp"] < stop_event["_timestamp"]
    ]
    received = stop_event["events_received"] - ready_event["events_received"]
    if received != len(observed) or any(event.get("observation_id") != metadata["observation_id"] for event in observed):
        metadata["telemetry_loss_accounting"] = "invalid"
        return metadata
    if any(event.get("event_type") == "observer_event_error"
           and ready_event["_timestamp"] <= event["_timestamp"] <= stop_event["_timestamp"]
           for event in all_events):
        metadata["telemetry_loss_accounting"] = "invalid"
        return metadata
    losses = [
        event for event in all_events
        if event.get("event_type") == "observer_loss"
        and ready_event["_timestamp"] <= event["_timestamp"] <= stop_event["_timestamp"]
    ]
    previous = ready_event["lost_events"]
    for loss in losses:
        if (loss.get("observation_id") != metadata["observation_id"]
                or loss["lost_events"] < previous
                or loss["lost_events"] > stop_event["lost_events"]
                or loss["lost_events"] - previous != loss["loss_count"]):
            metadata["telemetry_loss_accounting"] = "invalid"
            return metadata
        previous = loss["lost_events"]
    metadata["observation_end"] = iso_z(observation_end)
    metadata["telemetry_loss_accounting"] = "known"
    metadata["telemetry_lost_events"] = stop_event["lost_events"] - ready_event["lost_events"]
    metadata["telemetry_submit_failures"] = stop_event["submit_failures"] - ready_event["submit_failures"]
    metadata["telemetry_lifecycle_valid"] = True
    # Receipt timestamps assigned during final drain cannot locate those events
    # inside acquisition coverage. Do not certify zero windows by excluding them.
    if any(not ready_event["_timestamp"] <= event["_timestamp"] < observation_end
           for event in observed):
        metadata["telemetry_lifecycle_valid"] = False
        metadata["telemetry_timing_reason"] = "receipt_outside_observation_coverage"
        return metadata
    metadata["telemetry_timing_valid"] = True
    metadata["telemetry_timing_reason"] = None
    return metadata


for capture_index, (ready_event, stop_event) in enumerate(intervals, start=1):
    interval_ready = ready_event["_timestamp"]
    interval_stop = stop_event["_timestamp"]
    quality = interval_quality(ready_event, stop_event)
    if quality["observation_end"] is not None:
        interval_stop = parse_timestamp(quality["observation_end"])
    complete = (
        quality["telemetry_parse_valid"]
        and quality["telemetry_lifecycle_valid"]
        and quality["telemetry_timing_valid"]
        and quality["telemetry_loss_accounting"] == "known"
        and quality["telemetry_lost_events"] == 0
        and quality["telemetry_submit_failures"] == 0
    )

    #
    # Group events by aligned 10-second windows.
    #
    grouped = defaultdict(list)

    for event in data_events:
        timestamp = event["_timestamp"]

        if not (
            interval_ready
            <= timestamp
            < interval_stop
        ):
            continue

        start = floor_window_start(
            timestamp
        )

        grouped[start].append(event)

    #
    # Emit every FULL aligned window contained
    # completely inside the ready->stop interval.
    #
    # This intentionally includes zero-event windows,
    # because complete inactivity is analytically
    # meaningful rather than "missing data."
    #
    start = first_complete_window_start(
        interval_ready
    )

    while (
        start + WINDOW_DELTA
        <= interval_stop
    ):
        end = start + WINDOW_DELTA

        window_events = grouped.get(
            start,
            [],
        )

        events_used += len(window_events)

        connects = [
            event
            for event in window_events
            if event.get("event_type")
            == "connect"
        ]

        execs = [
            event
            for event in window_events
            if event.get("event_type")
            == "exec_success"
        ]

        cam_connections = sum(
            1
            for event in connects
            if event.get("asset")
            == "ESP32-CAM"
        )

        car_connections = sum(
            1
            for event in connects
            if event.get("asset")
            == "ESP32-WROVER"
        )

        expected_device_connections = sum(
            1
            for event in connects
            if event.get("classification")
            == "EXPECTED_DEVICE"
        )

        expected_local_connections = sum(
            1
            for event in connects
            if event.get("classification")
            == "EXPECTED_LOCAL"
        )

        unexpected_connections = sum(
            1
            for event in connects
            if event.get("classification")
            == "UNEXPECTED_DESTINATION"
        )

        expected_route_execs = sum(
            1
            for event in execs
            if event.get("classification")
            == "EXPECTED_ROUTE_TOOL"
        )

        unexpected_execs = sum(
            1
            for event in execs
            if event.get("classification")
            == "UNEXPECTED_EXEC"
        )

        destinations = {
            (
                event.get("destination_ip"),
                event.get("destination_port"),
            )
            for event in connects
        }

        total_connections = len(
            connects
        )

        total_execs = len(
            execs
        )

        if max(
            cam_connections,
            car_connections,
        ) > 0:
            device_balance = (
                min(
                    cam_connections,
                    car_connections,
                )
                /
                max(
                    cam_connections,
                    car_connections,
                )
            )
        else:
            device_balance = 0.0

        record = {
            "analytics_version":
                ANALYTICS_VERSION,

            "observer_version":
                ready_event["observer_version"],

            **quality,

            "window_seconds":
                args.window_seconds,

            "window_complete":
                complete,

            "capture_index":
                capture_index,

            "observation_ready":
                iso_z(interval_ready),

            "observation_stop":
                iso_z(interval_stop),

            "window_start":
                iso_z(start),

            "window_end":
                iso_z(end),

            "cam_connections":
                cam_connections,

            "car_connections":
                car_connections,

            "expected_device_connections":
                expected_device_connections,

            "expected_local_connections":
                expected_local_connections,

            "unexpected_connections":
                unexpected_connections,

            "expected_route_execs":
                expected_route_execs,

            "unexpected_execs":
                unexpected_execs,

            "unique_destinations":
                len(destinations),

            "total_connections":
                total_connections,

            "total_execs":
                total_execs,

            "total_security_events":
                total_connections
                + total_execs,

            "device_balance":
                round(
                    device_balance,
                    4,
                ),
        }

        records.append(record)

        start = end


args.output.parent.mkdir(
    parents=True,
    exist_ok=True,
)

with args.output.open(
    "w",
    encoding="utf-8",
) as output:

    for record in records:
        output.write(
            json.dumps(
                record,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        )


print(
    "Observer-version events:",
    len(all_events),
)

print(
    "Security data events:",
    len(data_events),
)

print(
    "Complete observation intervals:",
    len(intervals),
)

for index, (ready_event, stop_event) in enumerate(intervals, start=1):
    interval_ready = ready_event["_timestamp"]
    interval_stop = stop_event["_timestamp"]
    duration = (
        interval_stop
        - interval_ready
    ).total_seconds()

    print(
        f"Interval {index}: "
        f"{iso_z(interval_ready)} -> "
        f"{iso_z(interval_stop)} "
        f"({duration:.3f}s)"
    )

print(
    "Completed full windows:",
    len(records),
)

print(
    "Events inside completed windows:",
    events_used,
)

print(
    "Boundary/non-window data events:",
    len(data_events) - events_used,
)

print(
    "Skipped wrong observer version:",
    wrong_version,
)

print(
    "Skipped invalid JSON:",
    invalid_json,
)

print(
    "Skipped invalid timestamps:",
    invalid_timestamp,
)

print(
    "Output:",
    args.output,
)

print("Invalid event records:", invalid_event)
print("Invalid lifecycle records:", invalid_lifecycle)
print("Quality-complete windows:", sum(row["window_complete"] for row in records))

# Keep diagnostic output for incomplete input, but never report capture success.
if not records or not all(row["window_complete"] for row in records):
    raise SystemExit("Telemetry is empty, incomplete, invalid, lost, or has unknown loss accounting.")
