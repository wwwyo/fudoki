"""Detect independent care-account rules from original images, without OCR."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
import numpy as np
from PIL import Image,ImageFilter

def clusters(indices,size):
 groups=[]
 for i in indices:
  if not groups or i-groups[-1][-1]>2:groups.append([])
  groups[-1].append(int(i))
 return [sum(g)/len(g)/size for g in groups]
def inspect(directory):
 result={}
 for page in (8,9,20,21,22,23,24,25,26,27,28,29):
  p=directory/f'page-{page}.png'; im=Image.open(p).convert('L');dark=np.asarray(im.filter(ImageFilter.MinFilter(7)))<190
  h,w=dark.shape
  top,bottom=(.168,.72) if page in (8,9) else ((.035,.89) if page in (22,23) else (.135,.89))
  score=dark[int(top*h):int(bottom*h),:].mean(axis=0);ids=np.flatnonzero(score>.70);ids=ids[(ids>.05*w)&(ids<.96*w)]
  result[str(page)]={'width':w,'height':h,'x_edges':clusters(ids,w),'image_path':str(p.resolve()),'image_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
  if page in (9,21,23,25,27,29):
   left,right=(.11,.89) if page==9 else (.11,.65)
   if page==9:top,bottom=.16,.75
   else:top,bottom=.20,.91
   score=dark[:,int(left*w):int(right*w)].mean(axis=1);ids=np.flatnonzero(score>.70);ids=ids[(ids>top*h)&(ids<bottom*h)]
   result[str(page)]['edges']=clusters(ids,h)
 return result

def main():
 ap=argparse.ArgumentParser(description=__doc__)
 for f in ('images','output'):ap.add_argument('--'+f,required=True,type=Path)
 a=ap.parse_args()
 if a.output.exists():raise FileExistsError(a.output)
 r=inspect(a.images);a.output.write_text(json.dumps(r,indent=2)+'\n');print({p:{'columns':len(v['x_edges'])-1,'rows':len(v.get('edges',[]))-1} for p,v in r.items()})
if __name__=='__main__':main()
