"""Exact cache-only settlement2019 construction; explicit immutable evidence restore."""
import argparse,hashlib,json
from pathlib import Path
from ingestion.fiscal.akishima_settlement2019 import provider
from ingestion.fiscal.akishima_settlement2019.materialize import build
PKG=Path(__file__).resolve().with_name('akishima_settlement2019')
MANIFEST=PKG/'evidence-manifest.json'

def _objects():
    m=json.loads(MANIFEST.read_bytes())
    if m['schema_version']!=1 or m['namespace']!='akishima-settlement2019':raise ValueError('Unsupported settlement2019 manifest')
    return m

def evidence_objects():
    m=_objects()
    return [dict(key=f"inputs/{o['kind']}/sha256/{o['sha256']}",sha256=o['sha256'],bytes=o['bytes']) for o in m['objects']]

def verify_implementation_bindings():
    m=_objects();checked={}
    for rel,digest in m['bindings'].items():
        p=PKG/rel
        b=p.read_bytes()
        actual=hashlib.sha256(b).hexdigest()
        if actual!=digest:
            raise ValueError('Settlement2019 implementation binding differs: '+rel)
        checked[rel]=actual
    return checked

def restore(objects_dir):
    objects_dir=Path(objects_dir);done=[]
    for ref in evidence_objects():
        p=objects_dir/ref['key'];b=p.read_bytes()
        if len(b)!=ref['bytes'] or hashlib.sha256(b).hexdigest()!=ref['sha256']:raise ValueError('Frozen restored object identity differs: '+ref['key'])
        done.append(ref['key'])
    return {'objects_verified':len(done)}

def extract(objects_dir,output):
    objects_dir=Path(objects_dir)
    verify_implementation_bindings()
    cfg=json.loads((PKG/'config.json').read_bytes())
    # normalized object keys only: inputs/origin/sha256/<sha> is the only
    # accepted origin location; named originals/ directories are not inputs.
    import tempfile
    tmp=tempfile.TemporaryDirectory(prefix='akishima2019-origins-')
    orig=Path(tmp.name)
    for e in cfg['originals']:
        p=objects_dir/'inputs'/'origin'/'sha256'/e['sha256']
        if not p.exists():raise FileNotFoundError('Missing origin object '+e['sha256'])
        b=p.read_bytes()
        if len(b)!=e['bytes'] or hashlib.sha256(b).hexdigest()!=e['sha256']:
            raise ValueError('Origin identity differs '+e['file'])
        (orig/e['file']).write_bytes(b)
    result=build(orig,output)
    decl=json.loads((Path(__file__).parent/'sources-akishima-settlement2019.json').read_bytes())
    lookup={t['table_id']:t for t in decl['editions'][0]['tables']}
    actual=json.loads((Path(output)/'raw-table-manifest.json').read_bytes())
    if len(actual)!=32:raise ValueError('Thirty-two fixed raw resources required')
    for t in actual:
        s=lookup[t['table_id']]
        if t['sha256']!=s['expected_table_sha256'] or t['bytes']!=s['expected_table_bytes'] or t['rows']!=s['expected_rows']:
            raise ValueError('Reconstructed raw table bytes/count differ from fixed resource: '+t['table_id'])
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['describe','restore-evidence','extract'])
    p.add_argument('--object-dir',type=Path);p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.command=='describe':
        print(json.dumps({'accounts':6,'raw_tables':32,'objects':evidence_objects()},ensure_ascii=False));return
    if a.object_dir is None:p.error('--object-dir required')
    if a.command=='restore-evidence':print(json.dumps(restore(a.object_dir)));return
    print(json.dumps(extract(a.object_dir,a.output)))

if __name__=='__main__':
    main()
