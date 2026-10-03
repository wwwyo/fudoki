"""既存の構築メタデータから新しいパイプラインを起動できることを検査する。"""

import json
import os
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest
from unittest.mock import patch


class PathsTest(unittest.TestCase):
    def test_legacy_build_metadata_allows_import_before_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            pipeline = Path(directory).resolve() / 'pipeline'
            module = pipeline / 'ingestion/paths.py'
            module.parent.mkdir(parents=True)
            shutil.copyfile(Path(__file__).with_name('paths.py'), module)
            build = pipeline / '.build'
            build.mkdir()
            lock = pipeline / 'old-inputs.lock.json'
            lock.write_text('{}')
            (build / 'latest.json').write_text(json.dumps({
                'releaseId': 'r-old', 'inputLock': str(lock),
            }))
            environment = {key: value for key, value in os.environ.items()
                           if key not in {'FUDOKI_INPUT_LOCK', 'FUDOKI_INPUT_DIR', 'FUDOKI_PACKAGE_DIR'}}
            with patch.dict(os.environ, environment, clear=True):
                paths = runpy.run_path(str(module))
                self.assertEqual(paths['INPUT_LOCK'], lock)
                self.assertEqual(paths['PACKAGES'], build / 'builds/candidate/fiscal')
                override = pipeline / 'working/fiscal'
                with patch.dict(os.environ, {'FUDOKI_PACKAGE_DIR': str(override)}):
                    paths = runpy.run_path(str(module))
                    self.assertEqual(paths['PACKAGES'], override)


if __name__ == '__main__':
    unittest.main()
