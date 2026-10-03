"""パイプラインの入出力を作業ディレクトリに依存せず解決する。"""

import os
import hashlib
import json
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
REPO = PIPELINE.parent
CACHE = PIPELINE / '.cache'
BUILD = PIPELINE / '.build'
LATEST = json.loads((BUILD / 'latest.json').read_text()) if (BUILD / 'latest.json').exists() else None
canonical_lock = PIPELINE / 'ingestion/fiscal/sources.lock.json'
INPUT_LOCK = Path(os.environ.get('FUDOKI_INPUT_LOCK', canonical_lock if canonical_lock.exists() else (LATEST or {}).get('inputLock', canonical_lock))).resolve()
SNAPSHOT = hashlib.sha256(INPUT_LOCK.read_bytes()).hexdigest() if INPUT_LOCK.exists() else None
RAW = Path(os.environ.get('FUDOKI_INPUT_DIR', CACHE / 'inputs' / SNAPSHOT / 'raw' if SNAPSHOT else CACHE / 'acquisition' / 'raw'))
PACKAGES = Path(os.environ.get('FUDOKI_PACKAGE_DIR', BUILD / 'builds' / ((LATEST or {}).get('buildId') or 'candidate') / 'fiscal'))
WAREHOUSE = BUILD / 'warehouse.duckdb'
