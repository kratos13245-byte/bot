import unittest
from unittest.mock import patch

from youtube_bot import YouTubeChatBridge


class YouTubeConfigTests(unittest.TestCase):
    def test_video_id_can_be_used_without_chat_id(self):
        with patch.dict("os.environ", {"YOUTUBE_VIDEO_ID": "abc", "YOUTUBE_ACCESS_TOKEN": "token"}, clear=False):
            bridge = YouTubeChatBridge(None, None)
            self.assertEqual(bridge.video_id, "abc")
            self.assertEqual(bridge.chat_id, "")


if __name__ == "__main__":
    unittest.main()
