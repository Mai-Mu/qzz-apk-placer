"""Package an existing Windows build and matching source without rebuilding it."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil
import zipfile

try:
    from .bundle_adb import verify_bundle
except ImportError:
    from bundle_adb import verify_bundle

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ITEMS = (
    "apk_placer", "tests", "assets", "docs", "scripts", "main.py",
    "requirements.txt", "README.md", "TESTING.md", "THIRD_PARTY.md",
    "CHANGELOG.md", "VERSION", "build.ps1", "启动程序.bat", ".gitignore", ".gitattributes",
)


def package():
    version = (ROOT / "VERSION").read_text("utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?", version):
        raise ValueError("VERSION must contain a semantic version")
    binary = ROOT / "dist" / "QzzApkPlacer"
    if not (binary / "QzzApkPlacer.exe").is_file() or not (binary / "_internal").is_dir():
        raise FileNotFoundError("Build first: powershell -ExecutionPolicy Bypass -File .\\build.ps1")
    verify_bundle(binary / "platform-tools")
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    for name in ("README.md", "TESTING.md", "THIRD_PARTY.md", "CHANGELOG.md", "VERSION"):
        shutil.copyfile(ROOT / name, binary / name)
    for directory in ("docs", "licenses", "assets"):
        if (ROOT / directory).is_dir():
            shutil.copytree(ROOT / directory, binary / directory, dirs_exist_ok=True)
    shutil.copyfile(ROOT / "docs" / "USER_GUIDE.md", binary / "使用说明.md")
    shutil.copyfile(ROOT / "TESTING.md", binary / "验证记录.md")

    windows_zip = release / f"QzzApkPlacer-v{version}-windows-x64.zip"
    source_zip = release / f"QzzApkPlacer-v{version}-source.zip"
    with zipfile.ZipFile(windows_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(binary.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(binary.parent))
    items = SOURCE_ITEMS + (("licenses",) if (ROOT / "licenses").is_dir() else ())
    with zipfile.ZipFile(source_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in items:
            item = ROOT / name
            for path in sorted(item.rglob("*")) if item.is_dir() else [item]:
                if path.is_file() and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".apk", ".log"):
                    archive.write(path, path.relative_to(ROOT))
    checksums = []
    for path in (windows_zip, source_zip):
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise ValueError(f"Corrupt archive: {path.name}")
        with path.open("rb") as stream:
            checksum = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(chunk)
            digest = checksum.hexdigest()
        checksums.append(f"{digest}  {path.name}\n")
        print(f"{path.name}: {path.stat().st_size / 1024 / 1024:.1f} MiB")
    (release / "SHA256SUMS.txt").write_text("".join(checksums), "utf-8")


if __name__ == "__main__":
    package()
