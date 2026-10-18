"""Release/privacy regressions; no real compiler, installation or service changes."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "release"
        self.root.mkdir()
        for dirname in ("tools", "config", "esp32"):
            shutil.copytree(ROOT / dirname, self.root / dirname,
                            ignore=shutil.ignore_patterns("__pycache__", "*.local.h"))
        (self.root / "VERSION").write_text("1.0.1\n")
        (self.root / "README.md").write_text("Fixture release.\n")
        self.output = self.base / "release.zip"

    def command(self, script, *args, env=None):
        return subprocess.run([sys.executable, "-B", str(self.root / "tools" / script), *map(str, args)],
                              cwd=self.root, text=True, capture_output=True, env=env)

    def package(self):
        return self.command("package.py", "--output", self.output)

    def assert_private_refused(self, marker):
        result = self.package()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())
        self.assertNotIn(marker, result.stdout + result.stderr)

    def test_unknown_private_config_refused(self):
        (self.root / "config" / "gateway.env").write_text("PRIVATE_RELEASE_SENTINEL")
        self.assert_private_refused("PRIVATE_RELEASE_SENTINEL")

    def test_private_file_in_document_directory_refused(self):
        (self.root / "docs").mkdir()
        (self.root / "docs" / "private.env").write_text("PRIVATE_RELEASE_SENTINEL")
        self.assert_private_refused("PRIVATE_RELEASE_SENTINEL")

    def test_provisioned_firmware_template_refused(self):
        p = self.root / "config" / "ai-thinker-esp32cam-led.example.h"
        p.write_text(p.read_text().replace('SENTINEL_WIFI_SSID = ""', 'SENTINEL_WIFI_SSID = "PRIVATE_RELEASE_SENTINEL"'))
        self.assert_private_refused("PRIVATE_RELEASE_SENTINEL")

    def test_provisioned_car_firmware_template_refused(self):
        p = self.root / "esp32" / "sentinel_car" / "sentinel_car_config.example.h"
        p.write_text(
            p.read_text().replace(
                'SENTINEL_CAR_DEVICE_KEY = ""',
                'SENTINEL_CAR_DEVICE_KEY = "PRIVATE_RELEASE_SENTINEL"',
            )
        )
        self.assert_private_refused("PRIVATE_RELEASE_SENTINEL")

    def test_unknown_car_firmware_file_refused(self):
        p = self.root / "esp32" / "sentinel_car" / "unexpected.h"
        p.write_text("#pragma once\n")
        result = self.package()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_car_firmware_source_is_packaged(self):
        result = self.package()
        self.assertEqual(result.returncode, 0, result.stderr)

        expected = {
            "sentinel_car.ino",
            "car_engine.h",
            "response.h",
            "sentinel_car_config.example.h",
        }

        with zipfile.ZipFile(self.output) as archive:
            names = {
                Path(name).name
                for name in archive.namelist()
                if "/esp32/sentinel_car/" in name
            }

        self.assertEqual(names, expected)

    def test_provisioned_environment_template_refused(self):
        p = self.root / "config" / "gateway.env.example"
        p.write_text(
            p.read_text().replace(
                "REPLACE_WITH_DIFFERENT_64_LOWERCASE_HEX",
                "a" * 64,
                1,
            )
        )
        self.assert_private_refused("a" * 64)

    def test_provisioned_network_template_refused(self):
        p = self.root / "config" / "gateway.wifi.example.json"
        p.write_text(p.read_text().replace("REPLACE_WITH_PRIVATE_ESP32_IPV4", "192.168.44.3"))
        self.assert_private_refused("192.168.44.3")

    def test_local_state_and_venv_symlinks_excluded_and_zip_reproducible(self):
        (self.root / ".local").mkdir()
        (self.root / ".local" / "home.env").write_text("PRIVATE_RELEASE_SENTINEL")
        (self.root / ".venv").mkdir()
        (self.root / ".venv" / "python").symlink_to(sys.executable)
        first = self.package()
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.command("package.py", "--output", self.base / "repeat.zip")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.output.read_bytes(), (self.base / "repeat.zip").read_bytes())
        with zipfile.ZipFile(self.output) as z:
            self.assertFalse(any(".venv/" in n or ".local/" in n for n in z.namelist()))
            self.assertFalse(any(b"PRIVATE_RELEASE_SENTINEL" in z.read(n) for n in z.namelist()))

    def test_verifier_rejects_symlink_parent(self):
        outside = self.base / "outside"
        outside.mkdir()
        content = b"fixture"
        (outside / "note.md").write_bytes(content)
        (self.root / "docs").symlink_to(outside, target_is_directory=True)
        (self.root / "MANIFEST.json").write_text(json.dumps({
            "version": "1.0.1", "files": {"docs/note.md": hashlib.sha256(content).hexdigest()}}))
        result = self.command("verify_bundle.py")
        self.assertNotEqual(result.returncode, 0)

    def test_complete_gateway_asset_tree_is_packaged_and_verified(self):
        shutil.copytree(ROOT / "gateway", self.root / "gateway",
                        ignore=shutil.ignore_patterns("__pycache__"))
        first = self.package()
        self.assertEqual(first.returncode, 0, first.stderr)
        result = self.command("verify_bundle.py")
        self.assertEqual(result.returncode, 0, result.stderr)
        assets = [p for p in (self.root / "gateway" / "static").rglob("*")
                  if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".svg"}]
        self.assertGreater(len(assets), 0)
        with zipfile.ZipFile(self.output) as archive:
            for path in assets:
                self.assertEqual(archive.read("sentinel-cps-final/" + str(path.relative_to(self.root))),
                                 path.read_bytes())
        second = self.command("package.py", "--output", self.base / "full-repeat.zip")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.output.read_bytes(), (self.base / "full-repeat.zip").read_bytes())

    def test_verifier_rejects_unlisted_executable_file(self):
        self.assertEqual(self.package().returncode, 0)
        (self.root / "gateway").mkdir()
        (self.root / "gateway" / "extra.py").write_text("unlisted = True\n")
        self.assertNotEqual(self.command("verify_bundle.py").returncode, 0)

    def test_raster_outside_reviewed_asset_directory_refused(self):
        (self.root / "gateway").mkdir()
        (self.root / "gateway" / "private.png").write_bytes(b"PRIVATE_RELEASE_SENTINEL")
        self.assert_private_refused("PRIVATE_RELEASE_SENTINEL")

    def test_home_credentials_created_privately_without_starting_server(self):
        runner = """
import runpy, sys, types
gateway = types.ModuleType("gateway")
app = types.ModuleType("gateway.app")
app.create_app = lambda config: None
config = types.ModuleType("gateway.config")
config.Config = lambda *args, **kwargs: None
waitress = types.ModuleType("waitress")
waitress.serve = lambda *args, **kwargs: None
sys.modules.update({"gateway": gateway, "gateway.app": app,
                    "gateway.config": config, "waitress": waitress})
runpy.run_path(sys.argv[1])
"""
        result = subprocess.run([sys.executable, "-B", "-c", runner, str(self.root / "tools/home.py")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        local = self.root / ".local"
        private = local / "home.env"
        self.assertEqual(stat.S_IMODE(local.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o600)
        entries = dict(line.split("=", 1) for line in private.read_text().splitlines())
        self.assertEqual(
            set(entries),
            {
                "SENTINEL_ADMIN_TOKEN",
                "SENTINEL_DEVICE_KEY",
                "SENTINEL_CAR_DEVICE_KEY",
            },
        )
        self.assertEqual(len(entries), 3)
        self.assertEqual(len(set(entries.values())), 3)
        for value in entries.values():
            self.assertRegex(value, r"^[0-9a-f]{64}$")
            self.assertNotIn(value, result.stdout + result.stderr)

    def fake_compiler_env(self):
        executable = self.base / "arduino-cli"
        executable.write_text("#!" + sys.executable + "\n" + r"""import json, pathlib, sys
if sys.argv[1] == "version":
    print(json.dumps({"VersionString": "1.5.1"}))
elif sys.argv[1:3] == ["core", "list"]:
    print(json.dumps({"platforms": [{"id": "esp32:esp32", "installed_version": "3.3.7"}]}))
elif sys.argv[1] == "compile":
    p = pathlib.Path(sys.argv[sys.argv.index("--build-path") + 1])
    (p / "fake.bin").write_bytes(b"PRIVATE_BINARY_FIXTURE")
else:
    raise SystemExit(1)
""")
        executable.chmod(0o700)
        return {**os.environ, "PATH": str(self.base) + os.pathsep + os.environ["PATH"]}

    def test_firmware_build_refuses_existing_output(self):
        output = self.base / "build"
        output.mkdir()
        (output / "first-attempt.txt").write_text("preserve")
        result = self.command("build_firmware.py", "--output", output, env=self.fake_compiler_env())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sorted(p.name for p in output.iterdir()), ["first-attempt.txt"])

    def test_firmware_build_creates_private_output(self):
        output = self.base / "build"
        result = self.command("build_firmware.py", "--output", output, env=self.fake_compiler_env())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
        self.assertTrue((output / "fake.bin").is_file())


class InstallPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        spec = importlib.util.spec_from_file_location("install_preflight", ROOT / "tools/install_preflight.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    @staticmethod
    def absent(name):
        raise KeyError(name)

    def check(self, **kwargs):
        self.module.check_fresh_install(self.root, **{
            "user_lookup": self.absent, "group_lookup": self.absent, **kwargs})

    def test_clean_installation_passes_read_only(self):
        self.check()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_configuration_evidence_release_or_unit_refused(self):
        for name in self.module.TARGETS:
            with self.subTest(target=name):
                target = self.root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("preserve")
                with self.assertRaises(ValueError):
                    self.check()
                self.assertEqual(target.read_text(), "preserve")
                target.unlink()

    def test_existing_user_or_group_refused(self):
        for kind in ("user_lookup", "group_lookup"):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.check(**{kind: lambda name: object()})

    def test_symlink_installation_parent_refused(self):
        (self.root / "opt").symlink_to(self.root / "missing", target_is_directory=True)
        with self.assertRaises(ValueError):
            self.check()

    def test_version_rejects_paths_and_shell_characters(self):
        self.assertEqual(self.module.validate_version("1.0.1"), "1.0.1")
        for value in ("../1.0.1", "1.0.1;command", "1.0.1\\n", "v1.0.1", "01.0.1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.module.validate_version(value)


if __name__ == "__main__":
    unittest.main()
