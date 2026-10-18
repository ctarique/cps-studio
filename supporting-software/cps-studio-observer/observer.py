#!/usr/bin/python3

import argparse
import ctypes
import datetime
import ipaddress
import json
import os
import uuid
import signal
import socket
import struct
import subprocess
from pathlib import Path


OBSERVER_VERSION = "0.1.3"
LOSS_ACCOUNTING = "bcc_perf_lost_callback_and_submit_failures"
observation_id = str(uuid.uuid4())
lost_events = 0
events_received = 0
decode_errors = 0
collection_error = False
stop_reason = "error"
bpf = None

DEVICE_PORT = 80


parser = argparse.ArgumentParser()

parser.add_argument(
    "--service",
    default="sentinel-cps-final.service",
)

parser.add_argument(
    "--output",
    type=Path,
    required=True,
)

parser.add_argument(
    "--cam-ip",
    type=ipaddress.IPv4Address,
    required=True,
    help="Configured ESP32-CAM IPv4 address.",
)

parser.add_argument(
    "--car-ip",
    type=ipaddress.IPv4Address,
    required=True,
    help="Configured ESP32-WROVER IPv4 address.",
)

args = parser.parse_args()

if args.cam_ip == args.car_ip:
    parser.error("--cam-ip and --car-ip must differ")

CAM_IP = str(args.cam_ip)
CAR_IP = str(args.car_ip)

from bcc import BPF


def utc_now():
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def control_group_for_service(service):
    value = subprocess.check_output(
        [
            "/usr/bin/systemctl",
            "show",
            "--property=ControlGroup",
            "--value",
            service,
        ],
        text=True,
    ).strip()

    if not value or value == "/":
        raise RuntimeError(
            f"No active control group for {service}"
        )

    return value


control_group = control_group_for_service(
    args.service
)

cgroup_path = (
    Path("/sys/fs/cgroup")
    / control_group.lstrip("/")
)

if not cgroup_path.is_dir():
    raise SystemExit(
        f"Gateway cgroup does not exist: {cgroup_path}"
    )

target_cgroup_id = cgroup_path.stat().st_ino


BPF_PROGRAM = r"""
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>
#include <uapi/linux/in.h>

#define EVENT_CONNECT 1
#define EVENT_EXEC    2

struct event_t {
    u64 ts_ns;
    u64 cgroup_id;

    u32 tgid;
    u32 pid;
    u32 uid;
    u32 kind;

    u16 family;
    u16 dport;
    u32 daddr;

    char comm[TASK_COMM_LEN];
};

BPF_PERF_OUTPUT(events);
BPF_ARRAY(submit_failures, u64, 1);

/* A terminal failed submission may have no subsequent perf-loss notification. */
static __always_inline void count_submit_failure(void)
{
    u32 key = 0;
    u64 *count = submit_failures.lookup(&key);
    if (count)
        __sync_fetch_and_add(count, 1);
}


static __always_inline int target_cgroup(void)
{
    return (
        bpf_get_current_cgroup_id()
        == TARGET_CGROUP_ID
    );
}

TRACEPOINT_PROBE(syscalls, sys_enter_connect)
{
    if (!target_cgroup())
        return 0;

    if (args->uservaddr == 0)
        return 0;

    struct sockaddr_in addr4 = {};

    if (args->addrlen < sizeof(addr4))
        return 0;

    if (bpf_probe_read_user(
            &addr4,
            sizeof(addr4),
            (void *)args->uservaddr) < 0)
        return 0;

    if (addr4.sin_family != AF_INET)
        return 0;

    u64 id = bpf_get_current_pid_tgid();

    struct event_t event = {};

    event.ts_ns = bpf_ktime_get_ns();
    event.cgroup_id =
        bpf_get_current_cgroup_id();

    event.tgid = id >> 32;
    event.pid = (u32)id;
    event.uid =
        (u32)bpf_get_current_uid_gid();

    event.kind = EVENT_CONNECT;

    event.family = addr4.sin_family;
    event.dport = addr4.sin_port;
    event.daddr = addr4.sin_addr.s_addr;

    bpf_get_current_comm(
        &event.comm,
        sizeof(event.comm)
    );

    if (events.perf_submit(
            args,
            &event,
            sizeof(event)
        ) < 0)
        count_submit_failure();

    return 0;
}

/*
 * sched_process_exec occurs after a successful exec.
 * Failed PATH candidates therefore do not create
 * false execution events.
 */
TRACEPOINT_PROBE(sched, sched_process_exec)
{
    if (!target_cgroup())
        return 0;

    u64 id = bpf_get_current_pid_tgid();

    struct event_t event = {};

    event.ts_ns = bpf_ktime_get_ns();
    event.cgroup_id =
        bpf_get_current_cgroup_id();

    event.tgid = id >> 32;
    event.pid = (u32)id;
    event.uid =
        (u32)bpf_get_current_uid_gid();

    event.kind = EVENT_EXEC;

    bpf_get_current_comm(
        &event.comm,
        sizeof(event.comm)
    );

    if (events.perf_submit(
            args,
            &event,
            sizeof(event)
        ) < 0)
        count_submit_failure();

    return 0;
}
""".replace(
    "TARGET_CGROUP_ID",
    str(target_cgroup_id),
)


class Event(ctypes.Structure):
    _fields_ = [
        (
            "ts_ns",
            ctypes.c_ulonglong,
        ),
        (
            "cgroup_id",
            ctypes.c_ulonglong,
        ),

        ("tgid", ctypes.c_uint),
        ("pid", ctypes.c_uint),
        ("uid", ctypes.c_uint),
        ("kind", ctypes.c_uint),

        ("family", ctypes.c_ushort),
        ("dport", ctypes.c_ushort),
        ("daddr", ctypes.c_uint),

        ("comm", ctypes.c_char * 16),
    ]


args.output.parent.mkdir(
    parents=True,
    exist_ok=True,
)

output = args.output.open(
    "a",
    encoding="utf-8",
    buffering=1,
)


def decode_c_string(value):
    return (
        bytes(value)
        .split(b"\x00", 1)[0]
        .decode(
            "utf-8",
            errors="replace",
        )
    )


def emit(record):
    record.setdefault("observation_id", observation_id)
    line = json.dumps(
        record,
        separators=(",", ":"),
        sort_keys=True,
    )

    output.write(line + "\n")
    output.flush()

    if record.get("expected") is False:
        print(
            line,
            flush=True,
        )


def classify_connect(ip, port):
    if (
        ip == CAM_IP
        and port == DEVICE_PORT
    ):
        return (
            "ESP32-CAM",
            "EXPECTED_DEVICE",
            True,
        )

    if (
        ip == CAR_IP
        and port == DEVICE_PORT
    ):
        return (
            "ESP32-WROVER",
            "EXPECTED_DEVICE",
            True,
        )

    if ip.startswith("127."):
        return (
            "LOOPBACK",
            "EXPECTED_LOCAL",
            True,
        )

    return (
        "OTHER",
        "UNEXPECTED_DESTINATION",
        False,
    )


def classify_exec(process):
    if process == "ip":
        return (
            "EXPECTED_ROUTE_TOOL",
            True,
        )

    return (
        "UNEXPECTED_EXEC",
        False,
    )


emit({
    "timestamp": utc_now(),
    "event_type": "observer_start",
    "observer_version": OBSERVER_VERSION,
    "source": "observer",
    "service": args.service,
    "control_group": control_group,
    "cgroup_id": target_cgroup_id,
})


def _handle_event(cpu, data, size):
    global events_received
    if size != ctypes.sizeof(Event):
        raise ValueError("invalid eBPF event size")
    event = ctypes.cast(
        data,
        ctypes.POINTER(Event),
    ).contents

    process = decode_c_string(
        event.comm
    )

    common = {
        "timestamp": utc_now(),
        "observer_version":
            OBSERVER_VERSION,
        "source": "ebpf",
        "service": args.service,
        "cgroup_id":
            event.cgroup_id,
        "tgid": event.tgid,
        "pid": event.pid,
        "uid": event.uid,
        "process": process,
    }

    if event.kind == 1:
        ip = socket.inet_ntoa(
            struct.pack(
                "=I",
                event.daddr,
            )
        )

        port = socket.ntohs(
            event.dport
        )

        (
            asset,
            classification,
            expected,
        ) = classify_connect(
            ip,
            port,
        )

        emit({
            **common,
            "event_type": "connect",
            "protocol": "tcp",
            "destination_ip": ip,
            "destination_port": port,
            "asset": asset,
            "classification":
                classification,
            "expected": expected,
        })

    elif event.kind == 2:
        (
            classification,
            expected,
        ) = classify_exec(
            process
        )

        emit({
            **common,
            "event_type":
                "exec_success",
            "classification":
                classification,
            "expected":
                expected,
        })


    else:
        raise ValueError("unknown eBPF event kind")

    events_received += 1


def handle_event(cpu, data, size):
    global decode_errors, collection_error
    try:
        _handle_event(cpu, data, size)
    except Exception:
        # ctypes callbacks must not hide parse/write failures from capture quality.
        decode_errors += 1
        collection_error = True
        emit({
            "timestamp": utc_now(),
            "event_type": "observer_event_error",
            "observer_version": OBSERVER_VERSION,
            "source": "observer",
            "decode_errors": decode_errors,
        })


def handle_loss(cpu, lost):
    global lost_events, collection_error
    count = int(lost)
    if count < 0:
        collection_error = True
        return
    lost_events += count
    emit({
        "timestamp": utc_now(),
        "event_type": "observer_loss",
        "observer_version": OBSERVER_VERSION,
        "source": "observer",
        "cpu": int(cpu),
        "lost_events": lost_events,
        "loss_count": count,
    })


def submission_failures():
    if bpf is None:
        return None
    return int(bpf["submit_failures"][ctypes.c_int(0)].value)


def quality_metadata(buffers_drained=False):
    return {
        "loss_accounting": LOSS_ACCOUNTING,
        "lost_events": lost_events,
        "submit_failures": submission_failures(),
        "events_received": events_received,
        "decode_errors": decode_errors,
        "collection_error": collection_error,
        "buffers_drained": buffers_drained,
    }


running = True


def stop_handler(signum, frame):
    global running, stop_reason
    running = False
    stop_reason = "signal" 


signal.signal(
    signal.SIGTERM,
    stop_handler,
)

signal.signal(
    signal.SIGINT,
    stop_handler,
)


print(
    "CPS Studio Observer "
    f"{OBSERVER_VERSION}: "
    "loading eBPF probes for "
    f"{control_group} "
    f"(cgroup_id={target_cgroup_id})",
    flush=True,
)

# Every loaded run receives an identity and measured cumulative counters.
# Detach before the final drain so the stop record covers a closed producer.
buffers_drained = False
observation_end = None
try:
    bpf = BPF(text=BPF_PROGRAM)
    bpf["events"].open_perf_buffer(handle_event, lost_cb=handle_loss)

    emit({
        "timestamp": utc_now(),
        "event_type": "observer_ready",
        "observer_version": OBSERVER_VERSION,
        "source": "observer",
        "service": args.service,
        "control_group": control_group,
        "cgroup_id": target_cgroup_id,
        **quality_metadata(),
    })
    print("CPS Studio Observer: active", flush=True)

    while running:
        bpf.perf_buffer_poll(timeout=500)

except Exception:
    collection_error = True
    raise

finally:
    if bpf is not None:
        # Coverage ends while both probes are still attached, before drain time.
        observation_end = utc_now()
        try:
            bpf.detach_tracepoint(tp="syscalls:sys_enter_connect")
            bpf.detach_tracepoint(tp="sched:sched_process_exec")
            bpf.perf_buffer_consume()
            buffers_drained = True
        except Exception:
            collection_error = True
    try:
        emit({
            "timestamp": utc_now(),
            "event_type": "observer_stop",
            "observer_version": OBSERVER_VERSION,
            "source": "observer",
            "service": args.service,
            "stop_reason": stop_reason,
            "observation_end": observation_end,
            **quality_metadata(buffers_drained=buffers_drained),
        })
        os.fsync(output.fileno())
    finally:
        output.close()
        if bpf is not None:
            bpf.cleanup()
