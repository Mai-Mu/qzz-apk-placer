"""Prepare Google's pinned Windows ADB binaries and unmodified notices."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads(Path(__file__).with_name("adb-bundle.json").read_text("utf-8"))


def verify_bundle(directory: Path):
    for name, expected in MANIFEST["files"].items():
        path = directory / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Bundled ADB file missing or changed: {path}. Run scripts/bundle_adb.py.")


def extract_bundle(archive: Path, destination: Path):
    if hashlib.sha256(archive.read_bytes()).hexdigest() != MANIFEST["sha256"]:
        raise ValueError("ADB download SHA-256 mismatch; refusing to bundle it")
    with zipfile.ZipFile(archive) as package:
        files = {name: package.read(f"platform-tools/{name}") for name in MANIFEST["files"]}
    for name, data in files.items():
        if hashlib.sha256(data).hexdigest() != MANIFEST["files"][name]:
            raise ValueError(f"ADB archive member SHA-256 mismatch: {name}")
    destination.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (destination / name).write_bytes(data)
    verify_bundle(destination)


def prepare_bundle(destination: Path, archive: Path | None = None):
    try:
        verify_bundle(destination)
        return
    except ValueError:
        pass
    local = ROOT / "platform-tools"
    if destination.resolve() != local.resolve():
        try:
            verify_bundle(local)
        except ValueError:
            pass
        else:
            destination.mkdir(parents=True, exist_ok=True)
            for name in MANIFEST["files"]:
                shutil.copyfile(local / name, destination / name)
            verify_bundle(destination)
            return
    if archive is not None:
        extract_bundle(archive, destination)
        return
    with tempfile.TemporaryDirectory(prefix="qzz-adb-download-") as directory:
        download = Path(directory) / "platform-tools.zip"
        with urllib.request.urlopen(MANIFEST["url"], timeout=60) as response, download.open("wb") as output:
            shutil.copyfileobj(response, output)
        extract_bundle(download, destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=ROOT / "platform-tools")
    parser.add_argument("--archive", type=Path, help="Use a previously downloaded official ZIP (hash verified)")
    arguments = parser.parse_args()
    prepare_bundle(arguments.destination, arguments.archive)
    print(f"Verified bundled ADB {MANIFEST['version']}: {arguments.destination}")
