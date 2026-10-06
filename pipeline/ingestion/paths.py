"""パイプラインの入出力を作業ディレクトリに依存せず解決する。

環境変数の相対指定は PIPELINE からの相対とみなす。
pipeline/paths.ts と同じ解決規則の twin 実装。片方を変えたらもう片方も同期する。
"""

import os
import hashlib
import json
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
REPO = PIPELINE.parent
CACHE = PIPELINE / '.cache'
BUILD = PIPELINE / '.build'
LATEST = json.loads((BUILD / 'latest.json').read_text()) if (BUILD / 'latest.json').exists() else None


def _anchor(path: str | Path) -> Path:
    return (PIPELINE / Path(path)).resolve()


canonical_lock = PIPELINE / 'ingestion/fiscal/sources.lock.json'
INPUT_LOCK = _anchor(os.environ.get('FUDOKI_INPUT_LOCK', canonical_lock if canonical_lock.exists() else (LATEST or {}).get('inputLock', canonical_lock)))
SNAPSHOT = hashlib.sha256(INPUT_LOCK.read_bytes()).hexdigest() if INPUT_LOCK.exists() else None
RAW = _anchor(os.environ.get('FUDOKI_INPUT_DIR', CACHE / 'inputs' / SNAPSHOT / 'raw' if SNAPSHOT else CACHE / 'acquisition' / 'raw'))
PACKAGES = _anchor(os.environ.get('FUDOKI_PACKAGE_DIR', BUILD / 'builds' / ((LATEST or {}).get('buildId') or 'candidate') / 'fiscal'))
WAREHOUSE = BUILD / 'warehouse.duckdb'

def plain_path(path):
    """Absolute path with no symlinked ancestor; symlinks are evidence, not resolved away."""
    p = Path(path).absolute()
    if '..' in p.parts:
        raise ValueError('absolute traversal')
    current = Path(p.anchor)
    for part in p.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError('symlink ancestor: ' + str(current))
    return p
