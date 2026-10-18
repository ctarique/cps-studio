"""Software-only verification. Execute from an unpacked release."""
import pathlib
import shutil
import subprocess
import sys
import tempfile
root=pathlib.Path(__file__).resolve().parent.parent
result=subprocess.run([sys.executable,"-B","-m","unittest","discover","-s","tests","-v"],cwd=root)
if result.returncode:raise SystemExit(result.returncode)
compiler=shutil.which("c++") or shutil.which("clang++")
if not compiler:raise SystemExit("Python tests passed; native firmware engine checks NOT RUN (C++ compiler unavailable).")
with tempfile.TemporaryDirectory() as tmp:
    tmp=pathlib.Path(tmp)
    checks=(
        ("firmware-core", "firmware_core.cpp"),
        ("car-firmware-core", "car_firmware_core.cpp"),
    )
    for target_name, source_name in checks:
        target=tmp/target_name
        subprocess.run([
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(root/"tests"/source_name),
            "-o",
            str(target),
        ],check=True)
        subprocess.run([str(target)],check=True)
print("Software-only checks passed. No hardware validation performed.")
