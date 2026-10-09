"""Public input boundaries; real PDF/geometry checks belong to integration."""
import tempfile
import unittest
from pathlib import Path

from ingestion.lib.paddle_ocr import OcrRegion, PaddleConfig, PaddleOcr, PaddleOcrError


class PublicBoundaries(unittest.TestCase):
    def test_invalid_configuration(self):
        for config in ({"dpi": True}, {"dpi": 601}, {"max_pixels": 0},
                       {"cpu_threads": 0}, {"recognition_batch_size": True},
                       {"detection_limit_side_len": 0}, {"pdf_renderer": "auto"},
                       {"render_timeout_seconds": float("nan")}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                PaddleConfig(**config)

    def test_invalid_physical_pages_before_input_is_read(self):
        with PaddleOcr() as ocr:
            for pages in ([], [0], [True], [1, 1]):
                with self.subTest(pages=pages), self.assertRaisesRegex(ValueError, "distinct positive physical"):
                    ocr.recognize_pdf(Path("does-not-exist.pdf"), pages=pages)

    def test_invalid_retry_page_or_owner_before_pdf_render(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unreadable.pdf"
            path.write_bytes(b"No valid PDF is needed to reject invalid declarations")
            with PaddleOcr() as ocr:
                with self.assertRaisesRegex(ValueError, "retry_regions must be keyed"):
                    ocr.recognize_pdf(path, pages=[1], retry_regions=[])
                with self.assertRaisesRegex(ValueError, "Retry pages must be requested"):
                    ocr.recognize_pdf(path, pages=[1], retry_regions={2: [OcrRegion("cell", (0, 0, 1, 1))]})
                with self.assertRaisesRegex(ValueError, "exactly one declared normal region"):
                    ocr.recognize_pdf(path, pages=[1], regions=[OcrRegion("left", (0, 0, 0.5, 1))],
                                      retry_regions={1: [OcrRegion("right-cell", (0.6, 0.1, 0.8, 0.2))]})

    def test_image_missing_models_fails_without_download(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Optional Pillow is not installed")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "one-pixel.png"
            Image.new("RGB", (1, 1), "white").save(path)
            config = PaddleConfig(detection_model_dir=directory, recognition_model_dir=directory)
            with PaddleOcr(config) as ocr:
                with self.assertRaisesRegex(PaddleOcrError, "no models are downloaded"):
                    ocr.recognize_image(path)
            self.assertEqual([p.name for p in Path(directory).iterdir()], ["one-pixel.png"])


if __name__ == "__main__":
    unittest.main()
