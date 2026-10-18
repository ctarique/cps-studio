"""Create a deterministic source/deployment ZIP; exclude private state and builds."""
import argparse
import hashlib
import json
import pathlib
import zipfile
from release_policy import release_files

root = pathlib.Path(__file__).resolve().parent.parent
p = argparse.ArgumentParser()
p.add_argument("--output", type=pathlib.Path, required=True)
args = p.parse_args()
sidecar = args.output.with_suffix(args.output.suffix + ".sha256")
if args.output.exists() or args.output.is_symlink() or sidecar.exists() or sidecar.is_symlink():
    raise SystemExit("Output already exists; choose a new filename.")
if args.output.resolve().is_relative_to(root):
    raise SystemExit("Keep release ZIPs outside the source directory.")
if (root / "MANIFEST.json").is_symlink():
    raise SystemExit("Manifest cannot be a symlink.")
try:
    files = release_files(root)
except (ValueError, OSError, UnicodeError):
    raise SystemExit("Release inputs refused: unexpected/private file or provisioned template.") from None
manifest = {
    "version": (root / "VERSION").read_text().strip(),
    "files": {str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest() for f in files},
}
(root / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
files.append(root / "MANIFEST.json")
args.output.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(args.output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for f in sorted(files):
        info = zipfile.ZipInfo("sentinel-cps-final/" + str(f.relative_to(root)), (2026, 9, 7, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = ((0o100755 if f.suffix == ".sh" else 0o100644) << 16)
        z.writestr(info, f.read_bytes())
digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
with sidecar.open("x") as f:
    f.write(digest + "  " + args.output.name + "\n")
print("Packaged", len(files), "files; SHA-256", digest)
