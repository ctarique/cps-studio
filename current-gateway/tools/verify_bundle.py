"""Read-only SHA-256 verification before deployment."""
import hashlib
import json
from pathlib import Path
import re
from release_policy import release_files

root = Path(__file__).resolve().parent.parent


def verified_files(root):
    if (root / "MANIFEST.json").is_symlink():
        raise ValueError("Symlink manifest")
    manifest = json.loads((root / "MANIFEST.json").read_text())
    if manifest["version"] != (root / "VERSION").read_text().strip():
        raise ValueError("Version mismatch")
    if not isinstance(manifest["files"], dict) or not manifest["files"]:
        raise ValueError("Empty manifest")
    for name, expected in manifest["files"].items():
        relative = Path(name)
        if (not isinstance(name, str) or not name or relative.is_absolute() or
                ".." in relative.parts or str(relative) != name or
                not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)):
            raise ValueError("Unsafe manifest entry")
        path = root
        for part in relative.parts:
            path = path / part
            if path.is_symlink():
                raise ValueError("Symlink manifest path")
        if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Unsafe manifest file")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Bundle hash mismatch")
    selected = {str(path.relative_to(root)) for path in release_files(root)}
    if set(manifest["files"]) != selected:
        raise ValueError("Manifest does not cover exact release inputs")
    return manifest["files"]


if __name__ == "__main__":
    try:
        verified_files(root)
    except (KeyError, TypeError, ValueError, OSError):
        raise SystemExit("Bundle verification failed; missing, changed or unsafe release file.") from None
    print("Bundle SHA-256 verification passed.")
