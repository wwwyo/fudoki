"""Pinned runtime — verifies decoder/reconstruct/config match the manifest (held5 shape)."""
import hashlib, json
from pathlib import Path
HERE = Path(__file__).resolve().parent
MANIFEST = HERE / 'runtime-manifest.json'

def _digest(path):
    b = Path(path).read_bytes()
    return {'sha256': hashlib.sha256(b).hexdigest(), 'bytes': len(b)}

def manifest():
    return json.loads(MANIFEST.read_text())

def verify_runtime():
    m = manifest()
    for dest, ref in m['files'].items():
        local = HERE / dest.rsplit('/', 1)[-1]
        if not local.exists() or _digest(local) != ref:
            raise ValueError('runtime pin differs: ' + dest)
    return m
