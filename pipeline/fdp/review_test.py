"""相殺される金額変更、版による ID 交代、出典と分類の変化を報告する。"""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from fdp.review import compare, read_release


class ReleaseReview(unittest.TestCase):
    def snapshot(self):
        return {
            'manifest': {
                'buildId': 'previous',
                'jurisdictions': [{'jurisdictionCode': '000001', 'caveats': ['Before']}],
                'datasets': [{'dataset_id': 'edition-1', 'jurisdiction_code': '000001', 'fiscal_year': 2026,
                              'direction': 'expenditure', 'document_kind': 'settlement', 'origin_sha256': 'old', 'source_json': '{"url":"original"}'}],
            },
            'scopes': {('000001', '2026', 'expenditure', 'settlement', 'executed'): {
                'a': {'amount': 1000, 'classification': {'cofog_class': '01.1.1'}},
                'b': {'amount': 2000, 'classification': None},
            }},
            'resources': {'fiscal/000001/cofog_rules.csv': {('rule',): {'label': 'before'}}},
            'descriptors': {'000001': {'licenses': None, 'sources': ['original']}},
        }

    def test_offsetting_amounts_and_classification_changes_survive_equal_total(self):
        old = self.snapshot()
        new = copy.deepcopy(old)
        rows = next(iter(new['scopes'].values()))
        rows['a']['amount'] = 1100
        rows['b']['amount'] = 1900
        rows['a']['classification'] = {'cofog_class': '02.1.1'}
        new['manifest']['jurisdictions'][0]['caveats'] = ['After']
        new['manifest']['datasets'][0]['source_json'] = '{"url":"corrected"}'
        new['descriptors']['000001']['licenses'] = ['CC0']
        new['resources']['fiscal/000001/cofog_rules.csv'][('rule',)]['label'] = 'after'
        actual = compare(old, new)
        scope = actual['scopes'][0]
        self.assertEqual(scope['delta'], {'rows': 0, 'amount': 0})
        self.assertEqual(scope['amountChanges'], [
            {'fiscalLineId': 'a', 'before': 1000, 'after': 1100},
            {'fiscalLineId': 'b', 'before': 2000, 'after': 1900}])
        self.assertEqual(scope['classificationChanges']['rows'], 1)
        self.assertEqual(scope['classificationChanges']['beforeAmount'], 1000)
        self.assertEqual(scope['classificationChanges']['afterAmount'], 1100)
        for key in ('caveatChanges', 'sourceChanges', 'licenseAndSourceChanges', 'resourceChanges'):
            self.assertEqual(len(actual[key]), 1)

    def test_new_document_edition_reports_replaced_ids_without_assuming_line_correspondence(self):
        old = self.snapshot()
        new = copy.deepcopy(old)
        scope = next(iter(new['scopes']))
        new['scopes'][scope] = {'c': {'amount': 3000, 'classification': None}}
        new['scopes'][('000001', '2026', 'expenditure', 'budget', 'approved')] = {'budget-c': {'amount': 3000, 'classification': None}}
        actual = compare(old, new)
        settlement = next(row for row in actual['scopes'] if row['documentKind'] == 'settlement')
        self.assertEqual(settlement['identifiers'], {'added': ['c'], 'removed': ['a', 'b']})
        self.assertEqual(settlement['classificationChanges']['rows'], 0)
        self.assertEqual(len(actual['scopes']), 2)

    def test_descriptor_constants_and_multiline_csv_preserve_scope_and_reject_corruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = {
                'fiscal/000001/datapackage.json': json.dumps({'resources': [{
                    'path': 'settlement_expenditure.csv', 'schema': {'primaryKey': ['fiscal_line_id'], 'extraFields': [
                        {'name': 'document_kind', 'constant': 'settlement'}, {'name': 'direction', 'constant': 'expenditure'}]}}]}).encode(),
                'fiscal/000001/settlement_expenditure.csv': b'fiscal_line_id,fiscal_year,amount,label\na,2026,123,"line one\nline two"\n',
            }
            manifest = {'buildId': 'candidate', 'jurisdictions': [], 'datasets': [], 'files': []}
            for path, body in files.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
                manifest['files'].append({'path': path, 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()})
            (root / 'manifest.json').write_text(json.dumps(manifest))
            release = read_release(root)
            self.assertEqual(release['scopes'][('000001', '2026', 'expenditure', 'settlement', 'settlement_expenditure')]['a']['amount'], 123)
            row = release['resources']['fiscal/000001/settlement_expenditure.csv'][('a',)]
            self.assertEqual(row['label'], 'line one\nline two')
            (root / 'fiscal/000001/settlement_expenditure.csv').write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'hash or size'):
                read_release(root)


if __name__ == '__main__':
    unittest.main()
