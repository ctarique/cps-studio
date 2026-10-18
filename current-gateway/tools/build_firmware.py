"""Compile only; never opens an upload/flash operation."""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import tempfile

p = argparse.ArgumentParser()
p.add_argument("--board", choices=("esp32cam", "esp32"), default="esp32cam")
p.add_argument("--private-config", type=pathlib.Path)
p.add_argument("--output", type=pathlib.Path, required=True)
a = p.parse_args()
root = pathlib.Path(__file__).resolve().parent.parent
if a.output.resolve().is_relative_to(root):
    raise SystemExit("Keep build output outside the public release; provisioned binaries contain secrets.")
if a.output.exists() or a.output.is_symlink():
    raise SystemExit("Build output already exists; preserve it and choose a new attempt directory.")
if a.private_config:
    if a.private_config.resolve().is_relative_to(root):
        raise SystemExit("Keep private firmware configuration outside the public release.")
    if not a.private_config.is_file() or a.private_config.is_symlink():
        raise SystemExit("Private configuration must be a regular external file.")
cli = shutil.which("arduino-cli")
if not cli:
    raise SystemExit("Arduino CLI required; see DEPLOYMENT.md")
version = json.loads(subprocess.check_output([cli, "version", "--format", "json"]))
cores = json.loads(subprocess.check_output([cli, "core", "list", "--format", "json"]))
installed = {p["id"]: p.get("installed_version") for p in cores.get("platforms", [])}
if version.get("VersionString") != "1.5.1" or installed.get("esp32:esp32") != "3.3.7":
    raise SystemExit("Use the recorded Arduino CLI 1.5.1 and ESP32 core 3.3.7 toolchain.")
# Build products embed the private configuration. Preserve failures under a new private directory.
os.umask(0o077)
a.output.mkdir(mode=0o700, parents=True, exist_ok=False)
with tempfile.TemporaryDirectory(prefix="sentinel-firmware-") as tmp:
    sketch = pathlib.Path(tmp) / "sentinel_esp32"
    shutil.copytree(root / "esp32" / "sentinel_esp32", sketch)
    if (sketch / "sentinel_config.local.h").exists():
        raise SystemExit("Private header found in release; compilation refused.")
    if a.private_config:
        shutil.copyfile(a.private_config, sketch / "sentinel_config.local.h")
    result = subprocess.run([cli, "compile", "--fqbn", "esp32:esp32:" + a.board,
                             "--build-path", str(a.output.resolve()), str(sketch)])
    raise SystemExit(result.returncode)
