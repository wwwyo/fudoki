"""Public OCR boundaries and safe, whole-name dictionary corrections."""

import tempfile
import unittest
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ingestion.lib.ocr_names import NameDictionary, NameRule, correct_name, load_name_dictionary
from ingestion.lib.vision_ocr import OcrRegion, VisionConfig, recognize_pdf


class VocabularyLoading(unittest.TestCase):
    def recognize(self, config):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.pdf"
            path.write_bytes(b"native invocation is mocked")
            with patch("ingestion.lib.vision_ocr.platform.system", return_value="Darwin"), \
                    patch("ingestion.lib.vision_ocr.subprocess.run",
                          return_value=SimpleNamespace(returncode=0, stdout='{"engine":{}}')) as native:
                result = recognize_pdf(path, pages=[1], config=config)
                request = json.loads(native.call_args.kwargs["input"])
                return request, result

    def test_on_automatically_passes_separate_vocabulary(self):
        path = Path(__file__).with_name("ocr_vocabulary.json")
        expected = json.loads(path.read_text())["words"]
        request, result = self.recognize(VisionConfig(language_correction=True))
        self.assertEqual(request["config"]["custom_words"], expected)
        self.assertEqual(result["engine"]["vocabulary"]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertNotIn("vocabulary_path", request["config"])

    def test_off_does_not_read_dictionary(self):
        request, result = self.recognize(VisionConfig(vocabulary_path="/nonexistent/dictionary.json"))
        self.assertEqual(request["config"]["custom_words"], [])
        self.assertIsNone(result["engine"]["vocabulary"])

    def test_override_and_additional_words_are_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vocabulary.json"
            path.write_text(json.dumps({"schema_version": 1, "words": ["共済費", "共済費"]}))
            request, result = self.recognize(VisionConfig(language_correction=True,
                vocabulary_path=str(path), custom_words=("共済費", "備品購入費")))
            self.assertEqual(request["config"]["custom_words"], ["共済費", "備品購入費"])
            self.assertEqual(result["engine"]["vocabulary"]["path"], str(path.resolve()))

    def test_invalid_dictionary_does_not_start_ocr(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vocabulary.json"
            for payload in [{"schema_version": True, "words": []}, {"schema_version": 2, "words": []},
                            {"schema_version": 1, "words": "給料"}, {"schema_version": 1, "words": [""]},
                            {"schema_version": 1, "words": [12]}, {"schema_version": 1, "word": ["給料"]}]:
                path.write_text(json.dumps(payload))
                with self.assertRaises(ValueError):
                    self.recognize(VisionConfig(language_correction=True, vocabulary_path=str(path)))

    def test_empty_dictionary_disables_vocabulary_hints(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.json"
            path.write_text('{"schema_version":1,"words":[]}')
            request, _ = self.recognize(VisionConfig(language_correction=True, vocabulary_path=str(path)))
            self.assertEqual(request["config"]["custom_words"], [])


class NameCorrections(unittest.TestCase):
    def setUp(self):
        self.dictionary = load_name_dictionary(Path(__file__).with_name("fiscal_setsu_name_corrections.json"))

    def test_corrected_name_preserves_original_and_rule(self):
        result = correct_name(" 備品 入費 ", self.dictionary)
        self.assertEqual(result["raw_name"], " 備品 入費 ")
        self.assertEqual(result["corrected_name"], "備品購入費")
        self.assertEqual(result["rule_id"], "setsu-equipment-purchase-missing-character")
        self.assertEqual(result["dictionary_sha256"], self.dictionary.sha256)

    def test_partial_name_code_and_money_are_not_rewritten(self):
        for name in ["備品入費を含む事業", "18 備品入費", "10,409,000", "0", "既に正しい名称"]:
            result = correct_name(name, self.dictionary)
            self.assertEqual(result["corrected_name"], name)
            self.assertIsNone(result["rule_id"])

    def test_folded_name_requires_whole_label(self):
        self.assertIsNone(correct_name("價還金・利子", self.dictionary)["rule_id"])
        self.assertEqual(correct_name("價還金・利子\n及び割引料", self.dictionary)["corrected_name"], "償還金・利子及び割引料")

    def test_ambiguous_normalized_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            NameDictionary("test", (NameRule("a", "共济费", "共済費", "test"),
                                     NameRule("b", "共 济 费", "別の名称", "test")))

    def test_amount_only_dictionary_entry_is_rejected(self):
        with self.assertRaises(ValueError):
            NameDictionary("test", (NameRule("a", "１２４", "424", "test"),))


class InputBoundaries(unittest.TestCase):
    def test_regions_reject_outside_reversed_and_nan_coordinates(self):
        for box in [(-.1, 0, 1, 1), (0, 0, 1.1, 1), (1, 0, 0, 1), (0, 0, float('nan'), 1), (0, 0, 1)]:
            with self.assertRaises(ValueError):
                OcrRegion("column", box)

    def test_config_rejects_invalid_resource_limits_and_boolean_dpi(self):
        for config in [{"dpi": True}, {"dpi": 601}, {"max_pixels": 0}, {"revision": 0}, {"language_correction": "false"}, {"languages": "ja-JP"}]:
            with self.assertRaises(ValueError):
                VisionConfig(**config)

    def test_pages_must_be_explicit_positive_and_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"input.pdf"
            path.write_bytes(b"not a PDF")
            for pages in [[], [0], [True], [1, 1]]:
                with self.assertRaises(ValueError):
                    recognize_pdf(path, pages=pages)

    def test_vocabulary_requires_correction_and_valid_words(self):
        for words in ["備品購入費", [""], ["  "], [12], None]:
            with self.assertRaises(ValueError):
                VisionConfig(language_correction=True, custom_words=words)
        with self.assertRaises(ValueError):
            VisionConfig(custom_words=("備品購入費",))
        config = VisionConfig(language_correction=True, custom_words=["備品購入費", "償還金"])
        self.assertEqual(config.custom_words, ["備品購入費", "償還金"])

    def test_minimum_text_height_rejects_invalid_fractions(self):
        for height in [True, -0.01, 1.01, float("nan"), float("inf"), "0.001"]:
            with self.assertRaises(ValueError):
                VisionConfig(minimum_text_height=height)
        for height in [None, 0, 0.001, 1]:
            self.assertEqual(VisionConfig(minimum_text_height=height).minimum_text_height, height)


if __name__ == "__main__":
    unittest.main()
