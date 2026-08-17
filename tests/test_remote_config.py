import io
import json
import unittest
import urllib.error
from unittest import mock

import remote_config


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class RemoteConfigTests(unittest.TestCase):
    def setUp(self):
        remote_config._cache = None

    def tearDown(self):
        remote_config._cache = None

    def test_fetch_uses_default_verified_tls_context(self):
        context = object()
        response = Response(json.dumps({"games": {}}).encode("utf-8"))
        with (
            mock.patch.object(
                remote_config.ssl, "create_default_context", return_value=context
            ) as create_context,
            mock.patch.object(
                remote_config.urllib.request, "urlopen", return_value=response
            ) as urlopen,
        ):
            result = remote_config.fetch_remote_config()

        self.assertEqual(result, {"games": {}})
        create_context.assert_called_once_with()
        self.assertIs(urlopen.call_args.kwargs["context"], context)

    def test_fetch_retries_transient_network_failure(self):
        response = Response(b'{"social_links": []}')
        with (
            mock.patch.object(
                remote_config.urllib.request,
                "urlopen",
                side_effect=[urllib.error.URLError("temporary"), response],
            ) as urlopen,
            mock.patch.object(remote_config.time, "sleep") as sleep,
        ):
            result = remote_config.fetch_remote_config()

        self.assertEqual(result, {"social_links": []})
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(0.5)


if __name__ == "__main__":
    unittest.main()
