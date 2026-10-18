"""SCPS1 wire format. No raw device fields escape the strict response parser."""
import hashlib
import hmac
import re
HEX32 = re.compile(r"[0-9a-f]{32}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
STATES={"IDLE","RUNNING","COMPLETE","STOPPED"}
MAX_COMMAND_SEQUENCE=99999998
def sign(key,context,body):
    return hmac.new(bytes.fromhex(key),context.encode()+body,hashlib.sha256).hexdigest()
def verify(key,context,body,signature):
    return bool(isinstance(signature,str) and HEX64.fullmatch(signature)
                and hmac.compare_digest(sign(key,context,body),signature))
def parse_status(body):
    if len(body)>384:raise ValueError("RESPONSE_SIZE")
    fields=body.decode("ascii").split("|")
    if len(fields)!=9:raise ValueError("RESPONSE_SCHEMA")
    ver,boot,seq,rid,state,led,enabled,digest,origin=fields
    if (ver!="SCPS1" or not HEX32.fullmatch(boot) or not re.fullmatch(r"[1-9][0-9]{0,8}",seq)
        or not HEX32.fullmatch(rid) or state not in STATES or led not in ("0","1")
        or enabled not in ("0","1") or not HEX64.fullmatch(digest) or origin not in ("DEVICE","SIMULATOR")):
        raise ValueError("RESPONSE_SCHEMA")
    if led=="1" and (state!="RUNNING" or enabled!="1"):
        raise ValueError("RESPONSE_INCONSISTENT")
    return {"boot":boot,"next_seq":int(seq),"run_id":rid,"state":state,
            "led_reported":int(led),"gpio_enabled":enabled=="1","program_sha256":digest,"origin":origin}
def work(boot,seq,rid,action,program=""):
    if not HEX32.fullmatch(boot) or not HEX32.fullmatch(rid) or action not in ("RUN","STOP","RESET"):
        raise ValueError("WORK_SCHEMA")
    return f"SCPS1|{boot}|{seq}|{rid}|{action}|{program}".encode()

CAR_ACTIONS={"MOTOR_A_TEST","MOTOR_A_CW_TEST","MOTOR_A_CCW_TEST","MOTOR_B_TEST","MOTOR_B_CW_TEST","MOTOR_B_CCW_TEST","STOP"}
CAR_REPORTED_ACTIONS=CAR_ACTIONS|{"NONE"}
CAR_STATES={"IDLE","RUNNING","COMPLETE","STOPPED","FAULT"}

def parse_car_status(body):
    if len(body)>384:
        raise ValueError("RESPONSE_SIZE")

    fields=body.decode("ascii").split("|")

    if len(fields)!=14:
        raise ValueError("RESPONSE_SCHEMA")

    (ver,profile,boot,seq,rid,state,last_action,
     motor_a,motor_b,ldr32,ldr33,camera,rssi,origin)=fields

    if (ver!="SCPS1" or profile!="CAR"
        or not HEX32.fullmatch(boot)
        or not re.fullmatch(r"[1-9][0-9]{0,8}",seq)
        or not HEX32.fullmatch(rid)
        or state not in CAR_STATES
        or last_action not in CAR_REPORTED_ACTIONS
        or motor_a not in ("0","1")
        or motor_b not in ("0","1")
        or camera not in ("0","1")
        or origin not in ("DEVICE","SIMULATOR")):
        raise ValueError("RESPONSE_SCHEMA")

    next_seq=int(seq)

    if not 1 <= next_seq <= 99999999:
        raise ValueError("RESPONSE_SCHEMA")

    if not re.fullmatch(r"(0|[1-9][0-9]{0,3})",ldr32):
        raise ValueError("RESPONSE_SCHEMA")

    if not re.fullmatch(r"(0|[1-9][0-9]{0,3})",ldr33):
        raise ValueError("RESPONSE_SCHEMA")

    ldr32_value=int(ldr32)
    ldr33_value=int(ldr33)

    if ldr32_value>4095 or ldr33_value>4095:
        raise ValueError("RESPONSE_SCHEMA")

    if not re.fullmatch(r"-?(0|[1-9][0-9]{0,2})",rssi):
        raise ValueError("RESPONSE_SCHEMA")

    rssi_value=int(rssi)

    if not -127 <= rssi_value <= 0:
        raise ValueError("RESPONSE_SCHEMA")

    # A completed, stopped, idle, or faulted report must not claim
    # that either motor remains energized.
    if state in ("IDLE","COMPLETE","STOPPED","FAULT") and (
        motor_a!="0" or motor_b!="0"
    ):
        raise ValueError("RESPONSE_INCONSISTENT")

    return {
        "boot":boot,
        "next_seq":next_seq,
        "run_id":rid,
        "state":state,
        "last_action":last_action,
        "motor_a_active":motor_a=="1",
        "motor_b_active":motor_b=="1",
        "ldr32":ldr32_value,
        "ldr33":ldr33_value,
        "camera_ready":camera=="1",
        "rssi_dbm":rssi_value,
        "origin":origin,
    }

def car_work(boot,seq,rid,action):
    if (not HEX32.fullmatch(boot)
        or not HEX32.fullmatch(rid)
        or type(seq) is not int
        or not 1 <= seq <= MAX_COMMAND_SEQUENCE
        or action not in CAR_ACTIONS):
        raise ValueError("CAR_WORK_SCHEMA")

    return f"SCPS1|CAR|{boot}|{seq}|{rid}|{action}".encode()
