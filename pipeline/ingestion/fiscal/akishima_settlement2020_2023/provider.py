"""Immutable restore/bundle API for the FY2020-2023 Akishima settlement proposal.

No HTTP, live OCR, model calls or implicit cache locations. Every object read is
verified against the caller-supplied immutable manifest.
"""
from __future__ import annotations
import hashlib,json,os,re,tempfile
from pathlib import Path
from html.parser import HTMLParser
from .decoder import decode_year

H=lambda b:hashlib.sha256(b).hexdigest()
SCHEMA_VERSION=1
NAMESPACE='akishima-settlement2020-2023'

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
    if manifest.get('namespace')!=NAMESPACE:raise EvidenceError('Unsupported manifest namespace')
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
    def recognition(self,year,ycfg):
        rec=ycfg['recognition']
        if rec is None:return {}
        html=self.read(f'recognition/{year}.html').decode('utf-8')
        parser=Rows();parser.feed(html)
        approval={}
        for a in ycfg['accounts']:
            found=[(i,row) for i,row in enumerate(parser.rows,1) if row and row[0]==a['bill'] and '決算認定' in ''.join(row)]
            if len(found)!=1:raise EvidenceError(f'Exact recognition bill row absent or nonunique: {year} {a["bill"]}')
            ordinal,row=found[0]
            if row[1]!=f'令和{year-2018}年度昭島市{a["name"]}歳入歳出決算認定について' or row[3]!='認定':raise EvidenceError('Council recognition row differs: '+a['bill'])
            approval[a['id']]=dict(bill=row[0],cells=row,html_row_ordinal=ordinal,url=rec['url'],sha256=self.bindings[f'recognition/{year}.html'],bytes=self.objects[self.bindings[f'recognition/{year}.html']]['bytes'],recognition_date=rec['recognition_date'],date_context=rec['date_context'])
        if rec['date_context'].split('（')[0] not in html:raise EvidenceError('Recognition meeting context absent')
        return approval

def construct(bundle):
    """Reconstruct all 21 typed account editions + whole-page inventory from immutable inputs."""
    config=bundle.json('config/config.json')
    results={}
    for ycfg in config['years']:
        y=ycfg['fiscal_year']
        origin=bundle.read(f'origin/{y}.pdf')
        if not H(origin)==ycfg['origin']['sha256'] or len(origin)!=ycfg['origin']['bytes']:raise EvidenceError(f'Whole original identity differs: {y}')
        approval=bundle.recognition(y,ycfg)
        result,pages=decode_year(y,bundle.read(f'native/{y}.xhtml'),ycfg,approval)
        results[y]=(result,pages,approval)
    return results,config
