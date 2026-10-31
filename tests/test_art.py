import json
import os
import shutil
import tempfile
import unittest

from mcd_loader import art

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100


class ArtTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_uses_appdetails_urls_and_caches(self):
        calls = []
        details = {"1672970": {"success": True, "data": {
            "header_image": "https://cdn.example/apps/1672970/abc/header.jpg?t=1",
            "screenshots": [{"path_full": "https://cdn.example/shot1.jpg"}],
        }}}

        def fetch(url):
            calls.append(url)
            if "appdetails" in url:
                return json.dumps(details).encode()
            if url in ("https://cdn.example/shot1.jpg", "https://cdn.example/apps/1672970/abc/capsule_616x353.jpg"):
                return JPEG
            raise OSError("404")

        got = art.fetch_game_art("mcd", self.dir, fetch=fetch)
        self.assertEqual(set(got), {"hero", "card"})
        self.assertIn("https://cdn.example/shot1.jpg", calls)
        with open(got["card"], "rb") as f:
            self.assertEqual(f.read(), JPEG)
        calls.clear()
        self.assertEqual(art.fetch_game_art("mcd", self.dir, fetch=fetch), got)
        self.assertEqual(calls, [])  # fresh cache: no network
        self.assertEqual(art.cached_game_art("mcd", self.dir), got)

    def test_offline_falls_back_to_cdn_and_ignores_non_images(self):
        def fetch(url):
            if "appdetails" in url:
                raise OSError("offline")
            if url.endswith("/3949040/header.jpg"):
                return JPEG
            return b"<html>not found</html>"

        got = art.fetch_game_art("rv", self.dir, fetch=fetch)
        self.assertEqual(set(got), {"card"})

    def test_unknown_game(self):
        self.assertEqual(art.fetch_game_art("nope", self.dir, fetch=lambda u: JPEG), {})
        self.assertFalse(os.listdir(self.dir))


if __name__ == "__main__":
    unittest.main()
