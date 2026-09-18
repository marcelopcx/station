import os
import unittest
from unittest.mock import patch

from controller.webrtc.ice import _is_globally_routable, _select_host_addresses


class IceHostFilterTests(unittest.TestCase):
    def test_routable(self) -> None:
        self.assertTrue(_is_globally_routable("156.255.130.66"))
        self.assertFalse(_is_globally_routable("10.212.134.32"))
        self.assertFalse(_is_globally_routable("172.17.0.2"))
        self.assertFalse(_is_globally_routable("192.168.1.10"))
        self.assertFalse(_is_globally_routable("127.0.0.1"))

    def test_explicit_ips(self) -> None:
        env = {"ICE_HOST_IPS": "156.255.130.66", "ICE_INCLUDE_LOOPBACK": "0"}
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(
                _select_host_addresses(True, False),
                ["156.255.130.66"],
            )

    def test_public_policy_drops_rfc1918(self) -> None:
        env = {
            "ICE_HOST_IPS": "",
            "ICE_HOST_POLICY": "public",
            "ICE_INCLUDE_LOOPBACK": "0",
        }
        fake = ["10.212.134.32", "172.17.0.2", "156.255.130.66"]
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "controller.webrtc.ice._original_host_addresses",
                return_value=list(fake),
            ):
                self.assertEqual(
                    _select_host_addresses(True, False),
                    ["156.255.130.66"],
                )


if __name__ == "__main__":
    unittest.main()
