"""Coordinate-preserving PaddleOCR with explicit original-resolution retries.

This module returns native observations, not fiscal cells or corrected values.
Optional OCR packages are imported only when an engine or image is needed.
"""
from __future__ import annotations

import argparse
from contextlib import suppress
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .vision_ocr import OcrRegion


class PaddleOcrError(RuntimeError):
    """OCR failed; the caller receives no partial result."""


@dataclass(frozen=True)
class PaddleConfig:
    dpi: int = 300
    max_pixels: int = 40_000_000
    pdf_renderer: str = "coregraphics"
    render_timeout_seconds: float = 300
    detection_model_name: str = "PP-OCRv6_small_det"
    recognition_model_name: str = "PP-OCRv6_small_rec"
    detection_model_dir: str | None = None
    recognition_model_dir: str | None = None
    cpu_threads: int = 10
    recognition_batch_size: int = 6
    detection_limit_side_len: int = 1280

    def __post_init__(self) -> None:
        if type(self.dpi) is not int or not 72 <= self.dpi <= 600:
            raise ValueError("dpi must be an integer between 72 and 600")
        for name in ("max_pixels", "cpu_threads", "recognition_batch_size", "detection_limit_side_len"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.pdf_renderer not in ("coregraphics", "poppler"):
            raise ValueError("pdf_renderer must be coregraphics or explicit poppler")
        if (type(self.render_timeout_seconds) not in (int, float)
                or not math.isfinite(self.render_timeout_seconds) or self.render_timeout_seconds <= 0):
            raise ValueError("render_timeout_seconds must be finite and positive")
        for name in ("detection_model_name", "recognition_model_name"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or Path(value).name != value:
                raise ValueError(f"{name} must be a model name, not a path")
        for name in ("detection_model_dir", "recognition_model_dir"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a nonempty local path or null")


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _plain(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise PaddleOcrError(f"Native result is not JSON-compatible: {type(value).__name__}")


def _areas(regions: Sequence[OcrRegion] | None) -> tuple[OcrRegion, ...]:
    result = tuple(regions) if regions is not None else (OcrRegion("full-page", (0, 0, 1, 1)),)
    if (not result or any(not isinstance(r, OcrRegion) for r in result)
            or len({r.id for r in result}) != len(result)):
        raise ValueError("regions must be nonempty OcrRegions with distinct ids")
    return result


def _page_numbers(pages: Sequence[int]) -> tuple[int, ...]:
    result = tuple(pages)
    if not result or any(type(p) is not int or p < 1 for p in result) or len(set(result)) != len(result):
        raise ValueError("pages must be distinct positive physical page numbers")
    return result


def _retry_owners(areas, retries):
    owners = {}
    for retry in retries:
        b = retry.bbox_normalized
        candidates = [area for area in areas if area.bbox_normalized[0] <= b[0] and area.bbox_normalized[1] <= b[1]
                      and area.bbox_normalized[2] >= b[2] and area.bbox_normalized[3] >= b[3]]
        if len(candidates) != 1:
            raise ValueError("Each retry must lie inside exactly one declared normal region")
        owners[retry.id] = candidates[0].id
    return owners


def _checked_models(names, directories):
    manifest_path = Path(__file__).with_name("paddle_ocr_models.json")
    manifest_sha = _sha(manifest_path)
    declaration = json.loads(manifest_path.read_text())
    if declaration.get("schema_version") != 1:
        raise PaddleOcrError("Unsupported local model declaration")
    declared = {m["name"]: m for m in declaration["models"]}
    models = []
    for name, directory in zip(names, directories):
        if name not in declared:
            raise PaddleOcrError(f"Model is not declared: {name}")
        for file in declared[name]["files"]:
            path = directory / file["name"]
            if (not path.is_file() or path.stat().st_size != file["bytes"] or _sha(path) != file["sha256"]):
                raise PaddleOcrError(f"Local model missing or hash mismatch: {path}; no models are downloaded")
            models.append({"model_name": name, "path": str(path.resolve()), **file})
    return models, {"path": str(manifest_path), "sha256": manifest_sha}


def _crop_box(region: OcrRegion, width: int, height: int) -> list[int]:
    b = region.bbox_normalized
    return [math.floor(b[0] * width), math.floor(b[1] * height),
            math.ceil(b[2] * width), math.ceil(b[3] * height)]


def _inside(box, roi) -> bool:
    if box is None:
        return False
    x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return roi[0] <= x < roi[2] and roi[1] <= y < roi[3]


def _replace(observations: list[dict], replacements: list[dict], roi: list[int]) -> tuple[list[dict], list[str]]:
    """Replace a region and all its children together by parent-region center."""
    removed = {o["id"] for o in observations if o["kind"] == "region" and _inside(o["bbox_px"], roi)}
    kept, ids = [], []
    for item in observations:
        if item["id"] in removed or item.get("parent_id") in removed:
            ids.append(item["id"])
        else:
            kept.append(item)
    return kept + replacements, ids


def _observation(text, box, *, id, parent, kind, confidence, page, attempt_id):
    width, height = page["image_width"], page["image_height"]
    valid = (box is not None and len(box) == 4 and all(type(v) in (int, float) and math.isfinite(v) for v in box)
             and 0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height)
    b = [float(v) for v in box] if valid else None
    size = page["displayed_pdf_size_pt"]
    return {"id": id, "parent_id": parent, "kind": kind, "raw_text": text,
            "confidence": confidence, "attempt_id": attempt_id,
            "bbox_status": "available" if valid else "unavailable", "bbox_px": b,
            "bbox_normalized": [b[0] / width, b[1] / height, b[2] / width, b[3] / height] if b else None,
            "bbox_pdf_pt": [b[0] * size[0] / width, b[1] * size[1] / height,
                            b[2] * size[0] / width, b[3] * size[1] / height] if b and size else None,
            "page_number": page["page_number"]}


def _observations(native: list[dict], crop: list[int], page: dict, attempt_id: str) -> list[dict]:
    result = []
    for result_index, raw in enumerate(native):
        data = raw["res"]
        texts, scores, polys = data["rec_texts"], data["rec_scores"], data["rec_polys"]
        if not len(texts) == len(scores) == len(polys):
            raise PaddleOcrError("Native region arrays have different lengths")
        word_lists, word_boxes = data.get("text_word", []), data.get("text_word_boxes", [])
        for index, (text, score, polygon) in enumerate(zip(texts, scores, polys)):
            parent = f"{attempt_id}:result{result_index}:r{index}"
            xs, ys = [p[0] + crop[0] for p in polygon], [p[1] + crop[1] for p in polygon]
            box = [min(xs), min(ys), max(xs), max(ys)] if xs else None
            result.append(_observation(text, box, id=parent, parent=None, kind="region",
                                       confidence=score, page=page, attempt_id=attempt_id))
            words = word_lists[index] if index < len(word_lists) else []
            boxes = word_boxes[index] if index < len(word_boxes) else []
            for word_index, word in enumerate(words):
                if not isinstance(word, str) or not word.strip():
                    continue
                local = boxes[word_index] if word_index < len(boxes) else None
                box = ([local[0] + crop[0], local[1] + crop[1], local[2] + crop[0], local[3] + crop[1]]
                       if local is not None and len(local) == 4 else None)
                result.append(_observation(word, box, id=f"{parent}:w{word_index}", parent=parent,
                                           kind="word", confidence=score, page=page, attempt_id=attempt_id))
                # Do not invent substring geometry or drop a printed sign.
                if re.fullmatch(r"[0-9０-９][0-9０-９,，]*", word):
                    result.append(_observation(word, box, id=f"{parent}:n{word_index}", parent=parent,
                                               kind="number", confidence=score, page=page, attempt_id=attempt_id))
    return result


def _run(command: list[str], timeout: float, **kwargs) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, **kwargs)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PaddleOcrError(f"Cannot render PDF: {exc}") from exc
    if result.returncode:
        raise PaddleOcrError(f"PDF renderer failed: {result.stderr.strip()}")
    return result


def _render_pdf(path: Path, pages: Sequence[int], config: PaddleConfig, directory: Path) -> dict:
    if config.pdf_renderer == "coregraphics":
        if platform.system() != "Darwin":
            raise PaddleOcrError("CoreGraphics requires macOS; select poppler explicitly on other platforms")
        helper = Path(__file__).with_name("pdf_render.swift")
        helper_sha = _sha(helper)
        request = {"input_path": str(path), "pages": pages, "output_directory": str(directory),
                   "dpi": config.dpi, "max_pixels": config.max_pixels}
        result = json.loads(_run(["xcrun", "swift", str(helper)], config.render_timeout_seconds,
                                 input=json.dumps(request)).stdout)
        if _sha(helper) != helper_sha:
            raise PaddleOcrError("PDF renderer implementation changed during rendering")
        result["backend_sha256"] = helper_sha
        return result
    version = _run(["pdftoppm", "-v"], config.render_timeout_seconds)
    records = []
    for number in pages:
        info = _run(["pdfinfo", "-box", "-f", str(number), "-l", str(number), str(path)],
                    config.render_timeout_seconds, env={**os.environ, "LC_ALL": "C"}).stdout
        if re.search(r"Encrypted:\s+yes", info):
            raise PaddleOcrError("Encrypted PDFs are not supported")
        match = re.search(rf"Page\s+{number}\s+CropBox:\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", info)
        rotation = re.search(rf"Page\s+{number}\s+rot:\s+(-?\d+)", info)
        if not match or not rotation:
            raise PaddleOcrError(f"Cannot determine CropBox/rotation for physical page {number}")
        box = [float(v) for v in match.groups()]
        size = [box[2] - box[0], box[3] - box[1]]
        if int(rotation[1]) % 180:
            size.reverse()
        if (not all(math.isfinite(v) and v > 0 for v in size)
                or math.ceil(size[0] * config.dpi / 72) * math.ceil(size[1] * config.dpi / 72) > config.max_pixels):
            raise PaddleOcrError("PDF page exceeds max_pixels or has invalid geometry")
        prefix = directory / f"page-{number}"
        _run(["pdftoppm", "-f", str(number), "-l", str(number), "-r", str(config.dpi),
              "-cropbox", "-png", "-singlefile", str(path), str(prefix)], config.render_timeout_seconds)
        records.append({"page_number": number, "image_path": str(prefix.with_suffix(".png")),
                        "displayed_pdf_size_pt": size, "crop_box_pdf_pt": box,
                        "rotation_degrees": int(rotation[1])})
    return {"pages": records, "renderer": "Poppler", "version": (version.stderr or version.stdout).strip(), "dpi": config.dpi}


class PaddleOcr:
    """One lazily loaded local engine shared across images/PDF pages and retries."""

    def __init__(self, config: PaddleConfig = PaddleConfig()):
        if not isinstance(config, PaddleConfig):
            raise ValueError("config must be a PaddleConfig")
        self.config = config
        self._engine = None
        self._engine_metadata = None
        self._closed = False

    def __enter__(self):
        if self._closed:
            raise PaddleOcrError("OCR engine is closed")
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self._engine is not None:
            self._engine.close()
            self._engine = None
        self._closed = True

    def _load_engine(self):
        if self._closed:
            raise PaddleOcrError("OCR engine is closed")
        if self._engine is not None:
            return
        config = self.config
        cache = Path.home() / ".paddlex/official_models"
        dirs = [Path(config.detection_model_dir) if config.detection_model_dir else cache / config.detection_model_name,
                Path(config.recognition_model_dir) if config.recognition_model_dir else cache / config.recognition_model_name]
        names = [config.detection_model_name, config.recognition_model_name]
        models, manifest = _checked_models(names, dirs)
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise PaddleOcrError("PaddleOCR optional dependencies are not installed") from exc
        kwargs = {"ocr_version": "PP-OCRv6", "device": "cpu", "cpu_threads": config.cpu_threads,
                  "text_recognition_batch_size": config.recognition_batch_size,
                  "use_doc_orientation_classify": False, "use_doc_unwarping": False,
                  "use_textline_orientation": False, "text_rec_score_thresh": 0.0,
                  "text_detection_model_name": config.detection_model_name, "text_detection_model_dir": str(dirs[0].resolve()),
                  "text_recognition_model_name": config.recognition_model_name, "text_recognition_model_dir": str(dirs[1].resolve())}
        start = time.perf_counter()
        engine = None
        try:
            engine = PaddleOCR(**kwargs)
            pipe = engine.paddlex_pipeline._pipeline
            actual = {"det_cpu_threads": pipe.text_det_model.runner._config.get("cpu_threads"),
                      "rec_cpu_threads": pipe.text_rec_model.runner._config.get("cpu_threads"),
                      "recognition_batch_size": pipe.text_rec_model.batch_sampler.batch_size}
            if actual != {"det_cpu_threads": config.cpu_threads, "rec_cpu_threads": config.cpu_threads,
                          "recognition_batch_size": config.recognition_batch_size}:
                raise PaddleOcrError("Native PaddleOCR settings differ from requested configuration")
            if _checked_models(names, dirs) != (models, manifest):
                raise PaddleOcrError("Model declaration or model files changed during initialization")
            metadata = {"name": "PaddleOCR", "settings": kwargs, "config": asdict(config),
                        "init_seconds": time.perf_counter() - start, "models": models,
                        "model_manifest": manifest, "actual_engine_settings": actual,
                        "versions": {p: importlib.metadata.version(p) for p in ("paddleocr", "paddlepaddle", "paddlex", "numpy", "pillow")},
                        "platform": platform.platform(), "architecture": platform.machine(),
                        "driver_sha256": _sha(Path(__file__)), "word_confidence": "Inherited native parent-region score"}
        except Exception as exc:
            if engine is not None:
                # Keep the initialization error if cleanup itself also fails.
                with suppress(Exception):
                    engine.close()
            raise PaddleOcrError(f"Cannot initialize local PaddleOCR: {exc}") from exc
        self._engine, self._engine_metadata = engine, metadata

    def _attempt(self, image, page, region, area, index, retry):
        import numpy as np
        crop = _crop_box(area, image.width, image.height)
        rgb = np.array(image.crop(tuple(crop)).convert("RGB"))
        # Paddle's file loader decodes PNG with OpenCV as BGR; match it exactly.
        bgr = np.ascontiguousarray(rgb[:, :, ::-1])
        params = {"return_word_box": True, "text_det_limit_side_len": 64 if retry else self.config.detection_limit_side_len,
                  "text_det_limit_type": "min" if retry else "max"}
        attempt_id = f"p{page['page_number']}:{region.id}:a{index}"
        start = time.perf_counter()
        try:
            native = _plain([r.json for r in self._engine.predict(bgr, **params)])
        except Exception as exc:
            raise PaddleOcrError(f"PaddleOCR failed in {attempt_id}: {exc}") from exc
        seconds = time.perf_counter() - start
        observations = _observations(native, crop, page, attempt_id)
        return {"id": attempt_id, "region_id": region.id, "retry_region_id": area.id if retry else None,
                "crop_bbox_px": crop, "bbox_normalized": area.bbox_normalized,
                "predict_settings": params, "inference_seconds": seconds,
                "input_rgb_pixel_sha256": hashlib.sha256(rgb.tobytes()).hexdigest(),
                "input_bgr_pixel_sha256": hashlib.sha256(bgr.tobytes()).hexdigest(),
                "input_image_size_px": [rgb.shape[1], rgb.shape[0]],
                "native": native, "observations": observations}

    def _read_page(self, image, page, areas, retries):
        if image.width * image.height > self.config.max_pixels:
            raise ValueError("Image exceeds max_pixels")
        page.update(image_width=image.width, image_height=image.height)
        owners = _retry_owners(areas, retries)
        self._load_engine()
        regions, attempts = [], []
        for area in areas:
            attempt = self._attempt(image, page, area, area, len(attempts), False)
            attempts.append(attempt)
            regions.append({"id": area.id, "crop_bbox_px": attempt["crop_bbox_px"],
                            "observations": list(attempt["observations"]), "attempt_ids": [attempt["id"]]})
        for retry in retries:
            region = next(r for r in regions if r["id"] == owners[retry.id])
            area = next(a for a in areas if a.id == region["id"])
            attempt = self._attempt(image, page, area, retry, len(attempts), True)
            active, removed = _replace(region["observations"], attempt["observations"], attempt["crop_bbox_px"])
            attempt["superseded_observation_ids"] = removed
            attempts.append(attempt)
            region["observations"] = active
            region["attempt_ids"].append(attempt["id"])
        page.update(regions=regions, attempts=attempts)
        return page

    def _recognize(self, path, kind, pages, regions, retry_regions):
        started = time.perf_counter()
        path = Path(path).resolve(strict=True)
        if not path.is_file():
            raise ValueError("OCR input must be a file")
        areas = _areas(regions)
        if not isinstance(retry_regions, Mapping):
            raise ValueError("retry_regions must be keyed by physical page")
        retries = {p: tuple(v) for p, v in retry_regions.items()}
        if any(type(p) is not int or p not in pages for p in retries):
            raise ValueError("Retry pages must be requested physical pages")
        for values in retries.values():
            if values:
                _areas(values)
                _retry_owners(areas, values)
        origin_sha = _sha(path)
        try:
            from PIL import Image
        except ImportError as exc:
            raise PaddleOcrError("Pillow optional dependency is not installed") from exc
        output = []
        render_start = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="fudoki-paddle-render-") as temporary:
            if kind == "pdf":
                render = _render_pdf(path, pages, self.config, Path(temporary))
            else:
                render = {"renderer": "input-image", "pages": [{"page_number": 1, "image_path": str(path),
                           "displayed_pdf_size_pt": None}]}
            render_seconds = time.perf_counter() - render_start
            for record in render["pages"]:
                image_path = Path(record["image_path"])
                with Image.open(image_path) as image:
                    if image.width * image.height > self.config.max_pixels:
                        raise ValueError("Image exceeds max_pixels")
                    if kind == "image" and image.getexif().get(274, 1) != 1:
                        raise ValueError("Image EXIF rotation must be made upright before OCR")
                    image.load()
                    rgb = image.convert("RGB")
                    page = {k: v for k, v in record.items() if k != "image_path"}
                    image_file_sha = _sha(image_path)
                    page.update(image_file_sha256=image_file_sha,
                                rendered_png_sha256=image_file_sha if kind == "pdf" or image.format == "PNG" else None,
                                rendered_rgb_pixel_sha256=hashlib.sha256(rgb.tobytes()).hexdigest())
                    output.append(self._read_page(rgb, page, areas, retries.get(record["page_number"], ())))
        if _sha(path) != origin_sha:
            raise PaddleOcrError("OCR input changed during recognition")
        if _sha(Path(__file__)) != self._engine_metadata["driver_sha256"]:
            raise PaddleOcrError("OCR implementation changed during recognition")
        return {"schema_version": 1, "origin": {"path": str(path), "sha256": origin_sha, "bytes": path.stat().st_size},
                "engine": self._engine_metadata, "renderer": {k: v for k, v in render.items() if k != "pages"},
                "render_seconds": render_seconds, "elapsed_seconds": time.perf_counter() - started, "pages": output}

    def recognize_image(self, path: Path, *, regions: Sequence[OcrRegion] | None = None,
                        retry_regions: Sequence[OcrRegion] = ()) -> dict:
        return self._recognize(path, "image", (1,), regions, {1: retry_regions})

    def recognize_pdf(self, path: Path, *, pages: Sequence[int], regions: Sequence[OcrRegion] | None = None,
                      retry_regions: Mapping[int, Sequence[OcrRegion]] | None = None) -> dict:
        return self._recognize(path, "pdf", _page_numbers(pages), regions,
                               {} if retry_regions is None else retry_regions)


def recognize_image(path: Path, *, config: PaddleConfig = PaddleConfig(), regions=None, retry_regions=()) -> dict:
    with PaddleOcr(config) as ocr:
        return ocr.recognize_image(path, regions=regions, retry_regions=retry_regions)


def recognize_pdf(path: Path, *, pages: Sequence[int], config: PaddleConfig = PaddleConfig(), regions=None, retry_regions=None) -> dict:
    with PaddleOcr(config) as ocr:
        return ocr.recognize_pdf(path, pages=pages, regions=regions, retry_regions=retry_regions)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("schema")
    run = sub.add_parser("recognize")
    run.add_argument("--params", required=True, help="JSON request or @path")
    args = parser.parse_args()
    if args.command == "schema":
        print(json.dumps({"schema_version": 1, "request": {"path": "local file", "kind": "pdf | image",
              "pages": "distinct physical page numbers; PDF only", "config": asdict(PaddleConfig()),
              "regions": [{"id": "full-page", "bbox_normalized": [0, 0, 1, 1]}],
              "retry_regions": "PDF: object keyed by physical page, each value a region list; image: region list"},
              "output": {"schema_version": 1, "pages": "Vision-compatible active observations plus unchanged native attempts",
              "coordinates": "top-left full page px/normalized/displayed CropBox pt; null pt for images",
              "retry_policy": "parent-region center inside ROI removes parent and all children; cross-boundary parents may remain",
              "numbers": "native whole-word digit/comma matches only; sign-bearing raw word remains intact"}}, ensure_ascii=False))
        return 0
    try:
        payload = json.loads(Path(args.params[1:]).read_text() if args.params.startswith("@") else args.params)
        if not isinstance(payload, dict) or set(payload) - {"path", "kind", "pages", "config", "regions", "retry_regions"}:
            raise ValueError("Unknown request fields or request is not an object")
        config = PaddleConfig(**payload.get("config", {}))
        regions = [OcrRegion(**r) for r in payload["regions"]] if "regions" in payload else None
        with PaddleOcr(config) as ocr:
            if payload["kind"] == "pdf":
                raw_retries = payload.get("retry_regions", {})
                if not isinstance(raw_retries, dict) or any(not re.fullmatch(r"[1-9][0-9]*", k) for k in raw_retries):
                    raise ValueError("PDF retry_regions must be keyed by positive physical page strings")
                retries = {int(k): [OcrRegion(**r) for r in v] for k, v in raw_retries.items()}
                result = ocr.recognize_pdf(Path(payload["path"]), pages=payload["pages"], regions=regions, retry_regions=retries)
            elif payload["kind"] == "image":
                if "pages" in payload:
                    raise ValueError("Image requests must omit pages")
                retries = [OcrRegion(**r) for r in payload.get("retry_regions", [])]
                result = ocr.recognize_image(Path(payload["path"]), regions=regions, retry_regions=retries)
            else:
                raise ValueError("kind must be pdf or image")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (KeyError, TypeError, ValueError, OSError, PaddleOcrError) as exc:
        print(json.dumps({"error": {"code": "paddle_ocr_failed", "message": str(exc)}}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
