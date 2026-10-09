"""Observe remarks membership from rendered cell borders, independently of amount baselines."""
import argparse
import bisect
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as E

NS='{http://www.w3.org/1999/xhtml}'
def grouped(words):
    groups=[]
    for w in sorted(words,key=lambda x:(float(x.attrib['yMin']),float(x.attrib['xMin']))):
        y=float(w.attrib['yMin'])
        if not groups or abs(y-groups[-1][0])>1:groups.append((y,[]))
        groups[-1][1].append(w)
    return [(y,''.join(w.text or '' for w in sorted(ws,key=lambda w:float(w.attrib['xMin'])))) for y,ws in groups]

def observe(pdf,origin,out):
    source=json.loads(origin.read_text())
    if hashlib.sha256(pdf.read_bytes()).hexdigest()!=source['sha256']:raise ValueError('PDF SHA differs')
    out.mkdir(parents=True,exist_ok=False);remarks=[];borders=[]
    first,last=source['ranges'][1]
    for page in range(first,last+1):
        raw=subprocess.check_output(['pdftotext','-f',str(page),'-l',str(page),'-bbox-layout',str(pdf),'-'])
        words=list(E.fromstring(raw).iter(NS+'word'))
        finance=grouped([w for w in words if 630<float(w.attrib['xMin'])<700 and re.fullmatch(r'[\d,]+',w.text or '')])
        nodes=[n for n in source['nodes'] if n['kind']=='detail' and n['page']==page]
        nodes += [dict(t,path=[]) for t in source['totals'] if t['kind']=='detail' and t['page']==page]
        if len(finance)!=len(nodes) or any(text!=n['amounts']['executed'] for (_,text),n in zip(finance,nodes)):raise ValueError(('Independent finance anchors differ',page,finance,len(nodes)))
        # Full-width black strokes in the empty parts of the remarks column are printed cell borders.
        pgm=subprocess.check_output(['pdftoppm','-gray','-r','144','-f',str(page),'-l',str(page),'-singlefile',str(pdf)])
        m=re.match(rb'P5\s+(\d+)\s+(\d+)\s+255\s',pgm);width,height=map(int,m.groups());pixels=pgm[m.end():]
        hits=[]
        for y in range(height):
            line=pixels[y*width+1940:y*width+2290]
            if sum(v<160 for v in line)>=len(line)*.88:hits.append(y/2)
        runs=[]
        for y in hits:
            if not runs or y-runs[-1][-1]>1:runs.append([y])
            else:runs[-1].append(y)
        edges=[sum(r)/len(r) for r in runs];borders.append(dict(page=page,edges=edges))
        cells={}
        for (y,_),node in zip(finance,nodes):
            cell=bisect.bisect_right(edges,y)-1
            cells.setdefault(cell,[]).append(node)
        note_words=[w for w in words if float(w.attrib['xMin'])>=953]
        for cell,owners in cells.items():
            if cell<0 or cell+1>=len(edges):raise ValueError(('Missing cell edges',page,cell))
            selected=[w for w in note_words if edges[cell]<float(w.attrib['yMin'])<edges[cell+1]]
            lines=grouped(selected)
            if lines:
                # In the last reserve cell the note spans beside the printed grand total. The cell starts at the reserve's own row.
                remarks.append(dict(page=page,path=owners[0]['path'],text='\n'.join(text for _,text in lines),cell=[edges[cell],edges[cell+1]],financial_rows=len(owners)))
    result=dict(sha256=source['sha256'],engine='pdftoppm 144 dpi grayscale printed borders + independent source-path order + pdftotext remarks words',remarks=remarks,borders=borders)
    (out/'remarks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'remarks':len(remarks),'pages':len(borders),'multi_row_cells':[r for r in remarks if r['financial_rows']>1]},ensure_ascii=False))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['pdf','origin','output']:p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();observe(a.pdf,a.origin,a.output)
