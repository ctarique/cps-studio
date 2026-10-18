"""Read-only fresh-install checks. Never modifies accounts, files or services."""
from pathlib import Path
import grp
import pwd
import re

TARGETS = (
    "opt/sentinel-cps-final", "etc/sentinel-cps-final",
    "var/lib/sentinel-cps-final", "etc/systemd/system/sentinel-cps-final.service",
)


def validate_version(value):
    if not re.fullmatch(r"(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})", value):
        raise ValueError("Invalid release version")
    return value


def check_fresh_install(root=Path("/"), user_lookup=pwd.getpwnam, group_lookup=grp.getgrnam):
    for name in TARGETS:
        path = root / name
        if path.exists() or path.is_symlink():
            raise ValueError("Existing final installation path")
        for parent in path.parents:
            if parent == root:
                break
            if parent.is_symlink():
                raise ValueError("Symlink installation path")
    for lookup in (user_lookup, group_lookup):
        try:
            lookup("sentinel-final")
        except KeyError:
            continue
        raise ValueError("Existing service identity")


if __name__ == "__main__":
    try:
        version = validate_version((Path(__file__).resolve().parent.parent / "VERSION").read_text().strip())
        check_fresh_install()
    except (OSError, ValueError):
        raise SystemExit("Fresh installation refused: existing configuration, evidence, service identity or unsafe path. Preserve it and review the deployment runbook.") from None
    print(version)
