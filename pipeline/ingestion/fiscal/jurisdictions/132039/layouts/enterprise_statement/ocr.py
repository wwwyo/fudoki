"""Explicit, lease-controlled OCR capture; never overwrite native observations."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import time

from ingestion.lib.scan_ocr import OcrRegion, PaddleConfig, PaddleOcr, recognize_pdf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pages", type=int, nargs="+", required=True)
    parser.add_argument("--crop-request", type=Path)
    args = parser.parse_args()
    if hashlib.sha256(args.source.read_bytes()).hexdigest() != args.sha256:
        raise ValueError("Original SHA differs")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "pid.txt").write_text(str(os.getpid()) + "\n")
    start = time.monotonic()
    config = PaddleConfig(
        dpi=300, detection_limit_side_len=1280, cpu_threads=10,
        recognition_batch_size=6)
    if args.crop_request:
        request = json.loads(args.crop_request.read_text())
        if [r['page'] for r in request] != args.pages:
            raise ValueError('Crop request page scope differs')
        result = []
        with PaddleOcr(config) as engine:
            for spec in request:
                regions = [OcrRegion(r['id'],tuple(r['bbox_normalized'])) for r in spec['regions']]
                page_result = engine.recognize_pdf(args.source,pages=[spec['page']],regions=regions)
                data = (json.dumps(page_result,ensure_ascii=False,indent=2)+'\n').encode()
                filename = f"page-{spec['page']}.json"
                (args.output/filename).write_bytes(data)
                result.append({'path':filename,'sha256':hashlib.sha256(data).hexdigest(),
                               'regions':[r.id for r in regions]})
    else:
        result = recognize_pdf(args.source, pages=args.pages, config=config)
    data = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()
    (args.output / "native.json").write_bytes(data)
    summary = {"pid": os.getpid(), "wall_seconds": time.monotonic() - start,
               "native_sha256": hashlib.sha256(data).hexdigest(),
               "source_sha256": args.sha256, "pages": args.pages}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
