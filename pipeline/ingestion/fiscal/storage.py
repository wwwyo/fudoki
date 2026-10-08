"""Private current-table storage; only completed target/direction sets are published."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from ingestion.fiscal.manifest import BUCKET, object_key, sha_file
from ingestion.paths import CACHE

OBJECTS = CACHE / 'objects'


def verify(path: Path, reference: dict) -> None:
    if ('bytes' in reference and path.stat().st_size != reference['bytes']) or sha_file(path) != reference['sha256']:
        raise ValueError('Stored object hash/size differs')


def fetch(reference: dict, *, remote: bool = False) -> Path:
    from ingestion.inputs import safe_relative
    if reference.get('bucket', BUCKET) != BUCKET:
        raise ValueError('Only the private input bucket is supported')
    path = OBJECTS / safe_relative(reference['key'])
    if path.is_symlink() or not path.resolve().is_relative_to(OBJECTS.resolve()):
        raise ValueError('Object cache path escapes its root')
    if path.exists():
        verify(path, reference)
        return path
    if not remote:
        raise FileNotFoundError(f'Object is not cached: {reference["key"]}')
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            subprocess.run(['cf', 'r2', 'objects', 'get', reference['key'], '--bucket-name',
                            reference.get('bucket', BUCKET), '--quiet'], stdout=stream, check=True)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        verify(temporary, reference)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def save(document: dict, table: dict, path: Path, *, remote: bool) -> None:
    key = object_key(document, table['table_id'])
    reference = table['object']
    if reference['key'] != key:
        raise ValueError('Wrong current-table key')
    verify(path, reference)
    if not remote:
        raise ValueError('A saved manifest requires successful private R2 uploads')
    if path.stat().st_size > 300_000_000:
        raise ValueError('cf REST upload limit exceeded; configure a file-based S3 multipart transport')
    subprocess.run(['cf', 'r2', 'objects', 'put', key, '--bucket-name', BUCKET,
                    '--file', str(path), '--quiet'], check=True, stdout=subprocess.DEVNULL)
    cached = OBJECTS / key
    cached.parent.mkdir(parents=True, exist_ok=True)
    if cached.resolve() != path.resolve():
        shutil.copyfile(path, cached)


def cleanup(document: dict) -> int:
    from ingestion.fiscal.manifest import validate, require_current, read, manifest_path
    validate(document)
    require_current(document)
    prefix = object_key(document, 'placeholder').rsplit('/', 1)[0] + '/'
    wanted = {table['object']['key'] for table in document['tables']}
    removed = 0
    after = None
    while True:
        if read(manifest_path(document['target'], document['direction'])) != document:
            raise ValueError('Saved manifest changed; cleanup stopped')
        command = ['cf', 'r2', 'objects', 'list', '--bucket-name', BUCKET, '--prefix', prefix, '--per-page', '1000']
        if after:
            command += ['--start-after', after]
        response = json.loads(subprocess.check_output(command))
        # cf returns an object array, without the API cursor. start-after retains pagination.
        if not isinstance(response, list):
            raise ValueError('Unrecognized R2 listing response; no objects deleted')
        if not response:
            break
        keys = [item['key'] for item in response]
        if keys != sorted(set(keys)) or after is not None and keys[0] <= after:
            raise ValueError('Non-advancing R2 pagination; no page processed')
        for item in response:
            key = item['key']
            if not key.startswith(prefix):
                raise ValueError('R2 list returned an object outside the target/direction')
            if key not in wanted and key.endswith('.parquet') and '/' not in key[len(prefix):]:
                if read(manifest_path(document['target'], document['direction'])) != document:
                    raise ValueError('Saved manifest changed; cleanup stopped')
                subprocess.run(['cf', 'r2', 'objects', 'delete', key, '--bucket-name', BUCKET, '--quiet'],
                               check=True, stdout=subprocess.DEVNULL)
                removed += 1
        after = keys[-1]
    return removed
