import hashlib
import io
import os
import stat
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import wine_runtime


class WineRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.logs = []
        self.log_fn = lambda message, replace=False: self.logs.append(
            (message, replace)
        )

    def test_automatic_reuses_compatible_installed_wine(self):
        selection = wine_runtime.WineSelection(
            Path("/installed/wine"), "11.0", "installed Wine"
        )
        with (
            mock.patch.object(wine_runtime, "find_system_wine", return_value=selection),
            mock.patch.object(wine_runtime, "install_managed_wine") as install,
        ):
            result = wine_runtime.select_wine(self.log_fn)

        self.assertEqual(result, selection)
        install.assert_not_called()
        self.assertIn("no download needed", self.logs[-1][0])

    def test_automatic_downloads_only_after_all_reuse_options_fail(self):
        installed = wine_runtime.WineSelection(
            Path("/managed/wine"), "11.0", "managed Wine"
        )
        with (
            mock.patch.object(wine_runtime, "find_system_wine", return_value=None),
            mock.patch.object(wine_runtime, "_bundled_roots", return_value=[]),
            mock.patch.object(wine_runtime, "_selection_from_root", return_value=None),
            mock.patch.object(
                wine_runtime, "install_managed_wine", return_value=installed
            ) as install,
        ):
            result = wine_runtime.select_wine(self.log_fn)

        self.assertEqual(result, installed)
        install.assert_called_once_with(self.log_fn)

    def test_checksum_rejects_modified_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "wine.tar.xz"
            archive.write_bytes(b"not the pinned archive")
            with self.assertRaisesRegex(
                wine_runtime.WineRuntimeError, "checksum mismatch"
            ):
                wine_runtime._verify_archive(archive)

    def test_checksum_accepts_matching_digest(self):
        payload = b"test archive"
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch.object(
                wine_runtime, "WINE_SHA256", hashlib.sha256(payload).hexdigest()
            ),
        ):
            archive = Path(temp) / "wine.tar.xz"
            archive.write_bytes(payload)
            wine_runtime._verify_archive(archive)

    @unittest.skipIf(os.name == "nt", "managed Wine archives are macOS-only")
    def test_safe_extract_preserves_internal_app_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "wine.tar.xz"
            destination = root / "runtime"
            payload = b"runtime"

            with tarfile.open(archive, "w:xz") as bundle:
                regular = tarfile.TarInfo(
                    "Wine Stable.app/Contents/Versions/A/runtime.txt"
                )
                regular.size = len(payload)
                regular.mode = 0o755
                bundle.addfile(regular, io.BytesIO(payload))

                link = tarfile.TarInfo("Wine Stable.app/Contents/Versions/Current")
                link.type = tarfile.SYMTYPE
                link.linkname = "./A"
                bundle.addfile(link)

            wine_runtime._extract_archive(archive, destination)

            extracted = (
                destination
                / "Wine Stable.app"
                / "Contents"
                / "Versions"
                / "A"
                / "runtime.txt"
            )
            current = extracted.parent.parent / "Current"
            self.assertEqual(extracted.read_bytes(), payload)
            self.assertTrue(current.is_symlink())
            self.assertEqual(os.readlink(current), "A")

    def test_safe_extract_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "wine.tar.xz"
            destination = root / "runtime"
            escaped = root / "escaped.txt"

            with tarfile.open(archive, "w:xz") as bundle:
                member = tarfile.TarInfo("../escaped.txt")
                member.size = 4
                bundle.addfile(member, io.BytesIO(b"nope"))

            with self.assertRaisesRegex(wine_runtime.WineRuntimeError, "Unsafe path"):
                wine_runtime._extract_archive(archive, destination)
            self.assertFalse(escaped.exists())
            self.assertFalse(destination.exists())

    def test_safe_extract_rejects_escaping_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "wine.tar.xz"
            destination = root / "runtime"

            with tarfile.open(archive, "w:xz") as bundle:
                link = tarfile.TarInfo("Wine Stable.app/Contents/escape")
                link.type = tarfile.SYMTYPE
                link.linkname = "../../../outside"
                bundle.addfile(link)

            with self.assertRaisesRegex(wine_runtime.WineRuntimeError, "Unsafe link"):
                wine_runtime._extract_archive(archive, destination)
            self.assertFalse(destination.exists())

    def test_safe_extract_rejects_hard_links_explicitly(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "wine.tar.xz"
            destination = root / "runtime"

            with tarfile.open(archive, "w:xz") as bundle:
                regular = tarfile.TarInfo("Wine Stable.app/original")
                regular.size = 4
                bundle.addfile(regular, io.BytesIO(b"data"))

                link = tarfile.TarInfo("Wine Stable.app/hardlink")
                link.type = tarfile.LNKTYPE
                link.linkname = "Wine Stable.app/original"
                bundle.addfile(link)

            with self.assertRaisesRegex(
                wine_runtime.WineRuntimeError, "Hard links are not supported"
            ):
                wine_runtime._extract_archive(archive, destination)
            self.assertFalse(destination.exists())

    @unittest.skipIf(os.name == "nt", "managed Wine installs are macOS-only")
    def test_failed_install_removes_read_only_staging_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "runtimes" / "wine-11.0"
            staging = root.parent / ".wine-11.0.installing"
            archive = root.parent / wine_runtime.WINE_ARCHIVE

            def download(destination, _log_fn):
                destination.write_bytes(b"archive")

            def fail_extract(_archive, destination):
                directory = destination / "partial"
                directory.mkdir(parents=True)
                (directory / "file").write_text("partial", encoding="utf-8")
                directory.chmod(0o500)
                raise wine_runtime.WineRuntimeError("interrupted extraction")

            with (
                mock.patch.object(wine_runtime, "_managed_root", return_value=root),
                mock.patch.object(
                    wine_runtime, "_selection_from_root", return_value=None
                ),
                mock.patch.object(
                    wine_runtime, "_download_archive", side_effect=download
                ),
                mock.patch.object(wine_runtime, "_verify_archive"),
                mock.patch.object(
                    wine_runtime, "_extract_archive", side_effect=fail_extract
                ),
            ):
                with self.assertRaisesRegex(
                    wine_runtime.WineRuntimeError, "interrupted extraction"
                ):
                    wine_runtime.install_managed_wine(self.log_fn)

            self.assertFalse(staging.exists())
            self.assertFalse(archive.exists())
            self.assertFalse(root.exists())

    def test_partial_download_is_removed(self):
        class Response(io.BytesIO):
            headers = {"Content-Length": "12"}

        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "wine.tar.xz"
            with (
                mock.patch.object(
                    wine_runtime.urllib.request,
                    "urlopen",
                    return_value=Response(b"partial"),
                ),
                mock.patch.object(wine_runtime, "_require_free_space"),
            ):
                with self.assertRaisesRegex(
                    wine_runtime.WineRuntimeError, "incomplete"
                ):
                    wine_runtime._download_archive(destination, self.log_fn)

            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_name("wine.tar.xz.part").exists())

    def test_download_is_atomically_published_with_private_permissions(self):
        payload = b"complete"

        class Response(io.BytesIO):
            headers = {"Content-Length": str(len(payload))}

        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "wine.tar.xz"
            with (
                mock.patch.object(
                    wine_runtime.urllib.request,
                    "urlopen",
                    return_value=Response(payload),
                ),
                mock.patch.object(wine_runtime, "_require_free_space"),
            ):
                wine_runtime._download_archive(destination, self.log_fn)

            self.assertEqual(destination.read_bytes(), payload)
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)

    def test_free_space_check_fails_before_large_operation(self):
        usage = mock.Mock(free=100)
        with mock.patch.object(wine_runtime.shutil, "disk_usage", return_value=usage):
            with self.assertRaisesRegex(
                wine_runtime.WineRuntimeError, "Not enough free disk space"
            ):
                wine_runtime._require_free_space(Path("."), 101, "download")
        self.assertEqual(usage.free, 100)

    def test_launch_initializes_prefix_and_uses_game_directory(self):
        selection = wine_runtime.WineSelection(
            Path("/wine/bin/wine"), "11.0", "installed Wine"
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game_dir = root / "game"
            game_dir.mkdir()
            exe = game_dir / "Game.exe"
            exe.touch()

            completed = mock.Mock(returncode=0, stdout="")
            with (
                mock.patch.object(wine_runtime, "_check_macos_host"),
                mock.patch.object(wine_runtime, "select_wine", return_value=selection),
                mock.patch.object(
                    wine_runtime, "app_data_dir", return_value=root / "data"
                ),
                mock.patch.object(
                    wine_runtime.subprocess, "run", return_value=completed
                ) as run,
                mock.patch.object(wine_runtime.subprocess, "Popen") as popen,
            ):
                result = wine_runtime.launch_game(exe, "kanto", self.log_fn)

            self.assertEqual(result, selection)
            run.assert_called_once()
            self.assertEqual(
                run.call_args.args[0], ["/wine/bin/wine", "wineboot", "--init"]
            )
            self.assertEqual(run.call_args.kwargs["cwd"], str(game_dir))
            prefix = root / "data" / "wineprefixes" / "kanto"
            self.assertEqual(run.call_args.kwargs["env"]["WINEPREFIX"], str(prefix))
            self.assertEqual(popen.call_args.args[0], ["/wine/bin/wine", str(exe)])
            self.assertEqual(popen.call_args.kwargs["cwd"], str(game_dir))
            self.assertTrue(popen.call_args.kwargs["start_new_session"])


if __name__ == "__main__":
    unittest.main()
