"""Observe printed moku/setsu controls directly, independent of the builder."""
from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def identity(source, expected):
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("--origin-sha256 must be 64 lowercase hexadecimal characters")
    actual = hashlib.sha256(source.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"Original identity mismatch: expected {expected}, got {actual}")
    return actual


def fresh_output(output):
    # Never reuse a directory containing a previous passed result.
    output.mkdir(parents=True, exist_ok=False)


def run_cli():
    try:
        return main()
    except Exception as error:
        print(json.dumps({"status": "failed", "error": str(error) or type(error).__name__}, ensure_ascii=False))
        return 2


DIGITS = str.maketrans('０１２３４５６７８９', '0123456789')


def words_by_line(page):
    lines = {}
    for word in page.findall('.//{*}word'):
        y = round(float(word.get('yMin')), 2)
        lines.setdefault(y, []).append(word)
    return [(y, sorted(words, key=lambda w: float(w.get('xMin')))) for y, words in sorted(lines.items())]


def value(words):
    return ''.join(w.text or '' for w in words)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Original PDF (read only)')
    parser.add_argument('--origin-sha256', required=True, help='Expected original SHA-256')
    parser.add_argument('--origin-observations', type=Path, required=True, help='inspect_origin.py output directory')
    parser.add_argument('--output', type=Path, required=True, help='New detail control directory; must not exist')
    args = parser.parse_args()
    source_sha = identity(args.source, args.origin_sha256)
    controls = json.loads((args.origin_observations / 'independent-origin-controls.json').read_text())
    bbox = args.origin_observations / 'origin-detail-bbox.xhtml'
    bbox_sha = hashlib.sha256(bbox.read_bytes()).hexdigest()
    if controls['origin_sha256'] != source_sha or controls['bbox_sha256']['detail'] != bbox_sha:
        raise ValueError('Independent original observation identity mismatch')
    fresh_output(args.output)
    pages = ET.parse(bbox).findall('.//{*}page')
    moku, setsu, holds, spans = [], [], [], []
    kan = kou = active = None
    for offset in range(0, len(pages), 2):
        physical = 108 + offset
        events = []
        for y, words in words_by_line(pages[offset]):
            heading = value([w for w in words if float(w.get('xMin')) < 260])
            match = re.fullmatch(r'第([０-９0-9]+)(款|項)(.+)', heading)
            if match:
                code, kind, name = match.groups()
                if kind == '款':
                    kan = code.translate(DIGITS)
                else:
                    kou = code.translate(DIGITS)
                continue
            if not 108 <= y < 756.77:
                continue
            codes = [w for w in words if 56 <= float(w.get('xMin')) < 72
                     and re.fullmatch(r'\d+', w.text or '')]
            names = [w for w in words if 72 <= float(w.get('xMin')) < 125]
            printed = value([w for w in words if 125 <= float(w.get('xMin')) < 184])
            if not names or (not codes and (not printed or value(names) == '計')):
                continue
            key = [kan, kou, codes[0].text if codes else value(names)]
            if printed:
                assert re.fullmatch(r'\d[\d,]*', printed), (physical, y, printed)
                assert not any(r['key'] == key for r in moku), ('Repeated new moku', key)
                active = key
                moku.append({'key': key, 'code': codes[0].text if codes else None,
                             'name_first_line': value(names), 'printed': printed,
                             'page': physical, 'y': y,
                             'amount_box': [[float(w.get(k)) for k in ('xMin','yMin','xMax','yMax')]
                                            for w in words if 125 <= float(w.get('xMin')) < 184]})
            else:
                assert key == active, ('Continuation context differs', physical, y, key, active)
            events.append((y, key))
        assert events, ('No moku on left page', physical)
        for index, (top, key) in enumerate(events):
            spans.append({'page': physical + 1, 'top': top - .8,
                          'bottom': events[index+1][0] - .8 if index+1 < len(events) else 756.77,
                          'key': key})
        for y, words in words_by_line(pages[offset+1]):
            if not 108 <= y < 756.77:
                continue
            amounts = [w for w in words if 132 <= float(w.get('xMin')) < 195
                       and re.fullmatch(r'\d[\d,]*', w.text or '')]
            if not amounts:
                continue
            codes = [w for w in words if 56 <= float(w.get('xMin')) < 72
                     and re.fullmatch(r'\d+', w.text or '')]
            names = [w for w in words if 72 <= float(w.get('xMin')) < 132]
            if len(codes) != 1:
                holds.append({'reason': 'Statutory amount without same-line code; inspect source',
                              'page': physical+1, 'y': y, 'printed': value(amounts)})
                continue
            contexts = [s for s in spans if s['page']==physical+1 and s['top']<=y<s['bottom']]
            assert len(contexts)==1, (physical+1,y,contexts)
            setsu.append({'key': contexts[0]['key'], 'code': codes[0].text,
                          'name_first_line': value(names), 'printed': value(amounts),
                          'page': physical+1, 'y': y,
                          'amount_box': [[float(w.get(k)) for k in ('xMin','yMin','xMax','yMax')] for w in amounts]})
    result = {'origin_sha256': source_sha, 'detail_bbox_sha256': bbox_sha, 'moku': moku, 'setsu': setsu, 'source_spans': spans, 'holds': holds}
    (args.output / 'independent-detail-controls.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'status':'failed' if holds else 'passed','origin_sha256':source_sha,'output':str(args.output),'moku':len(moku),'setsu':len(setsu),'spans':len(spans),'holds':len(holds),
                      'moku_by_kan':dict(Counter(r['key'][0] for r in moku))},ensure_ascii=False))

    return 1 if holds else 0


if __name__=='__main__':
    raise SystemExit(run_cli())
