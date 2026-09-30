"""原典を再取得し、保管と照合に成功した入力だけを固定する。"""
import os
import subprocess
import sys
import uuid
from ingestion.paths import CACHE, PIPELINE
from ingestion.inputs import migrate


def main() -> None:
    raw = CACHE / 'acquisition' / str(uuid.uuid4()) / 'raw'
    environment = {**os.environ, 'FUDOKI_INPUT_DIR': str(raw), 'FUDOKI_STORE_ORIGIN_REMOTE': '1', 'FUDOKI_REFRESH_ORIGINS': '1'}
    for module in ['fetch', 'extract_projects', 'extract_revenue_accounts', 'extract_statement']:
        subprocess.run([sys.executable, '-m', f'ingestion.fiscal.{module}'], cwd=PIPELINE, env=environment, check=True)
    migrate(raw, remote=True)


if __name__ == '__main__':
    main()
