"""Independent printed controls and scope inventory; no builder imports."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
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



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Original PDF (read only)')
    parser.add_argument('--origin-sha256', required=True, help='Expected original SHA-256')
    parser.add_argument('--output', type=Path, required=True, help='New independent observation directory; must not exist')
    args = parser.parse_args()
    source_sha = identity(args.source, args.origin_sha256)
    fresh_output(args.output)
    for start, end, name in [(10, 11, 'totals'), (18, 19, 'summary'), (108, 449, 'detail')]:
        subprocess.run(['pdftotext', '-f', str(start), '-l', str(end),
                        '-bbox-layout', str(args.source), str(args.output / f'origin-{name}-bbox.xhtml')], check=True)
    controls = []
    kan = None
    for index, page in enumerate(ET.parse(args.output / 'origin-totals-bbox.xhtml').findall('.//{*}page')):
        lines = {}
        for word in page.findall('.//{*}word'):
            lines.setdefault(float(word.get('yMin')), []).append(word)
        for y, words in sorted(lines.items()):
            words.sort(key=lambda w: float(w.get('xMin')))
            amounts = [w for w in words if 275 <= float(w.get('xMin')) < 365
                       and re.fullmatch(r'[0-9,]+', w.text or '')]
            names = [w for w in words if float(w.get('xMin')) < 275]
            if not amounts or not names or not 98 <= y < 800:
                continue
            text = ''.join(w.text or '' for w in names)
            box = [min(float(w.get('xMin')) for w in words), y,
                   max(float(w.get('xMax')) for w in words), max(float(w.get('yMax')) for w in words)]
            match = re.fullmatch(r'(\d+)(.+)', text)
            if match:
                kind = 'kan' if float(names[0].get('xMin')) < 140 else 'kou'
                code, name = match.groups()
                if kind == 'kan':
                    kan = code
                row = {'kind': kind, 'kan': kan, 'code': code, 'name': name}
            elif text == '歳出合計':
                row = {'kind': 'account', 'name': text}
            else:
                raise ValueError((text, y))
            controls.append({**row, 'printed': amounts[0].text, 'page': 10 + index, 'bbox': box})
    inventory = []
    for index, page in enumerate(ET.parse(args.output / 'origin-detail-bbox.xhtml').findall('.//{*}page')):
        words = page.findall('.//{*}word')
        footer = ''.join(w.text or '' for w in sorted(
            [w for w in words if float(w.get('yMin')) > 790], key=lambda w: float(w.get('xMin'))))
        inventory.append({'page': 108 + index, 'word_count': len(words), 'footer': footer,
                          'body_word_count': sum(108 <= float(w.get('yMin')) < 756.77 for w in words)})
    assert len(inventory) == 342
    integer = lambda s: int(s.replace(',', ''))
    for parent in [r for r in controls if r['kind'] == 'kan']:
        total = sum(integer(r['printed']) for r in controls if r['kind'] == 'kou' and r['kan'] == parent['kan'])
        assert total == integer(parent['printed']), (parent, total)
    assert sum(integer(r['printed']) for r in controls if r['kind'] == 'kan') == integer(
        next(r['printed'] for r in controls if r['kind'] == 'account'))
    result = {'origin_sha256': source_sha,
              'bbox_sha256': {name: hashlib.sha256((args.output / f'origin-{name}-bbox.xhtml').read_bytes()).hexdigest() for name in ('totals', 'summary', 'detail')},
              'unit': '千円', 'controls': controls, 'page_inventory': inventory}
    (args.output / 'independent-origin-controls.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    from collections import Counter
    print(json.dumps({'status': 'passed', 'output': str(args.output), 'origin_sha256': source_sha, 'controls': dict(Counter(r['kind'] for r in controls)), 'pages': len(inventory),
                      'words': sum(r['word_count'] for r in inventory), 'source_control_matches': 14}, ensure_ascii=False))


if __name__ == '__main__':
    raise SystemExit(run_cli())
