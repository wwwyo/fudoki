"""ダウンロード失敗が次のロゴ生成を妨げないことを確認する。"""

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fonts


class FontCacheTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.data = b"verified font fixture"
        (self.root / "type-fonts.json").write_text(json.dumps([{
            "id": "fixture",
            "url": "https://example.invalid/font.ttf",
            "sha256": hashlib.sha256(self.data).hexdigest(),
        }]))
        for name in ("ROOT", "HERE"):
            self.enterContext(patch.object(fonts, name, self.root))
        self.path = self.root / ".cache/logo-fonts/fixture.ttf"

    def test_invalid_download_is_not_cached_and_retry_succeeds(self):
        with patch.object(fonts.urllib.request, "urlopen", return_value=io.BytesIO(b"truncated")):
            with self.assertRaisesRegex(ValueError, "ハッシュが一致しません"):
                fonts.font_paths("fixture")
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.path.parent.iterdir()), [])
        with patch.object(fonts.urllib.request, "urlopen", return_value=io.BytesIO(self.data)):
            self.assertEqual(fonts.font_paths("fixture"), [self.path])
        self.assertEqual(self.path.read_bytes(), self.data)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_publish_failure_cleans_temporary_file(self):
        with patch.object(fonts.urllib.request, "urlopen", return_value=io.BytesIO(self.data)):
            with patch.object(Path, "replace", side_effect=OSError("publish failed")):
                with self.assertRaisesRegex(OSError, "publish failed"):
                    fonts.font_paths("fixture")
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.path.parent.iterdir()), [])

    def test_valid_cache_is_reused_without_network(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(self.data)
        with patch.object(fonts.urllib.request, "urlopen") as download:
            self.assertEqual(fonts.font_paths("fixture"), [self.path])
            download.assert_not_called()

    def test_existing_invalid_cache_still_fails_validation(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"corrupt existing cache")
        with patch.object(fonts.urllib.request, "urlopen") as download:
            with self.assertRaisesRegex(ValueError, "ハッシュが一致しません"):
                fonts.font_paths("fixture")
            download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
