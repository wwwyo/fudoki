"""Locate printed rules in independently rendered original pages, without OCR."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


def clusters(indices, size):
    groups = []
    for index in indices:
        if not groups or index - groups[-1][-1] > 2:
            groups.append([])
        groups[-1].append(int(index))
    return [sum(group) / len(group) / size for group in groups]


def inspect(directory):
    result = {}
    for page in (8, 9, 16, 17, 18, 19):
        path = directory / f'page-{page}.png'
        image = Image.open(path).convert('L')
        dark = np.asarray(image.filter(ImageFilter.MinFilter(7))) < 190
        height, width = dark.shape
        top, bottom = (.168, .52) if page in (8, 9) else (.208, .89)
        scores = dark[int(top*height):int(bottom*height), :].mean(axis=0)
        indices = np.flatnonzero(scores > .70)
        indices = indices[(indices > .05*width) & (indices < .96*width)]
        info = {'width': width, 'height': height, 'x_edges': clusters(indices, width),
                'image_path': str(path.resolve()),
                'image_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        if page in (9, 17, 19):
            left, right = (.11, .89) if page == 9 else (.11, .65)
            top, bottom = (.16, .53) if page == 9 else (.205, .9)
            scores = dark[:, int(left*width):int(right*width)].mean(axis=1)
            indices = np.flatnonzero(scores > .70)
            indices = indices[(indices > top*height) & (indices < bottom*height)]
            info['edges'] = clusters(indices, height)
        result[str(page)] = info
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = inspect(args.images)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({p: {'columns': len(v['x_edges'])-1,
                          'rows': len(v.get('edges', []))-1} for p,v in result.items()}))


if __name__ == '__main__':
    main()
