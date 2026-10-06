"""Cache-only immutable provider proposed for reviewed native scan observations."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil


class FrozenNativeProvider:
    def __init__(self, manifest_path: Path, cache_dir: Path):
        self.manifest_path = manifest_path
        self.manifest = json.loads(manifest_path.read_text())
        self.cache_dir = cache_dir
        self.assets = {x['logical_path']: x for x in self.manifest['assets']}
        if len(self.assets) != len(self.manifest['assets']):
            raise ValueError('Duplicate logical proof path')
        self.verified = []

    def path(self, logical_path: str) -> Path:
        item = self.assets[logical_path]
        path = self.cache_dir / item['object_key']
        if not path.is_file():
            raise FileNotFoundError(f"Immutable object unavailable: {item['object_key']}")
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if digest != item['sha256'] or len(body) != item['bytes']:
            raise ValueError(f'Immutable SHA/byte mismatch: {logical_path}')
        return path

    def verify_all(self) -> list[dict]:
        self.verified = []
        for logical_path, item in self.assets.items():
            self.path(logical_path)
            self.verified.append({k: item[k] for k in ('logical_path', 'kind', 'sha256', 'bytes', 'object_key')})
        return self.verified

    def hydrate(self, destination: Path) -> None:
        # The logical tree is ephemeral. Only the verified immutable objects and
        # Git-declared manifest/transcription are required after adoption.
        for logical_path in self.assets:
            if logical_path.startswith('accepted-readback/'):
                continue  # Comparison evidence never supplies reconstructed rows.
            relative = Path(logical_path)
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError(f'Unsafe logical path: {logical_path}')
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.path(logical_path), target)

    def json(self, logical_path: str):
        return json.loads(self.path(logical_path).read_text())

    def validate_source_ledgers(self, transcription: dict) -> dict:
        pages = {}
        for logical in self.assets:
            if logical.startswith('pages/') and logical.endswith('.json'):
                page = self.json(logical)
                key = page['expected_printed_page']
                if key in pages:
                    raise ValueError(f'Duplicate printed page observation: {key}')
                pages[key] = page
        original_specs = {x['sha256']: x for x in self.manifest['originals']}
        if set(pages) != set(range(1, 231)):
            raise ValueError('Incomplete 230-page observations')
        for number, page in pages.items():
            spec = original_specs[page['origin_sha256']]
            if not (1 <= page['physical_page'] <= spec['pages']):
                raise ValueError('Physical page outside fixed original')
            if number != spec['first_printed_page'] + page['physical_page'] - 1:
                raise ValueError('Physical/printed page mismatch')
            self.path('originals/' + spec['sha256'] + '.pdf')
        counts = {}
        cells = []
        for kind in ['monetary_cells', 'legal_labels', 'hierarchy_labels', 'running_headers']:
            rows = self.json(transcription[kind])
            identities = set()
            for row in rows:
                number = row['printed_page']
                page = pages[number]
                source_id = row.get('observed_id')
                if source_id:
                    sha, physical, *_ = source_id.split(':')
                    anchor_page = pages[number - 1] if kind == 'monetary_cells' and row['table'] == 'hierarchy-controls' and row['field'] in ['executed', 'carryover', 'unused'] else page
                    if sha != anchor_page['origin_sha256'] or int(physical[1:]) != anchor_page['physical_page']:
                        raise ValueError('Visual reading points at a different original/page')
                else:
                    if row['origin_sha256'] != page['origin_sha256'] or row['physical_page'] != page['physical_page']:
                        raise ValueError('Running-header original/page mismatch')
                identity = (source_id or str(number), row.get('field') or row.get('level') or kind)
                if identity in identities:
                    raise ValueError(f'Duplicate correction declaration: {identity}')
                identities.add(identity)
                box = row.get('bbox') or row['raw_observation']['bbox_normalized_top_left']
                if not (len(box) == 4 and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
                    raise ValueError(f'Invalid original cell box: {identity}')
                review = row['review_render']
                self.path(review)
                cells.append({'ledger': kind, 'source_id': source_id, 'field': row.get('field'),
                    'level': row.get('level') or row.get('control_level'),
                    'origin_sha256': page['origin_sha256'], 'origin_url': page['origin_url'],
                    'physical_page': page['physical_page'], 'printed_page': number,
                    'bbox_normalized_top_left': box,
                    'page_observation_sha256': self.assets[next(k for k in self.assets if k.startswith('pages/') and k.endswith(f'printed{number:03}.json'))]['sha256'],
                    'review_render_sha256': self.assets[review]['sha256'],
                    'ledger_sha256': self.assets[transcription[kind]]['sha256']})
            counts[kind] = len(rows)
        summaries = []
        for row in transcription['summary_rows']:
            for key, prefix in [('control_left_observations_json', ''), ('control_right_observations_json', 'right_')]:
                observation = json.loads(row[key])
                page = pages[observation['printed_page']]
                if (observation['origin_sha256'] != page['origin_sha256'] or
                        observation['physical_page'] != page['physical_page'] or
                        row[prefix + 'origin_sha256'] != page['origin_sha256'] or
                        row[prefix + 'physical_page'] != page['physical_page']):
                    raise ValueError('Independent summary points at a different source page')
                box = observation['bbox']
                if not (len(box) == 4 and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
                    raise ValueError('Independent summary has invalid printed row box')
                summaries.append({'summary_id': row['observed_id'], 'origin_sha256': page['origin_sha256'],
                    'physical_page': page['physical_page'], 'printed_page': observation['printed_page'],
                    'bbox_normalized_top_left': box, 'review_render_sha256': self.assets['summary-review.png']['sha256']})
        if len(summaries) != 8:
            raise ValueError('Independent four-summary source proof is incomplete')
        self.path('summary-review.png')
        return {'pages': len(pages), 'ledger_counts': counts, 'correction_cells': cells,
            'summary_source_positions': summaries}
