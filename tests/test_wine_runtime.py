import hashlib
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
