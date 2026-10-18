"""Local non-physical Sentinel-CPS simulator."""

import fcntl
import logging
import os
import secrets
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from gateway.app import create_app
from gateway.config import Config
from waitress import serve

os.umask(0o077)

local = root / ".local"

if local.is_symlink():
    raise SystemExit("Private home state cannot be a symlink.")

local.mkdir(mode=0o700, exist_ok=True)
local.chmod(0o700)

envfile = local / "home.env"

if envfile.is_symlink():
    raise SystemExit("Private credential file cannot be a symlink.")

values = {}

if envfile.exists():
    for line in envfile.read_text().splitlines():
        if not line.strip():
            continue
        if "=" not in line:
            raise SystemExit("Invalid private credential file.")
        key, value = line.split("=", 1)
        values[key] = value

required = (
    "SENTINEL_ADMIN_TOKEN",
    "SENTINEL_DEVICE_KEY",
    "SENTINEL_CAR_DEVICE_KEY",
)

for key in required:
    if not values.get(key):
        values[key] = secrets.token_hex(32)

# Rewrite only the credentials still used by the current architecture.
with envfile.open("w") as private_file:
    for key in required:
        private_file.write(f"{key}={values[key]}\n")

envfile.chmod(0o600)

config = Config(
    data_dir=local / "evidence",
    admin_token=values["SENTINEL_ADMIN_TOKEN"],
    device_key=values["SENTINEL_DEVICE_KEY"],
    car_device_key="",
)

# A process lock prevents a second simulator instance from using
# the same evidence ledger simultaneously.
lock = (local / ".instance.lock").open("a")
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

app = create_app(config)

print(
    "NON_PHYSICAL simulator: http://127.0.0.1:8080",
    flush=True,
)
print(
    "Open .local/home.env privately if you need the administrator credential. "
    "Do not share that file.",
    flush=True,
)

logging.getLogger("waitress").setLevel(logging.CRITICAL)

serve(
    app,
    host="127.0.0.1",
    port=8080,
    threads=4,
    max_request_body_size=4096,
    max_request_header_size=4096,
    connection_limit=32,
    channel_timeout=15,
    ident="",
    clear_untrusted_proxy_headers=True,
    trusted_proxy="127.0.0.1",
    trusted_proxy_headers={"x-forwarded-proto"},
)
