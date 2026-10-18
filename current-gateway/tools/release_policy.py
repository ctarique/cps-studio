"""Release selection and template checks; private deployment state is never an input."""
import json
from pathlib import Path
import re

TOP = {"README.md", "VERSION", "requirements.lock", "THIRD_PARTY.md", ".gitignore"}
SUFFIXES = {
    "gateway": {".py", ".html", ".css", ".js"},
    "esp32": {".h", ".ino"},
    "tests": {".py", ".cpp", ".js"},
    "tools": {".py"},
    "deploy": {".sh", ".service", ".conf"},
    "docs": {".md", ".csv"},
    "examples": {".cpp"},
    "audit": {".md", ".csv", ".json", ".txt"},
    "verification": {".md", ".json", ".txt"},
    "wheelhouse": {".whl"},
}
CONFIG = {
    "ai-thinker-esp32cam-led.example.h", "gateway.env.example",
    "gateway.simulator-http.json", "gateway.simulator.json", "gateway.wifi.example.json",
}
FIRMWARE = {
    "sentinel_esp32": {
        "experiment.h",
        "response.h",
        "sentinel_config.example.h",
        "sentinel_esp32.ino",
    },
    "sentinel_car": {
        "car_engine.h",
        "response.h",
        "sentinel_car_config.example.h",
        "sentinel_car.ino",
    },
}
RASTER_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
RASTER_DIRECTORIES = {
    "device-icons",  # Approved transparent car PNG alongside existing SVG icons.
    "brand",
    "contact",
    "display-gallery",
    "experiment-images",
    "home-gallery",
    "home-gallery-sticker",
}
VECTOR_SUFFIXES = {".svg"}
VECTOR_DIRECTORIES = {"device-icons"}
PRIVATE_FIELDS = (
    "SENTINEL_WIFI_SSID",
    "SENTINEL_WIFI_PASSWORD",
    "SENTINEL_GATEWAY_IP",
    "SENTINEL_DEVICE_KEY",
)
HEADER_PRIVATE_FIELDS = {
    "esp32/sentinel_esp32/sentinel_config.example.h": PRIVATE_FIELDS,
    "config/ai-thinker-esp32cam-led.example.h": PRIVATE_FIELDS,
    "esp32/sentinel_car/sentinel_car_config.example.h": (
        "SENTINEL_WIFI_SSID",
        "SENTINEL_WIFI_PASSWORD",
        "SENTINEL_GATEWAY_IP",
        "SENTINEL_CAR_DEVICE_KEY",
    ),
}


def release_files(root):
    files = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        top = rel.parts[0]
        # Home credentials, evidence, virtual environments and their symlinks are excluded.
        if top not in SUFFIXES and top != "config" and str(rel) not in TOP:
            continue
        if "__pycache__" in rel.parts:
            continue
        if path.is_symlink():
            raise ValueError("Symlink in release inputs")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("Non-file release input")
        if any(part.startswith(".") for part in rel.parts) and str(rel) != ".gitignore":
            raise ValueError("Private file in release inputs")
        if path.name.endswith(".local.h"):
            raise ValueError("Private firmware configuration in release inputs")
        if top == "esp32":
            if (
                len(rel.parts) != 3
                or rel.parts[1] not in FIRMWARE
                or path.name not in FIRMWARE[rel.parts[1]]
            ):
                raise ValueError("Unexpected firmware file in release inputs")
        if top == "config":
            if len(rel.parts) != 2 or path.name not in CONFIG:
                raise ValueError("Unexpected configuration file in release inputs")
        elif (top == "gateway" and len(rel.parts) == 4 and rel.parts[1] == "static"
              and rel.parts[2] in RASTER_DIRECTORIES and path.suffix.lower() in RASTER_SUFFIXES):
            # These are reviewed raster presentation assets. Configuration,
            # database and arbitrary binary files remain outside release policy.
            pass
        elif (top == "gateway" and len(rel.parts) == 4 and rel.parts[1] == "static"
              and rel.parts[2] in VECTOR_DIRECTORIES and path.suffix.lower() in VECTOR_SUFFIXES):
            # Reviewed SVG presentation assets are restricted to explicit directories.
            pass
        elif str(rel) not in TOP and path.suffix not in SUFFIXES[top]:
            raise ValueError("Unexpected file type in release inputs")
        files.append(path)
    validate_templates(root)
    return sorted(files)


def validate_templates(root):
    for name, fields in HEADER_PRIVATE_FIELDS.items():
        text = (root / name).read_text()
        for field in fields:
            declarations = re.findall(r"static\s+const\s+char\s*\*\s*" + field +
                                      r'\s*=\s*"([^"]*)"\s*;', text)
            if declarations != [""]:
                raise ValueError("Firmware template must contain empty credentials")
    env = {}
    for line in (root / "config/gateway.env.example").read_text().splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            if key in env:
                raise ValueError("Duplicate environment template field")
            env[key] = value
    expected = {
        "SENTINEL_CONFIG": "/etc/sentinel-cps-final/gateway.json",
        "SENTINEL_DATA_DIR": "/var/lib/sentinel-cps-final",
        "SENTINEL_ADMIN_TOKEN": "REPLACE_WITH_DIFFERENT_64_LOWERCASE_HEX",
        "SENTINEL_DEVICE_KEY": "REPLACE_WITH_DIFFERENT_64_LOWERCASE_HEX",
        "SENTINEL_CAR_DEVICE_KEY": "REPLACE_WITH_DIFFERENT_64_LOWERCASE_HEX",
    }
    if env != expected:
        raise ValueError("Environment template must contain placeholders")
    expected_configs = {
        "gateway.simulator.json": {
            "mode": "simulator", "config_label": "LAB-CONFIG-001",
            "max_runs": 500, "max_events": 20000,
        },
        "gateway.simulator-http.json": {
            "mode": "simulator_http", "device_host": "127.0.0.1", "device_port": 8090,
            "config_label": "LAB-CONFIG-001", "max_runs": 500, "max_events": 20000,
        },
        "gateway.wifi.example.json": {
            "mode": "wifi", "device_host": "REPLACE_WITH_PRIVATE_ESP32_IPV4",
            "device_port": 80, "car_device_host": "REPLACE_WITH_PRIVATE_CAR_IPV4",
            "car_device_port": 80, "wifi_interface": "wlan0", "config_label": "LAB-CONFIG-002",
            "max_runs": 500, "max_events": 20000, "timeout": 2,
        },
    }
    for name, expected in expected_configs.items():
        if json.loads((root / "config" / name).read_text()) != expected:
            raise ValueError("Configuration template must retain public defaults")
