import unittest

from controller.webrtc.ice import candidate_from_message
from controller.webrtc.signaling import Ice, Offer, parse_client_message


class SignalingTests(unittest.TestCase):
    def test_parse_offer(self) -> None:
        msg = parse_client_message({"type": "OFFER", "sdp": "v=0..."})
        self.assertIsInstance(msg, Offer)
        assert isinstance(msg, Offer)
        self.assertEqual(msg.sdp, "v=0...")

    def test_ignore_empty_offer(self) -> None:
        self.assertIsNone(parse_client_message({"type": "OFFER", "sdp": ""}))

    def test_parse_ice(self) -> None:
        raw = {"type": "ICE", "candidate": "candidate:0 1 UDP 1 127.0.0.1 9 typ host"}
        msg = parse_client_message(raw)
        self.assertIsInstance(msg, Ice)

    def test_ignore_unknown_type(self) -> None:
        self.assertIsNone(parse_client_message({"type": "PING"}))


class IceCandidateTests(unittest.TestCase):
    def test_skip_empty(self) -> None:
        self.assertIsNone(candidate_from_message({"type": "ICE", "candidate": ""}))

    def test_skip_mdns(self) -> None:
        line = "candidate:0 1 UDP 1 abc.local 9 typ host"
        self.assertIsNone(candidate_from_message({"candidate": line}))

    def test_host_candidate(self) -> None:
        line = "candidate:0 1 UDP 2122252543 127.0.0.1 54321 typ host"
        cand = candidate_from_message(
            {"candidate": line, "sdpMid": "0", "sdpMLineIndex": 0}
        )
        self.assertIsNotNone(cand)
        assert cand is not None
        self.assertEqual(cand.sdpMid, "0")
        self.assertEqual(cand.sdpMLineIndex, 0)


if __name__ == "__main__":
    unittest.main()
