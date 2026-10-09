"""Observe the source independently through Poppler's fixed-pitch line layout."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

SHA = 'f519167e438c0ee25e1cfcae0d3c940e748002a02929c893cb727cb3fa8594fb'
NUMBER = re.compile(r'△?\d[\d,]*')
DETAIL_FIELDS = ['initial','amendment','prior','transfer','total','executed','carry_continuing','carry_authorized','carry_accident','unused']
LEAF_FIELDS = ['total','executed','carry_continuing','carry_authorized','carry_accident','unused']
SUMMARY_FIELDS = ['total','executed','carry','unused','comparison']

def observe(pdf: Path, destination: Path, summary_pages=(8, 10), detail_pages=(42, 91)) -> dict:
    if hashlib.sha256(pdf.read_bytes()).hexdigest() != SHA:
        raise ValueError('Original SHA differs')
    destination.mkdir(parents=True, exist_ok=False)
    nodes, totals = [], []
    path = []
    for start, end, kind in [(*summary_pages,'summary'),(*detail_pages,'detail')]:
        text = subprocess.check_output(['pdftotext','-f',str(start),'-l',str(end),'-fixed','4.5',str(pdf),'-']).decode()
        (destination / f'{kind}-fixed.txt').write_text(text)
        path = []
        for page, content in enumerate(text.split('\f')[:-1], start):
            lines = content.splitlines()
            current = []
            for line_number, line in enumerate(lines):
                m = re.match(r'(\s*)(\d{1,2})(\D.*)',line)
                if not m:
                    if re.search(r'歳\s*出\s*合\s*計',line):
                        amounts=NUMBER.findall(line)
                        expected=DETAIL_FIELDS if kind=='detail' else SUMMARY_FIELDS
                        if len(amounts)!=len(expected): raise ValueError(('Total columns',page,line))
                        totals.append(dict(kind=kind,page=page,amounts=dict(zip(expected,amounts))))
                    continue
                amounts = list(NUMBER.finditer(m[3]))
                width = 10 if kind=='detail' and len(m[1])<40 else 6 if kind=='detail' else 5
                if len(amounts)<width: continue
                level = {5:0,7:1,9:2}.get(len(m[1]),3) if kind=='detail' else (0 if len(m[1])<30 else 1)
                if level==3 and len(m[1])<80: raise ValueError(('Unexpected indentation',page,line))
                fields=DETAIL_FIELDS if kind=='detail' and level<3 else LEAF_FIELDS if kind=='detail' else SUMMARY_FIELDS
                # The source's only touching numeric cells are the prior zero and signed reserve transfer.
                values=[x.group() for x in amounts[:width]]
                name=m[3][:amounts[0].start()].strip()
                node=dict(kind=kind,page=page,line=line_number,level=level,number=m[2],name=name,amounts=dict(zip(fields,values)),name_parts=[(line_number,name)] if name else [])
                nodes.append(node); current.append(node)
            # Folded labels sit above or below the amount baseline; assign by closest baseline within their original column.
            for line_number,line in enumerate(lines):
                if kind=='detail' and '円' in line[:97] and line[97:113].strip() and '円' not in line[97:113]:
                    line=' '*99+line[97:113].strip()
                segment=re.split(r'\s{2,}',line.strip())[0]
                # Printed financial baselines start with an ASCII number. Names
                # such as 第１号被保険 contain digits but are folded label text.
                if not segment or re.match(r'△?[0-9]',segment) or '円' in segment or '－' in segment: continue
                indent=len(line)-len(line.lstrip())
                if kind=='detail' and 95<=indent<=103:
                    candidates=[n for n in current if n['level']==3]
                elif kind=='detail' and 5<=indent<=15:
                    candidates=[n for n in current if n['level']<3]
                else: continue
                if candidates:
                    node=min(candidates,key=lambda n:abs(n['line']-line_number))
                    if abs(node['line']-line_number)<=2:
                        node['name_parts'].append((line_number,segment))
            for node in current:
                node['name']='\n'.join(v for _,v in sorted(node.pop('name_parts')))
                level=node['level']
                if level<len(path): path=path[:level]
                if level!=len(path): raise ValueError(('Missing hierarchy context',page,node))
                path.append(node['number'])
                node['path']=path.copy()
                if level==3: path=path[:3]
    result=dict(sha256=SHA,source=str(pdf.resolve()),ranges=[list(summary_pages),list(detail_pages)],engine='pdftotext -fixed 4.5',nodes=nodes,totals=totals)
    (destination/'origin.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pdf',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--summary-pages',type=int,nargs=2,default=(8,10));p.add_argument('--detail-pages',type=int,nargs=2,default=(42,91))
    a=p.parse_args();r=observe(a.pdf,a.output,a.summary_pages,a.detail_pages)
    from collections import Counter
    print(json.dumps({'nodes':len(r['nodes']),'levels':dict(Counter(f"{n['kind']}:{n['level']}" for n in r['nodes'])),'totals':len(r['totals'])}))
