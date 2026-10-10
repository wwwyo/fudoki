"""パイプラインの入出力を作業ディレクトリに依存せず解決する。"""

from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1]
REPO = PIPELINE.parent
CACHE = PIPELINE / '.cache'
BUILD = PIPELINE / '.build'
