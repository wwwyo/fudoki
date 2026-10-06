"""Immutable restore-evidence API. No HTTP, live OCR, or implicit cache locations."""
from __future__ import annotations
import hashlib,json,os,re,tempfile,unicodedata
from pathlib import Path
from html.parser import HTMLParser
H=lambda b:hashlib.sha256(b).hexdigest()
class EvidenceError(ValueError):pass
class Rows(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.rows=[];self.row=None;self.cell=None
 def handle_starttag(self,tag,attrs):
  if tag=='tr':self.row=[]
  if tag in ('td','th') and self.row is not None:self.cell=[]
  if tag=='br' and self.cell is not None:self.cell.append(' ')
 def handle_data(self,data):
  if self.cell is not None:self.cell.append(data)
 def handle_endtag(self,tag):
  if tag in ('td','th') and self.cell is not None:
   self.row.append(re.sub(r'\s+',' ',''.join(self.cell)).strip());self.cell=None
  if tag=='tr' and self.row is not None:
   self.rows.append(self.row);self.row=None

def validate_manifest(manifest):
 if manifest.get('schema_version')!=1:raise EvidenceError('Unsupported immutable manifest version')
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
 """Restore exact refs via caller-supplied transport; verify every SHA/byte before atomic put.

 get_object({sha256,bytes,type,roles,...}) -> bytes. This provider performs no network
 operations. A future authorized caller can supply immutable R2 retrieval separately.
 Existing different bytes are rejected, never overwritten.
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
 def jsonl(self,logical):return [json.loads(l) for l in self.read(logical).decode().splitlines()]
 def image(self,sha,page):
  image_sha=self.bindings[f'native-visual-pages/{sha}/page-{page:02}.png'];self.object(image_sha)
  return {'path':'sha256:'+image_sha,'sha256':image_sha,'bytes':self.objects[image_sha]['bytes']}
 def approval(self,config):
  a=config['approval'];parser=Rows();parser.feed(self.object(a['html_sha256']).decode('utf-8'))
  found=[r for r in parser.rows if r==a['expected_row']]
  if len(found)!=1:raise EvidenceError('Exact bill/title/approval row absent or nonunique in original official HTML: '+a['url'])
  if found[0][3]!='原案可決':raise EvidenceError('Original approval result is not approved')
  return found[0]
 def validate_all(self):
  for sha in self.objects:self.object(sha)
  return {'objects_verified':len(self.objects),'bytes_verified':sum(x['bytes'] for x in self.objects.values())}
 def observed_scope(self,configs):
  pages=[];docs=[]
  for c in configs:
   g=c['identity'];sha=g['prior_sha256'];raw={p['page']:p for p in self.jsonl(f'origins/{sha}/vision-observations.jsonl')};cells={p['page']:p for p in self.jsonl(f'origins/{sha}/vision-cells.jsonl')};amounts={p['page']:p for p in self.jsonl(f'origins/{sha}/vision-amount-cells.jsonl')}
   if H(self.read(f'origins/{sha}/origin.pdf'))!=sha:raise EvidenceError('Whole original identity differs')
   lo,hi=c['expected_scope']
   for page in range(1,g['physical_pages']+1):
    role='expenditure-explanation' if lo<=page<=hi else 'cover' if page==1 else 'first-article' if page==3 else 'expenditure-summary' if page in ([6,7] if g['fund_label']=='国民健康保険特別会計' else [5]) else 'outside-finite-extraction-scope'
    pages.append(dict(origin_sha256=sha,physical_page=page,role=role,full_page_native_observed=page in raw,raw_observation_count=len(raw.get(page,{}).get('observations',[])),raw_cell_observation_count=len(cells.get(page,{}).get('observations',[])),raw_amount_observation_count=len(amounts.get(page,{}).get('observations',[])),phase=None,amount_unit=None,amount=None))
   docs.append(dict(origin_sha256=sha,origin_bytes=g['prior_bytes'],source_url=g['url'],fiscal_year=g['fiscal_year'],account=g['fund_label'],physical_page_count=g['physical_pages'],direct_document_evidence=c['document_direct_evidence'],cover_observations=raw[1],article_observations=raw[3],approval_html_sha256=c['approval']['html_sha256'],approval_original_row=self.approval(c),submitted_date=c['submitted_date'],submitted_evidence_physical_page=3,submitted_evidence_raster=self.image(sha,3),approved_date_from_html=True,phase=None,amount_unit=None,amount=None))
  return pages,docs
