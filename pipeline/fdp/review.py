"""配布物の版間で金額・識別子・分類・出典の変化を報告する。"""
import argparse
import csv
import hashlib
import json
import re
from pathlib import Path


def read_release(directory: Path):
    manifest = json.loads((directory / 'manifest.json').read_text())
    files = {}
    for entry in manifest['files']:
        path = entry['path']
        if not re.fullmatch(r'fiscal/\d{6}/[a-z_]+\.(?:csv|json)', path):
            raise ValueError('Invalid distribution path')
        body = (directory / path).read_bytes()
        if len(body) != entry['bytes'] or hashlib.sha256(body).hexdigest() != entry['sha256']:
            raise ValueError(f'Distribution hash or size differs: {path}')
        if path in files:
            raise ValueError('Duplicate distribution path')
        files[path] = body
    scopes, resources, descriptors = {}, {}, {}
    for path, body in files.items():
        if not path.endswith('/datapackage.json'):
            continue
        code = path.split('/')[1]
        descriptor = json.loads(body)
        descriptors[code] = {key: descriptor.get(key) for key in ('sources', 'licenses')}
        for resource in descriptor['resources']:
            resource_path = f'fiscal/{code}/{resource["path"]}'
            if resource_path not in files:
                raise ValueError('Descriptor refers to an unlisted file')
            constants = {field['name']: field['constant'] for field in resource['schema'].get('extraFields', [])}
            reader = csv.DictReader(files[resource_path].decode().splitlines(keepends=True))
            if set(constants) & set(reader.fieldnames or []):
                raise ValueError('Descriptor constants collide with CSV fields')
            rows = [dict(constants, **row) for row in reader]
            keys = resource['schema']['primaryKey']
            if isinstance(keys, str):
                keys = [keys]
            indexed = {}
            for row in rows:
                key = tuple(str(row[column]) for column in keys)
                if key in indexed:
                    raise ValueError(f'Duplicate distribution identity: {resource_path}')
                indexed[key] = row
            resources[resource_path] = indexed
        classifications = {row['fiscal_line_id']: row for row in resources.get(f'fiscal/{code}/cofog.csv', {}).values()}
        for direction in ('expenditure', 'revenue'):
            for row in resources.get(f'fiscal/{code}/{direction}.csv', {}).values():
                scope = (code, str(row['fiscal_year']), direction, row['document_kind'], row['phase_id'])
                group = scopes.setdefault(scope, {})
                line_id = row['fiscal_line_id']
                if line_id in group:
                    raise ValueError('Duplicate line and phase in distribution')
                group[line_id] = {'amount': int(row['value']), 'classification': classifications.get(line_id)}
    return {'manifest': manifest, 'scopes': scopes, 'resources': resources, 'descriptors': descriptors}


def changed_records(before, after):
    return [{'key': list(key) if isinstance(key, tuple) else key, 'before': before.get(key), 'after': after.get(key)}
            for key in sorted(before.keys() | after.keys()) if before.get(key) != after.get(key)]


def compare(before, after):
    groups = []
    for scope in sorted(before['scopes'].keys() | after['scopes'].keys()):
        old, new = before['scopes'].get(scope, {}), after['scopes'].get(scope, {})
        added, removed, common = new.keys() - old.keys(), old.keys() - new.keys(), old.keys() & new.keys()
        classifications = sorted(key for key in common if old[key]['classification'] != new[key]['classification'])
        amounts = sorted(key for key in common if old[key]['amount'] != new[key]['amount'])
        old_amount, new_amount = sum(row['amount'] for row in old.values()), sum(row['amount'] for row in new.values())
        groups.append({
            'jurisdictionCode': scope[0], 'fiscalYear': int(scope[1]), 'direction': scope[2], 'documentKind': scope[3], 'phase': scope[4],
            'before': {'rows': len(old), 'amount': old_amount}, 'after': {'rows': len(new), 'amount': new_amount},
            'delta': {'rows': len(new) - len(old), 'amount': new_amount - old_amount},
            'identifiers': {'added': sorted(added), 'removed': sorted(removed)},
            'amountChanges': [{'fiscalLineId': key, 'before': old[key]['amount'], 'after': new[key]['amount']} for key in amounts],
            'classificationChanges': {
                'rows': len(classifications), 'beforeAmount': sum(old[key]['amount'] for key in classifications),
                'afterAmount': sum(new[key]['amount'] for key in classifications),
                'lines': [{'fiscalLineId': key, 'before': old[key]['classification'], 'after': new[key]['classification']} for key in classifications],
            },
        })
    def caveats(release):
        return {row['jurisdiction_code']: row.get('caveats', []) for row in release['manifest']['jurisdictions']}
    def sources(release):
        result = {}
        for row in release['manifest']['datasets']:
            scope = (row['jurisdiction_code'], str(row['fiscal_year']), row['direction'], row['document_kind'])
            result.setdefault(scope, []).append({key: row[key] for key in ('dataset_id', 'origin_sha256', 'source')})
        return {key: sorted(rows, key=lambda row: row['dataset_id']) for key, rows in result.items()}
    resource_changes = []
    for path in sorted(before['resources'].keys() | after['resources'].keys()):
        if path.endswith(('/expenditure.csv', '/revenue.csv', '/cofog.csv')):
            continue
        changes = changed_records(before['resources'].get(path, {}), after['resources'].get(path, {}))
        if changes:
            resource_changes.append({'path': path, 'rows': changes})
    return {
        'baselineReleaseId': before['manifest']['buildId'], 'releaseId': after['manifest']['buildId'],
        'amountUnit': 'JPY', 'scopes': groups,
        'caveatChanges': changed_records(caveats(before), caveats(after)),
        'sourceChanges': changed_records(sources(before), sources(after)),
        'licenseAndSourceChanges': changed_records(before['descriptors'], after['descriptors']), 'resourceChanges': resource_changes,
    }


def markdown(review):
    comparison = review['comparison'] or review['initialContents']
    heading = '公開前の初回構築。比較対象の公開版はありません。全件を新規追加として記録します。' if review['comparison'] is None else f"比較: {comparison['baselineReleaseId']} → {comparison['releaseId']}。"
    lines = [heading + ' 金額は円。各文書・段階を別々に表示し、合算しません。', '',
             '| 団体 / 年度 / 歳入歳出 / 文書 / 段階 | 行数差 | 金額差 | ID 追加 / 削除 | 金額変更行 | 分類変更行 | 分類変更行の旧 / 新金額 |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for row in comparison['scopes']:
        scope = ' / '.join(str(row[key]) for key in ('jurisdictionCode', 'fiscalYear', 'direction', 'documentKind', 'phase'))
        ids, classification = row['identifiers'], row['classificationChanges']
        lines.append(f"| {scope} | {row['delta']['rows']:+,} | {row['delta']['amount']:+,} | {len(ids['added']):,} / {len(ids['removed']):,} | {len(row['amountChanges']):,} | {classification['rows']:,} | {classification['beforeAmount']:,} / {classification['afterAmount']:,} |")
    lines.extend(['', f"注意点: {len(comparison['caveatChanges'])}団体、原典・出典: {len(comparison['sourceChanges'])}範囲、利用条件・出典宣言: {len(comparison['licenseAndSourceChanges'])}団体、名称・規則等: {len(comparison['resourceChanges'])}リソースの変更。個別 ID と変更前後の内容は review-summary.json を参照。", ''])
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    baseline_options = parser.add_mutually_exclusive_group(required=True)
    baseline_options.add_argument('--baseline', type=Path)
    baseline_options.add_argument('--initial-publication', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    current = read_release(args.candidate)
    comparison = compare(read_release(args.baseline), current) if args.baseline else None
    baseline = {'kind': 'release', 'releaseId': comparison['baselineReleaseId']} if comparison else {'kind': 'initial-publication'}
    manifest = current['manifest']
    review = {key: manifest[key] for key in ('inputFingerprint', 'codeRevision', 'files')}
    review['releaseId'] = manifest['buildId']
    review.update({'baseline': baseline, 'comparison': comparison})
    if comparison is None:
        empty = {'manifest': {'buildId': None, 'jurisdictions': [], 'datasets': []}, 'scopes': {}, 'resources': {}, 'descriptors': {}}
        review['initialContents'] = compare(empty, current)
    args.output.write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n')
    args.output.with_suffix('.md').write_text(markdown(review))
    print(json.dumps({'path': str(args.output), 'releaseId': manifest['buildId'], 'baseline': baseline}))


if __name__ == '__main__':
    main()
