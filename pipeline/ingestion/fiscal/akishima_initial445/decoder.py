"""Pure measured decoding of frozen native observations; no OCR or network fallback."""
import json,copy,re
from collections import defaultdict
from . import _statement as E
from ._statement import extract,reconcile
instances=[]
class ObservedNested(E._Nested):
 def __init__(self,levels):super().__init__(levels);self.nodes=[];instances.append(self)
 def add(self,level,name,amount,context):
  self.nodes.append(dict(level=level,name=name,amount=amount,context=dict(context)))
  super().add(level,name,amount,context)
E._Nested=ObservedNested
class Page(list):
 def __init__(self):super().__init__();self.boxes_by_y=defaultdict(list)
def pages_of(raw,lo,hi,minimum_y=0):
 pages={p['page']:p for p in raw};out=[]
 for left in range(lo,hi,2):
  both=[Page(),Page()];obs=sorted([(side,o) for side,p in enumerate([pages[left],pages[left+1]]) for o in p['observations'] if o['bbox'][1]<765 and (o['bbox'][1]>=minimum_y or o['text'].startswith('第'))],key=lambda so:sum(so[1]['bbox'][1::2])/2)
  groups=[]
  for side,o in obs:
   cy=(o['bbox'][1]+o['bbox'][3])/2
   if not groups or cy-groups[-1][0]>5:groups.append([cy,[]])
   groups[-1][1].append((side,o))
  for y,group in groups:
   for side,o in group:
    p=both[side];p.boxes_by_y[y].append(tuple(o['bbox']))
    for c in o['characters']:
     b=c['bbox']
     if c['text'].strip() and (b[2]>b[0] or (side==1 and o.get('zone')==1 and c['text'].isdigit())):
      x=b[0]
      if side==1 and o.get('zone')==1:
       import re
       prefix=re.match(r'^([0-9]{1,2})\s*',o['text'])
       if prefix:
        idx=o['characters'].index(c)
        x=58+idx*5 if idx<len(prefix[1]) else max(74,x)
      p.append((x,y,c['text']))
  out.extend(both)
 return out
def decode(bundle,config):
 sha=config['identity']['prior_sha256']
 raw=copy.deepcopy(bundle.jsonl(f'origins/{sha}/vision-cells.jsonl'))
 full={p['page']:p for p in bundle.jsonl(f'origins/{sha}/vision-observations.jsonl')}
 amounts={p['page']:p for p in bundle.jsonl(f'origins/{sha}/vision-amount-cells.jsonl')}
 for p in raw:
  if p['page']%2:
   import re
   for zone,xlo,xhi in [(2,132,194),(3,475,545)]:
    existing=[o for o in p['observations'] if o.get('zone')==zone and re.fullmatch(r'[0-9, ]+',o['text'])]
    for observed in full[p['page']]['observations']:
     if re.fullmatch(r'[0-9, ]+',observed['text']) and xlo<=observed['bbox'][0]<xhi and observed['bbox'][2]<=xhi and not any(abs((observed['bbox'][1]+observed['bbox'][3]-w['bbox'][1]-w['bbox'][3])/2)<6 for w in existing):
      extra=dict(observed);extra['zone']=zone;p['observations'].append(extra)
   whole=[o for o in p['observations'] if o.get('zone')==3 and re.search(r'[0-9,]+$',o['text']) and o['characters'] and o['characters'][-1]['bbox'][0]>474]
   for o in amounts[p['page']]['observations']:
    if o.get('zone')==4 and re.fullmatch(r'[0-9, ]+',o['text']) and o['bbox'][2]>497 and not any(abs((o['bbox'][1]+o['bbox'][3]-w['bbox'][1]-w['bbox'][3])/2)<6 for w in whole):p['observations'].append(o)
  if p['page']%2==0:
   import re
   heads=[o for o in full[p['page']]['observations'] if re.match(r'^第\s*[0-9]+\s*[款項]',o['text'])]
   p['observations']=[o for o in p['observations'] if not any(abs((o['bbox'][1]+o['bbox'][3]-h['bbox'][1]-h['bbox'][3])/2)<8 for h in heads)]+heads
 lo,hi=config['expected_scope'];spec=copy.deepcopy(config['spec'])
 for correction in config['direct_cells']['native_numeric']:
  found=[]
  for page in raw:
   if page['page']==correction['page']:
    for o in page['observations']:
     if o.get('zone')==correction['zone'] and o['text']==correction['raw'] and correction['y_min']<o['bbox'][1]<correction['y_max']:
      found.append(o);o['text']=correction['confirmed'];o['characters']=[o['characters'][i] for i in correction['character_selection']]
  assert len(found)==1,('source-cell-selector-not-unique',correction)
 pages=pages_of(raw,lo,hi,config['minimum_y']);rows,totals,aux=extract(pages,spec,'expenditure')
 rec=reconcile(rows,totals,aux)
 nodes=[];stack=[];previous=None
 for n in instances[-1].nodes:
  ctx=E._resolve(n['context']);moku=tuple(ctx.get(k+'_code') for k in ['kan','kou','moku']);depth=['project','setsu','detail'].index(n['level'])
  if moku!=previous:stack=[]
  while stack and stack[-1]['depth']>=depth:stack.pop()
  node=dict(node_id=len(nodes)+1,depth=depth,parent_node_id=stack[-1]['node_id'] if stack else None,level=n['level'],printed_name=n['name'],printed_amount=n['amount'],**ctx)
  nodes.append(node);stack.append(node);previous=moku
 child_ids={n['parent_node_id'] for n in nodes if n['parent_node_id'] is not None}
 for n in nodes:
  descendants=[]
  for leaf in nodes:
   if leaf['node_id'] in child_ids:continue
   ancestor=leaf
   while ancestor['parent_node_id'] is not None and ancestor['node_id']!=n['node_id']:ancestor=nodes[ancestor['parent_node_id']-1]
   if ancestor['node_id']==n['node_id']:descendants.append(leaf['printed_amount'])
  n['descendant_leaf_sum']=sum(descendants);n['control_matches']=n['printed_amount']==sum(descendants);n['is_leaf']=n['node_id'] not in child_ids
 rec['individualProjectControls']=sum(n['level']=='project' for n in nodes);rec['individualProjectControlFailures']=sum(n['level']=='project' and not n['control_matches'] for n in nodes);rec['individualSetsuControls']=sum(n['level']=='setsu' for n in nodes);rec['individualSetsuControlFailures']=sum(n['level']=='setsu' and not n['control_matches'] for n in nodes)
 aux['setsu_column']=[dict(path=list(k),amount=v) for k,v in aux['setsu_column'].items()]
 return dict(rows=rows,nodes=nodes,moku=[dict(path=list(k),amount=v) for k,v in totals.items()],aux=aux,summary=rec,spec=spec)
