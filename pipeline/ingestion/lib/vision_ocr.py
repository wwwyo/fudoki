"""Reusable macOS Vision OCR. Returns observations, not fiscal rows or cells.

Use explicit physical PDF pages and optional normalized page regions. Raw text
and page coordinates are preserved; name correction lives in ``ocr_names``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class VisionConfig:
    dpi: int = 300
    revision: int = 3
    languages: tuple[str, ...] = ("ja-JP", "en-US")
    language_correction: bool = False
    max_pixels: int = 40_000_000
    custom_words: tuple[str, ...] = ()
    vocabulary_path: str | None = None
    minimum_text_height: float | None = None

    def __post_init__(self) -> None:
        if type(self.dpi) is not int or not 72 <= self.dpi <= 600:
            raise ValueError("dpi must be an integer between 72 and 600")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer")
        if (not isinstance(self.languages, (tuple, list)) or not self.languages
                or any(not isinstance(x, str) or not x for x in self.languages)):
            raise ValueError("languages must contain nonempty language identifiers")
        if type(self.language_correction) is not bool:
            raise ValueError("language_correction must be a boolean")
        if (not isinstance(self.custom_words, (tuple, list))
                or any(not isinstance(x, str) or not x.strip() for x in self.custom_words)):
            raise ValueError("custom_words must be a list or tuple of nonempty words")
        if self.custom_words and not self.language_correction:
            raise ValueError("custom_words requires language_correction=true; Vision otherwise ignores it")
        if self.vocabulary_path is not None and (
                not isinstance(self.vocabulary_path, str) or not self.vocabulary_path.strip()):
            raise ValueError("vocabulary_path must be a nonempty path string or null")
        if type(self.max_pixels) is not int or self.max_pixels < 1:
            raise ValueError("max_pixels must be a positive integer")
        if self.minimum_text_height is not None and (
                type(self.minimum_text_height) not in (float, int)
                or not math.isfinite(self.minimum_text_height)
                or not 0 <= self.minimum_text_height <= 1):
            raise ValueError("minimum_text_height must be a finite fraction between 0 and 1, or null")


@dataclass(frozen=True)
class OcrRegion:
    id: str
    bbox_normalized: tuple[float, float, float, float]

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("Region id must be nonempty")
        b = self.bbox_normalized
        if (len(b) != 4 or any(type(x) not in (int, float) or not math.isfinite(x) for x in b)
                or not (0 <= b[0] < b[2] <= 1 and 0 <= b[1] < b[3] <= 1)):
            raise ValueError("Region bbox must be [xMin,yMin,xMax,yMax], top-left, normalized 0..1")


class VisionOcrError(RuntimeError):
    """Native OCR failed; no partial result is returned."""


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _load_vocabulary(path: Path) -> tuple[list[str], dict]:
    path = path.resolve(strict=True)
    data = path.read_bytes()
    payload = json.loads(data)
    if (not isinstance(payload, dict) or type(payload.get("schema_version")) is not int
            or payload["schema_version"] != 1 or set(payload) - {"schema_version", "description", "words"}):
        raise ValueError("Vocabulary must be a schema_version 1 object with words")
    words = payload.get("words")
    if (not isinstance(words, list)
            or any(not isinstance(word, str) or not word.strip() for word in words)):
        raise ValueError("Vocabulary words must be an array of nonempty strings")
    return words, {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def _recognize(path: Path, kind: str, pages: Sequence[int], config: VisionConfig,
               regions: Sequence[OcrRegion] | None, timeout_seconds: float) -> dict:
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ValueError("OCR input must be a file")
    pages = tuple(pages)
    if not pages or any(type(p) is not int or p < 1 for p in pages) or len(set(pages)) != len(pages):
        raise ValueError("pages must be distinct positive physical page numbers")
    areas = tuple(regions) if regions is not None else (OcrRegion("full-page", (0, 0, 1, 1)),)
    if not areas or len({area.id for area in areas}) != len(areas):
        raise ValueError("regions must be nonempty and have distinct ids")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    native_config = asdict(config)
    vocabulary_path = native_config.pop("vocabulary_path")
    vocabulary = None
    if config.language_correction:
        words, vocabulary = _load_vocabulary(
            Path(vocabulary_path) if vocabulary_path is not None
            else Path(__file__).with_name("ocr_vocabulary.json"))
        native_config["custom_words"] = list(dict.fromkeys([*words, *config.custom_words]))
    if platform.system() != "Darwin":
        raise VisionOcrError("Apple Vision OCR requires macOS; no engine is substituted")
    helper = Path(__file__).with_suffix(".swift")
    origin_sha = _sha256(path)
    code_hashes = {"driver_sha256": _sha256(Path(__file__)), "backend_sha256": _sha256(helper)}
    request = {"input_path": str(path), "input_kind": kind, "pages": pages,
               "config": native_config, "regions": [asdict(area) for area in areas]}
    try:
        process = subprocess.run(
            ["xcrun", "swift", str(helper)], input=json.dumps(request),
            capture_output=True, text=True, timeout=timeout_seconds, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VisionOcrError(f"Cannot complete Vision OCR: {exc}") from exc
    if process.returncode:
        raise VisionOcrError(f"Vision OCR failed ({process.returncode}): {process.stderr.strip()}")
    result = json.loads(process.stdout)
    # Never label observations with the hash of a different input revision.
    if _sha256(path) != origin_sha:
        raise VisionOcrError("OCR input changed during recognition")
    if code_hashes != {"driver_sha256": _sha256(Path(__file__)), "backend_sha256": _sha256(helper)}:
        raise VisionOcrError("OCR implementation changed during recognition")
    result["origin"] = {"path": str(path), "sha256": origin_sha, "bytes": path.stat().st_size}
    result["engine"].update(code_hashes)
    result["engine"]["architecture"] = platform.machine()
    result["engine"]["vocabulary"] = vocabulary
    return result


def recognize_pdf(path: Path, *, pages: Sequence[int], config: VisionConfig = VisionConfig(),
                  regions: Sequence[OcrRegion] | None = None, timeout_seconds: float = 300) -> dict:
    """Read selected physical pages; use the same page-relative regions on each.

    Bboxes use the displayed CropBox with PDF rotation applied, top-left origin.
    This does not select text-vs-scan extraction, infer cells, or repair names.
    """
    return _recognize(path, "pdf", pages, config, regions, timeout_seconds)


def recognize_image(path: Path, *, config: VisionConfig = VisionConfig(),
                    regions: Sequence[OcrRegion] | None = None, timeout_seconds: float = 300) -> dict:
    """Read an upright image. Coordinates refer to its original pixel dimensions."""
    return _recognize(path, "image", (1,), config, regions, timeout_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("schema", help="Describe request and output coordinates as JSON")
    run = sub.add_parser("recognize", help="Emit raw OCR JSON to stdout; errors go to stderr")
    run.add_argument("--params", required=True, help="JSON object, or @path to a JSON request")
    args = parser.parse_args()
    if args.command == "schema":
        print(json.dumps({"schema_version": 1, "request": {
            "path": "local PDF or upright image path", "kind": "pdf | image",
            "pages": "required distinct positive physical pages for PDF; omit for image",
            "config": asdict(VisionConfig()),
            "vocabulary": "language_correction=true loads sibling ocr_vocabulary.json; config.vocabulary_path overrides it; custom_words appends hints",
            "regions": [{"id": "column-name", "bbox_normalized": [0, 0, 1, 1]}],
            "timeout_seconds": 300}, "output": {
            "schema_version": 1, "pages": "page_number, pixel size, displayed PDF size, regions",
            "observations": "region | word | number; raw_text, confidence, parent_id, bbox_status, bboxes",
            "bbox_px": "top-left page pixels, restored after cropping",
            "bbox_normalized": "top-left page-relative 0..1",
            "bbox_pdf_pt": "top-left displayed CropBox points; null for image input",
            "limits": "unavailable boxes are null; word precision, no cell completeness guarantee; names corrected separately"}}, ensure_ascii=False))
        return 0
    try:
        payload = json.loads(Path(args.params[1:]).read_text() if args.params.startswith("@") else args.params)
        allowed = {"path", "kind", "pages", "config", "regions", "timeout_seconds"}
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise ValueError("Unknown request fields or request is not an object")
        config = VisionConfig(**payload.get("config", {}))
        regions = [OcrRegion(**area) for area in payload["regions"]] if "regions" in payload else None
        options = {"config": config, "regions": regions, "timeout_seconds": payload.get("timeout_seconds", 300)}
        if payload["kind"] == "pdf":
            result = recognize_pdf(Path(payload["path"]), pages=payload["pages"], **options)
        elif payload["kind"] == "image":
            if "pages" in payload:
                raise ValueError("Image requests must omit pages")
            result = recognize_image(Path(payload["path"]), **options)
        else:
            raise ValueError("kind must be pdf or image")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (KeyError, TypeError, ValueError, OSError, VisionOcrError) as exc:
        print(json.dumps({"error": {"code": "vision_ocr_failed", "message": str(exc)}}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
