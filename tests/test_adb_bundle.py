import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import bundle_adb, package_release


class BundleTests(unittest.TestCase):
    def fixture(self, root):
        archive = root / "official.zip"
        files = {"adb.exe": b"adb fixture", "AdbWinApi.dll": b"dll fixture", "NOTICE.txt": b"license fixture"}
        with zipfile.ZipFile(archive, "w") as package:
            for name, data in files.items():
                package.writestr("platform-tools/" + name, data)
            package.writestr("platform-tools/fastboot.exe", b"not needed")
            package.writestr("../outside.txt", b"must not extract")
        manifest = {"sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
        return archive, manifest

    def test_extracts_only_verified_adb_files_and_notices(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, manifest = self.fixture(root)
            with patch.object(bundle_adb, "MANIFEST", manifest):
                bundle_adb.extract_bundle(archive, root / "output")
                bundle_adb.verify_bundle(root / "output")
            self.assertEqual({p.name for p in (root / "output").iterdir()}, set(manifest["files"]))
            self.assertFalse((root / "outside.txt").exists())

    def test_tampered_archive_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, manifest = self.fixture(root)
            archive.write_bytes(archive.read_bytes() + b"changed")
            with patch.object(bundle_adb, "MANIFEST", manifest), self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                bundle_adb.extract_bundle(archive, root / "output")
            self.assertFalse((root / "output").exists())

    def test_changed_binary_or_missing_notice_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, manifest = self.fixture(root)
            with patch.object(bundle_adb, "MANIFEST", manifest):
                for name in ("adb.exe", "NOTICE.txt"):
                    bundle_adb.extract_bundle(archive, root / "output")
                    (root / "output" / name).write_bytes(b"changed")
                    with self.assertRaisesRegex(ValueError, "missing or changed"):
                        bundle_adb.verify_bundle(root / "output")
                (root / "output/NOTICE.txt").unlink()
                with self.assertRaises(ValueError):
                    bundle_adb.verify_bundle(root / "output")

    def test_release_refuses_build_without_bundled_adb(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "VERSION").write_text("1.2.1", encoding="utf-8")
            binary = root / "dist/QzzApkPlacer"
            (binary / "_internal").mkdir(parents=True)
            (binary / "QzzApkPlacer.exe").write_bytes(b"fixture")
            with patch.object(package_release, "ROOT", root), self.assertRaisesRegex(ValueError, "Bundled ADB"):
                package_release.package()
            self.assertFalse((root / "release").exists())
