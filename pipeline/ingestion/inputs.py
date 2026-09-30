"""採用した入力の内容を固定し、検査してからローカルへ復元する。"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import re
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from ingestion.paths import CACHE, PIPELINE, REPO

LOCK = PIPELINE / 'ingestion/fiscal/sources.lock.json'
OBJECTS = CACHE / 'objects'
BUCKET = 'fudoki-inputs'


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def encode(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or '\\' in value or not value or not path.parts or value != str(path) or any(ord(c) < 32 for c in value):
        raise ValueError(f'Unsafe input path: {value}')
    return str(path)


def save_object(kind: str, body: bytes) -> dict:
    sha = digest(body)
    key = f'inputs/{kind}/sha256/{sha}'
    out = OBJECTS / key
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and digest(out.read_bytes()) != sha:
        raise ValueError(f'Corrupt cached object: {key}')
    out.write_bytes(body)
    return {'key': key, 'sha256': sha, 'bytes': len(body)}


def verify_object(ref: dict, body: bytes) -> None:
    if digest(body) != ref['sha256'] or len(body) != ref['bytes']:
        raise ValueError(f'Input hash or size mismatch: {ref["key"]}')


def remote_object(ref: dict, operation: str) -> None:
    path = OBJECTS / safe_relative(ref['key'])
    path.parent.mkdir(parents=True, exist_ok=True)
    command = ['cf', 'r2', 'objects', operation, ref['key'], '--bucket-name', BUCKET, '--quiet']
    if operation == 'put':
        verify_object(ref, path.read_bytes())
        with tempfile.TemporaryFile() as stream:
            existing = subprocess.run(['cf', 'r2', 'objects', 'get', ref['key'], '--bucket-name', BUCKET, '--quiet'], stdout=stream, stderr=subprocess.PIPE)
            if existing.returncode == 0:
                stream.seek(0)
                verify_object(ref, stream.read())
                return
            error = existing.stderr.decode(errors='replace')
            if not re.search(r'(?:HTTP(?: status)?[ :]+404|"status"\s*:\s*404|NoSuchKey)', error, re.IGNORECASE):
                raise RuntimeError('Cannot establish whether the immutable R2 input already exists')
        subprocess.run(command + ['--file', str(path)], check=True, stdout=sys.stderr)
    elif operation == 'get':
        with tempfile.TemporaryFile() as stream:
            subprocess.run(command, check=True, stdout=stream)
            stream.seek(0)
            body = stream.read()
        verify_object(ref, body)
        path.write_bytes(body)
    else:
        raise ValueError('Unsupported object operation')


def read_lock(path: Path = LOCK) -> dict:
    lock = json.loads(path.read_text())
    if lock['schemaVersion'] != 1 or not lock['entries']:
        raise ValueError('Unsupported or empty input snapshot')
    logical = [safe_relative(e['path']) for e in lock['entries']]
    if len(set(logical)) != len(logical):
        raise ValueError('Duplicate logical input paths')
    for e in lock['entries']:
        if not re.fullmatch(r'\d{6}', e['jurisdiction']) or type(e['fiscalYear']) is not int or not 1900 <= e['fiscalYear'] <= 2200:
            raise ValueError('Invalid input jurisdiction or fiscal year')
        if e['documentKind'] not in ['budget', 'supplementary', 'settlement'] or e['direction'] not in ['expenditure', 'revenue', None]:
            raise ValueError('Invalid document or direction')
        if not re.fullmatch(r'[a-f0-9]{64}', e['originEdition']) or e['origin']['sha256'] != e['originEdition']:
            raise ValueError('Input edition differs from its original document')
        if e['origin'].get('availability') != 'stored' or not e['origin'].get('object'):
            raise ValueError('An input snapshot requires every fixed original document')
        if e['origin']['object']['sha256'] != e['originEdition']:
            raise ValueError('Original document object differs from edition')
        partitions = dict(part.split('=', 1) for part in PurePosixPath(e['path']).parts if '=' in part)
        if partitions.get('jurisdiction') != e['jurisdiction'] or partitions.get('year') != str(e['fiscalYear']):
            raise ValueError('Logical input path differs from its scope')
        if e['direction'] is not None and any(partitions.get(key) != value for key, value in [('document_kind', e['documentKind']), ('edition', e['originEdition']), ('direction', e['direction'])]):
            raise ValueError('Statement input path differs from its document or edition')
        for kind, ref in [('table', e['table']), ('provenance', e['provenance']), ('origin', e['origin']['object'])]:
            safe_relative(ref['key'])
            expected = f'inputs/{kind}/sha256/{ref["sha256"]}'
            if ref['key'] != expected or not re.fullmatch(r'[a-f0-9]{64}', ref['sha256']) or type(ref['bytes']) is not int or ref['bytes'] < 0:
                raise ValueError('Input object key does not identify its hash and kind')
    return lock


def restore(path: Path = LOCK, *, remote: bool = False) -> Path:
    lock = read_lock(path)
    snapshot = digest(path.read_bytes())
    out = CACHE / 'inputs' / snapshot / 'raw'
    expected_paths = set()
    for entry in lock['entries']:
        directory = out / safe_relative(entry['path'])
        for name, ref in [('data.parquet', entry['table']), ('provenance.json', entry['provenance'])]:
            cached = OBJECTS / ref['key']
            if not cached.exists():
                if not remote:
                    raise FileNotFoundError(f'Input not cached: {ref["key"]}; run pipeline:inputs restore --remote')
                remote_object(ref, 'get')
            body = cached.read_bytes()
            verify_object(ref, body)
            if name == 'provenance.json':
                provenance = json.loads(body)
                if provenance['sha256'] != entry['originEdition'] or provenance['jurisdiction_code'] != entry['jurisdiction'] or provenance['fiscal_year'] != entry['fiscalYear']:
                    raise ValueError('Provenance differs from fixed input scope or edition')
            directory.mkdir(parents=True, exist_ok=True)
            (directory / name).write_bytes(body)
            expected_paths.add(directory / name)
        ref = entry['origin'].get('object')
        if ref:
            cached = OBJECTS / ref['key']
            if not cached.exists() and remote:
                remote_object(ref, 'get')
            if not cached.exists():
                raise FileNotFoundError(f'Origin not cached: {ref["key"]}')
            verify_object(ref, cached.read_bytes())
    extra = set(out.rglob('*.parquet')) | set(out.rglob('provenance.json'))
    if extra - expected_paths:
        raise ValueError('Unexpected files in fixed input snapshot')
    return out


def origin_path(sha: str) -> Path:
    if not re.fullmatch(r'[a-f0-9]{64}', sha):
        raise ValueError('Invalid original document hash')
    path = OBJECTS / f'inputs/origin/sha256/{sha}'
    if not path.exists() or digest(path.read_bytes()) != sha:
        raise FileNotFoundError(f'Fixed origin unavailable: {sha}')
    return path


def locked_objects(lock: dict) -> dict:
    return {ref['key']: ref for entry in lock['entries'] for ref in [entry['table'], entry['provenance'], entry['origin']['object']]}


def backup(lock_path: Path, output: Path) -> None:
    lock = read_lock(lock_path)
    refs = locked_objects(lock)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', allowZip64=True) as archive:
        archive.writestr('sources.lock.json', lock_path.read_bytes())
        for key, ref in sorted(refs.items()):
            body = (OBJECTS / key).read_bytes()
            verify_object(ref, body)
            archive.writestr(key, body)


def restore_backup(lock_path: Path, archive_path: Path) -> Path:
    lock = read_lock(lock_path)
    refs = locked_objects(lock)
    with zipfile.ZipFile(archive_path) as archive:
        if archive.read('sources.lock.json') != lock_path.read_bytes():
            raise ValueError('Backup belongs to another fixed input snapshot')
        if len(archive.namelist()) != len(refs) + 1 or set(archive.namelist()) != set(refs) | {'sources.lock.json'}:
            raise ValueError('Backup objects differ from the fixed snapshot')
        for key, ref in sorted(refs.items()):
            if archive.getinfo(key).file_size != ref['bytes']:
                raise ValueError('Backup object size differs from fixed snapshot')
            body = archive.read(key)
            verify_object(ref, body)
            out = OBJECTS / safe_relative(key)
            if out.exists():
                verify_object(ref, out.read_bytes())
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(body)
    return restore(lock_path)


def migrate(raw: Path, *, fetch_origins: bool = False, remote: bool = False) -> Path:
    from ingestion.fiscal.sources import all_sources
    declared = all_sources()
    entries = []
    origins = {}
    missing = []
    for provenance in sorted(raw.rglob('provenance.json')):
        prov = json.loads(provenance.read_text())
        sha = prov['sha256']
        if sha not in origins:
            candidate = OBJECTS / f'inputs/origin/sha256/{sha}'
            if not candidate.exists() and fetch_origins:
                from ingestion.lib.http import http_get
                try:
                    got = http_get(prov['request_url'], refresh=True)
                    if got.sha256 == sha:
                        save_object('origin', got.body)
                    else:
                        missing.append({'sha256': sha, 'reason': 'current origin has different hash', 'url': prov['request_url']})
                except Exception as error:
                    missing.append({'sha256': sha, 'reason': str(error), 'url': prov['request_url']})
            origins[sha] = {'sha256': sha, 'availability': 'stored' if candidate.exists() else 'missing'}
            if candidate.exists():
                if digest(candidate.read_bytes()) != sha:
                    raise ValueError(f'Cached origin does not match provenance: {sha}')
                origins[sha]['object'] = save_object('origin', candidate.read_bytes())
        relative = str(provenance.parent.relative_to(raw))
        relative = relative.replace('phase=approved', 'document_kind=budget').replace('phase=settlement','document_kind=settlement')
        if '/document_kind=' in relative and '/edition=' not in relative:
            relative = relative.replace('/direction=', f'/edition={sha}/direction=')
        entries.append({'path': relative, 'jurisdiction': prov['jurisdiction_code'], 'fiscalYear': prov['fiscal_year'],
                        'documentKind': next((p.split('=', 1)[1] for p in Path(relative).parts if p.startswith('document_kind=')), None) or next(s.document_kind for s in declared.values() if s.jurisdiction_code == prov['jurisdiction_code'] and s.fiscal_year == prov['fiscal_year']), 'originEdition': sha,
                        'direction': next((p.split('=', 1)[1] for p in Path(relative).parts if p.startswith('direction=')), None),
                        'table': save_object('table', (provenance.parent / 'data.parquet').read_bytes()),
                        'provenance': save_object('provenance', provenance.read_bytes()), 'origin': origins[sha]})
    lock = {'schemaVersion': 1, 'entries': entries}
    draft = CACHE / 'migration/sources.lock.json'
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_bytes(encode(lock))
    (CACHE / 'migration/missing-origins.json').write_bytes(encode(missing))
    if remote:
        if any(e['origin']['availability'] != 'stored' for e in entries):
            raise ValueError('Cannot pin remote inputs while original documents are missing')
        refs = {r['key']: r for e in entries for r in [e['table'], e['provenance'], e['origin'].get('object')] if r}
        for ref in refs.values():
            remote_object(ref, 'put')
            remote_object(ref, 'get')
            verify_object(ref, (OBJECTS / ref['key']).read_bytes())
        LOCK.write_bytes(encode(lock))
        draft = LOCK
    restore(draft)
    return draft


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    r = sub.add_parser('restore')
    r.add_argument('--lock', type=Path, default=LOCK)
    r.add_argument('--remote', action='store_true')
    m = sub.add_parser('migrate')
    m.add_argument('--raw', type=Path, required=True)
    m.add_argument('--fetch-origins', action='store_true')
    m.add_argument('--remote', action='store_true')
    b = sub.add_parser('backup')
    b.add_argument('--lock', type=Path, default=LOCK)
    b.add_argument('--output', type=Path, required=True)
    b = sub.add_parser('restore-backup')
    b.add_argument('--lock', type=Path, default=LOCK)
    b.add_argument('--archive', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'restore':
        out = restore(args.lock, remote=args.remote)
    elif args.command == 'migrate':
        out = migrate(args.raw, fetch_origins=args.fetch_origins, remote=args.remote)
    elif args.command == 'backup':
        backup(args.lock, args.output)
        out = args.output
    else:
        out = restore_backup(args.lock, args.archive)
    print(json.dumps({'path': str(out)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
