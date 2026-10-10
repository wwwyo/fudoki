"""Assign remarks by printed horizontal rules rasterized independently with Poppler."""
import argparse,bisect,hashlib,json,re,subprocess
from pathlib import Path

def observe(pdf,origin,out):
 o=json.loads(origin.read_text())
 if hashlib.sha256(pdf.read_bytes()).hexdigest()!=o['sha256']:raise ValueError('SHA differs')
 out.mkdir(parents=True,exist_ok=False);cells=[];unowned=[];borders=[]
 for note in o['notes']:
  page=note['page'];pgm=subprocess.check_output(['pdftoppm','-f',str(page),'-l',str(page),'-singlefile','-gray','-r','144',str(pdf)])
  m=re.match(rb'P5\s+(\d+)\s+(\d+)\s+255\s',pgm);width,height=map(int,m.groups());pix=pgm[m.end():]
  hits=[y/2 for y in range(height) if sum(v<160 for v in pix[y*width+920:y*width+1120])>=190]
  runs=[]
  for y in hits:
   if not runs or y-runs[-1][-1]>1:runs.append([y])
   else:runs[-1].append(y)
  edges=[sum(r)/len(r) for r in runs];borders.append(dict(page=page,edges=edges))
  anchors=[n for n in o['nodes'] if n['right_page']==page]
  assignments={}
  for n in anchors:
   idx=bisect.bisect_right(edges,n['y']+4)-1
   assignments.setdefault(idx,[]).append(n)
  for idx in range(len(edges)-1):
   ls=[l for l in note['lines'] if edges[idx]<l['y']+4<edges[idx+1]]
   if not ls:continue
   owners=assignments.get(idx,[])
   if not owners:unowned.append(dict(page=page,edges=edges[idx:idx+2],lines=ls));continue
   cells.append(dict(page=page,edges=edges[idx:idx+2],paths=[n['path'] for n in owners],levels=[n['level'] for n in owners],text='\n'.join(l['text'] for l in ls)))
  for l in note['lines']:
   if not edges or not edges[0]<l['y']+4<edges[-1]:unowned.append(dict(page=page,line=l,reason='Outside printed cells'))
 result=dict(sha256=o['sha256'],engine='Poppler grayscale 144 dpi horizontal rules in remarks column',cells=cells,unowned=unowned,borders=borders)
 (out/'notes.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(dict(cells=len(cells),unowned=unowned),ensure_ascii=False))
 for c in cells:print(c['page'],c['paths'],c['text'].replace('\n',' | '))
 if unowned:raise SystemExit(1)
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 for k in ['pdf','origin','output']:p.add_argument('--'+k,type=Path,required=True)
 a=p.parse_args();observe(a.pdf,a.origin,a.output)
