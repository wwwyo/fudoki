"""Immutable restore/bundle API for the FY2024 Akishima settlement proposal.

No HTTP, live OCR, model calls or implicit cache locations. Every object read is
verified against the caller-supplied immutable manifest.
"""
from __future__ import annotations
import hashlib,json,os,re,tempfile
from pathlib import Path
from html.parser import HTMLParser
from .decoder import decode

H=lambda b:hashlib.sha256(b).hexdigest()
SCHEMA_VERSION=1

class EvidenceError(ValueError):pass

class Rows(HTMLParser):
    def __init__(self):super().__init__();self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.row=[]
        if tag in ('td','th') and self.row is not None:self.cell=[]
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:self.row.append(''.join(self.cell).strip());self.cell=None
        if tag=='tr' and self.row is not None:self.rows.append(self.row);self.row=None

def validate_manifest(manifest):
    if manifest.get('schema_version')!=SCHEMA_VERSION:raise EvidenceError('Unsupported immutable manifest version')
    objects={}
    for x in manifest['objects']:
        sha=x['sha256']
        if not re.fullmatch('[a-f0-9]{64}',sha) or not isinstance(x['bytes'],int) or x['bytes']<=0:raise EvidenceError('Invalid immutable object identity')
        if sha in objects:raise EvidenceError('Duplicate immutable object')
        objects[sha]=x
    for logical,sha in manifest['bindings'].items():
        if logical.startswith('/') or '..' in logical.split('/') or any(ord(c)<32 for c in logical) or sha not in objects:raise EvidenceError('Invalid logical evidence binding')
    return objects

def restore_evidence(manifest,destination,get_object):
    """Restore exact refs via caller-supplied transport; verify every SHA/byte.

    get_object({sha256,bytes,...}) -> bytes. This provider performs no network
    operations. Existing different bytes are rejected, never overwritten.
    """
    objects=validate_manifest(manifest);destination=Path(destination)
    for sha,ref in sorted(objects.items()):
        p=destination/'objects/sha256'/sha
        body=p.read_bytes() if p.exists() else get_object(dict(ref))
        if len(body)!=ref['bytes'] or H(body)!=sha:raise EvidenceError('Immutable object verification failed: '+sha)
        if not p.exists():
            p.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as f:f.write(body);tmp=Path(f.name)
            try:os.link(tmp,p)
            except FileExistsError:
                if p.read_bytes()!=body:raise EvidenceError('Concurrent immutable-object body mismatch')
            finally:tmp.unlink()
    return {'objects_verified':len(objects),'bytes_verified':sum(x['bytes'] for x in objects.values())}

class Bundle:
    def __init__(self,cache,manifest):
        self.cache=Path(cache).resolve();self.manifest=manifest;self.objects=validate_manifest(manifest);self.bindings=manifest['bindings'];self.accesses=set()
    def object(self,sha):
        if sha not in self.objects:raise EvidenceError('Undeclared evidence SHA')
        b=(self.cache/'objects/sha256'/sha).read_bytes();ref=self.objects[sha]
        if len(b)!=ref['bytes'] or H(b)!=sha:raise EvidenceError('Corrupt or incorrect cached evidence: '+sha)
        self.accesses.add(sha);return b
    def read(self,logical):return self.object(self.bindings[logical])
    def json(self,logical):return json.loads(self.read(logical))
    def validate_all(self):
        for sha in self.objects:self.object(sha)
        return {'objects_verified':len(self.objects),'bytes_verified':sum(x['bytes'] for x in self.objects.values())}
    def recognition(self,config):
        parser=Rows();parser.feed(self.read('recognition.html').decode('utf-8'))
        approval={}
        for a in config['accounts']:
            found=[(i,row) for i,row in enumerate(parser.rows,1) if row and row[0]==a['bill']]
            if len(found)!=1:raise EvidenceError('Exact recognition bill row absent or nonunique: '+a['bill'])
            ordinal,row=found[0]
            expected=[a['bill'],f'令和6年度昭島市{a["name"]}歳入歳出決算認定について','10月2日','認定']
            if row!=expected:raise EvidenceError('Council recognition row differs: '+a['bill'])
            approval[a['id']]=dict(bill=row[0],cells=row,html_row_ordinal=ordinal,url=config['recognition_url'],sha256=self.bindings['recognition.html'],bytes=self.objects[self.bindings['recognition.html']]['bytes'],recognition_date='2025-10-02',date_context='令和7年第3回定例会（9月2日から10月2日まで）')
        if '令和7年第3回定例会' not in self.read('recognition.html').decode('utf-8'):raise EvidenceError('Recognition meeting context absent')
        return approval

def construct(bundle):
    """Reconstruct the three finite roles and 651 physical pages from immutable inputs."""
    config=bundle.json('config/config.json')
    origin=config['origin']
    if not H(bundle.read('origin.pdf'))==config['origin']['sha256']==bundle.manifest['origin_sha256']:raise EvidenceError('Whole original identity differs')
    if len(bundle.read('origin.pdf'))!=config['origin']['bytes']:raise EvidenceError('Whole original size differs')
    approval=bundle.recognition(config)
    cells=bundle.json('health-summary/direct-cells.json')
    if cells['original_sha256']!=origin['sha256']:raise EvidenceError('Direct-cell ledger is bound to a different original')
    render=bundle.read('health-summary/render.png')
    if H(render)!=cells['render_sha256'] or len(render)!=cells['render_bytes']:raise EvidenceError('Direct-cell render identity differs')
    result,pp=decode(bundle.read('native-bbox.xhtml'),config,approval,cells)
    return result,pp,config,approval
