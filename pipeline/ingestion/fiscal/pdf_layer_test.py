"""回転PDFの文字層を、描画ページと同じ寸法へ対応付ける。"""
import struct
import tempfile
import unittest
from pathlib import Path
from ingestion.fiscal.pdf_layer import page_dimensions

class PageDimensions(unittest.TestCase):
    def check(self, width, height, pixels_w, pixels_h):
        with tempfile.TemporaryDirectory() as directory:
            png=Path(directory)/'page.png'
            png.write_bytes(b'\x89PNG\r\n\x1a\n'+b'\0'*8+struct.pack('>II',pixels_w,pixels_h))
            return page_dimensions(width,height,png)

    def test_rotated_a4_uses_display_dimensions(self):
        self.assertEqual(self.check(595,842,1287,910),(842,595))

    def test_unrotated_page_keeps_dimensions(self):
        self.assertEqual(self.check(595,842,910,1287),(595,842))

    def test_incompatible_crop_is_not_silently_overlaid(self):
        with self.assertRaises(ValueError):
            self.check(595,842,1000,1000)
