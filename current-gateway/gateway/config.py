import hashlib
import hmac
import ipaddress
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

TOKEN_RE = re.compile(r"\A[0-9a-f]{64}\Z")
# Validation contract reused from the historical operator_token.py.
def valid_token(value):
    return isinstance(value, str) and TOKEN_RE.fullmatch(value) is not None

@dataclass(frozen=True)
class Config:
    data_dir: Path
    admin_token: str = field(default="", repr=False)
    device_key: str = field(default="", repr=False)
    car_device_key: str = field(default="", repr=False)
    mode: str = "simulator"
    device_host: str = field(default="127.0.0.1", repr=False)
    device_port: int = 80
    car_device_host: str = field(default="", repr=False)
    car_device_port: int = 80
    wifi_interface: str = "wlan0"
    config_label: str = "LAB-CONFIG-001"
    max_runs: int = 500
    max_events: int = 20000
    timeout: float = 2.0
    led_policy_max_steps: int = 32
    led_policy_max_duration_ms: int = 5000
    led_policy_allow_led: bool = True

    def __post_init__(self):
        if not all(valid_token(x) for x in (self.admin_token,self.device_key)):
            raise ValueError("CONFIG_CREDENTIALS_REQUIRED")
        if hmac.compare_digest(self.admin_token,self.device_key):
            raise ValueError("CONFIG_CREDENTIALS_MUST_DIFFER")

        car_host_configured=bool(self.car_device_host)
        car_key_configured=bool(self.car_device_key)

        if car_host_configured != car_key_configured:
            raise ValueError("CONFIG_CAR_INCOMPLETE")

        if car_key_configured:
            if not valid_token(self.car_device_key):
                raise ValueError("CONFIG_CAR_CREDENTIAL")
            if (hmac.compare_digest(self.car_device_key,self.admin_token)
                    or hmac.compare_digest(self.car_device_key,self.device_key)):
                raise ValueError("CONFIG_CREDENTIALS_MUST_DIFFER")
        if type(self.led_policy_max_steps) is not int or not 1 <= self.led_policy_max_steps <= 32:
            raise ValueError("CONFIG_LED_POLICY")
        if type(self.led_policy_max_duration_ms) is not int or not 0 <= self.led_policy_max_duration_ms <= 5000:
            raise ValueError("CONFIG_LED_POLICY")
        if type(self.led_policy_allow_led) is not bool:
            raise ValueError("CONFIG_LED_POLICY")
        if self.mode not in ("simulator", "simulator_http", "wifi"):
            raise ValueError("CONFIG_TRANSPORT")
        address = ipaddress.IPv4Address(self.device_host)
        networks = ("10.0.0.0/8","172.16.0.0/12","192.168.0.0/16")
        if self.mode == "wifi" and not any(address in ipaddress.ip_network(n) for n in networks):
            raise ValueError("CONFIG_PRIVATE_DEVICE_REQUIRED")
        if self.mode != "wifi" and not address.is_loopback:
            raise ValueError("CONFIG_SIMULATOR_LOOPBACK_REQUIRED")

        if car_host_configured:
            car_address=ipaddress.IPv4Address(self.car_device_host)
            if self.mode!="wifi":
                raise ValueError("CONFIG_CAR_WIFI_ONLY")
            if not any(car_address in ipaddress.ip_network(n) for n in networks):
                raise ValueError("CONFIG_PRIVATE_CAR_REQUIRED")
            if car_address==address:
                raise ValueError("CONFIG_DEVICE_HOSTS_MUST_DIFFER")
        if not re.fullmatch(r"wlan[0-9]",self.wifi_interface):
            raise ValueError("CONFIG_WIFI_INTERFACE")
        if not re.fullmatch(r"LAB-CONFIG-[0-9]{3}",self.config_label):
            raise ValueError("CONFIG_REFERENCE")
        if type(self.device_port) is not int or not 1 <= self.device_port <= 65535:
            raise ValueError("CONFIG_PORT")
        if type(self.car_device_port) is not int or not 1 <= self.car_device_port <= 65535:
            raise ValueError("CONFIG_CAR_PORT")
        if type(self.max_runs) is not int or not 1 <= self.max_runs <= 10000:
            raise ValueError("CONFIG_QUOTA")
        if type(self.max_events) is not int or not 100 <= self.max_events <= 200000:
            raise ValueError("CONFIG_QUOTA")
        if type(self.timeout) not in (int,float) or not 0.1 <= self.timeout <= 3:
            raise ValueError("CONFIG_TIMEOUT")

    @property
    def reference(self):
        # Private routing/credentials are not public evidence. A fixed private deployment
        # file is retained separately by the instructor under this configuration label.
        spec = {"label":self.config_label,"mode":self.mode,"experiment":"led-status-v1",
                "protocol":1,"source_limit":2048,"steps":32,"duration_ms":5000,
                "workflow_version":10,"device_profile":"esp32-cam",
                "policy":{"steps":self.led_policy_max_steps,"duration_ms":self.led_policy_max_duration_ms,"allow_led":self.led_policy_allow_led},
                "timeout":float(self.timeout),"max_runs":self.max_runs,"max_events":self.max_events}
        private_binding = hmac.new(bytes.fromhex(self.device_key),
            f"{self.device_host}|{self.device_port}|{self.wifi_interface}".encode(),hashlib.sha256).hexdigest()
        spec["private_binding"] = private_binding
        if self.car_device_host:
            spec["car_private_binding"] = hmac.new(
                bytes.fromhex(self.car_device_key),
                f"{self.car_device_host}|{self.car_device_port}|{self.wifi_interface}".encode(),
                hashlib.sha256
            ).hexdigest()
        return self.config_label + "-" + hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()[:12]

def load_config(path):
    data = json.loads(Path(path).read_text())
    allowed = {"mode","device_host","device_port","car_device_host","car_device_port","wifi_interface","config_label","max_runs","max_events","timeout","led_policy_max_steps","led_policy_max_duration_ms","led_policy_allow_led"}
    if not isinstance(data,dict) or set(data)-allowed:
        raise ValueError("CONFIG_SCHEMA")
    return Config(data_dir=Path(os.environ["SENTINEL_DATA_DIR"]),
                  admin_token=os.environ.get("SENTINEL_ADMIN_TOKEN",""),
                  device_key=os.environ.get("SENTINEL_DEVICE_KEY",""),
                  car_device_key=os.environ.get("SENTINEL_CAR_DEVICE_KEY",""),**data)
