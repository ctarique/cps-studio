"""Strict preparation of the documented C++ experiment subset; never executes source."""
import hashlib
import re

class SourceError(ValueError):
    pass

def prepare(source):
    if not isinstance(source, str) or not 1 <= len(source) <= 2048:
        raise SourceError("SOURCE_SIZE")
    if not source.isascii():
        raise SourceError("SOURCE_ASCII")
    match = re.fullmatch(r"\s*void\s+experiment\s*\(\s*\)\s*\{(.*?)\}\s*", source, re.S)
    if not match:
        raise SourceError("SOURCE_GRAMMAR")
    body = match[1]
    ops, total, end, has_led = [], 0, 0, False
    call = re.compile(r"\s*(led|wait_ms|status)\s*\(\s*([0-9]*)\s*\)\s*;")
    while end < len(body):
        if not body[end:].strip():
            break
        m = call.match(body, end)
        if not m:
            raise SourceError("SOURCE_GRAMMAR")
        fn, arg = m[1], m[2]
        if fn == "status":
            if arg:
                raise SourceError("STATUS_ARGUMENT")
            op = "S0"
        elif fn == "led":
            if arg not in ("0", "1"):
                raise SourceError("LED_ARGUMENT")
            has_led = True
            op = "L" + arg
        else:
            if not re.fullmatch(r"[1-9][0-9]{1,3}", arg) or not 10 <= int(arg) <= 1000:
                raise SourceError("WAIT_RANGE")
            total += int(arg)
            op = "W" + arg
        ops.append(op)
        end = m.end()
        if len(ops) > 32 or total > 5000:
            raise SourceError("PROGRAM_LIMIT")
    if not ops:
        raise SourceError("EMPTY_PROGRAM")
    led_ops = [op for op in ops if op.startswith("L")]
    if led_ops and led_ops[-1] != "L0":
        raise SourceError("FINAL_LED_MUST_BE_OFF")
    encoded = ",".join(ops)
    return {"bytecode": encoded, "sha256": hashlib.sha256(encoded.encode()).hexdigest(),
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "steps": len(ops), "duration_ms": total, "uses_led": has_led,
            "preparation_kind": "bounded_cpp_subset_to_interaction_program"}
