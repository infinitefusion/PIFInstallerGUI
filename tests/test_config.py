import os
import unittest
from pathlib import Path
from unittest import mock

import config


class ConfigTests(unittest.TestCase):
    def test_macos_data_directory(self):
        with (
            mock.patch.object(config.sys, "platform", "darwin"),
            mock.patch.object(Path, "home", return_value=Path("/Users/tester")),
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            self.assertEqual(
                config.app_data_dir(),
                Path("/Users/tester/Library/Application Support/infinitefusion_common"),
            )

    def test_data_directory_override(self):
        with mock.patch.dict(
            os.environ, {"PIF_LAUNCHER_DATA_DIR": "~/custom-pif"}, clear=True
        ):
            self.assertEqual(config.app_data_dir(), Path("~/custom-pif").expanduser())


if __name__ == "__main__":
    unittest.main()
