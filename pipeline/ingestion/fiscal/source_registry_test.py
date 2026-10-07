"""Public source-registry CLI contracts with small synthetic declarations."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PIPELINE = Path(__file__).resolve().parents[2]


def source(identifier='synthetic', form='csv', status='csv_inspected'):
    """A schema-shaped observation; no original or warehouse is required."""
    included = {'status': 'included', 'basis': 'synthetic observed scope', 'evidence_urls': []}
    return {
        'id': identifier, 'jurisdiction': '132047', 'fiscal_year': 2026,
        'document_phase': 'initial', 'directions': ['expenditure'],
        'account_labels': ['一般会計'], 'account_scope_status': 'content_inspected',
        'document_title': 'Synthetic initial budget', 'amendment_numbers': [],
        'edition_status': 'content_inspected',
        'editions': [{'fiscal_year': 2026, 'account_label': '一般会計',
                      'document_phase': 'initial', 'amendment_number': None,
                      'basis': 'synthetic observed edition', 'page': 1,
                      'in_scope': copy.deepcopy(included)}],
        'role': 'statement', 'format': form,
        'landing_url': 'https://example.test/budget',
        'download_url': f'https://example.test/{identifier}.{form}',
        'inspected_at': '2026-10-06',
        'listing_evidence': {'label': identifier, 'heading': '予算書',
                             'primary_fiscal_page': True},
        'content_inspection': {'status': status, 'evidence': [
            {'page': 1, 'kind': 'direction', 'text': '歳出'},
            {'page': 1, 'kind': 'grain', 'text': '目'}]},
        'content_grain': {'status': 'observed', 'observed_levels': ['moku'],
                          'project_setsu_relation': 'unconfirmed',
                          'note': 'Synthetic moku observation', 'relation_evidence': []},
        'fixed_inputs': [], 'marts': {'status': 'not_checked', 'evidence': []},
        'unresolved': [], 'in_scope': included,
    }


def inventory(*records):
    return {
        '$schema': 'https://fudoki.local/schemas/fiscal-sources-v1.json',
        'schema_version': 1, 'inspected_at': '2026-10-06',
        'method': 'fixed synthetic CLI regression fixture',
        'jurisdictions': [{'code': '132047', 'name': '三鷹市',
                           'search_boundaries': [], 'gaps': []}],
        'sources': list(records),
        'lock_reconciliation': {'lock_sha256': '0' * 64, 'entry_count': 0,
                                'matched_paths': [], 'unmatched_paths': []},
    }


def declaration(key='synthetic', *, section='csv', enabled=True, order=0):
    return {'section': section, 'key': key, 'enabled': enabled, 'order': order,
            'profile': {'edition_index': 0, 'direction': 'expenditure'},
            'options': {'resource': {'direction': 'expenditure', 'resource_name': key}}
            if section == 'csv' else {}}


class SourceRegistryCliTest(unittest.TestCase):
    def run_cli(self, document):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'inventory.json'
            path.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
            return subprocess.run(
                [sys.executable, '-m', 'ingestion.fiscal.source_registry',
                 '--inventory', str(path), '--json'],
                cwd=PIPELINE, capture_output=True, text=True, timeout=15,
            )

    def assert_rejected(self, document, message):
        result = self.run_cli(document)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertIn(message, result.stderr)

    def test_explicit_enabled_declarations_only_and_ordered_plan(self):
        registered = source()
        registered['ingestions'] = [declaration('late', order=9),
                                     declaration('early', order=1),
                                     declaration('disabled', enabled=False)]
        discovered = source('discovered-without-registration')
        result = self.run_cli(inventory(registered, discovered))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual([task['key'] for task in report['tasks']], ['early', 'late'])
        self.assertEqual(set(report['projected_sources']), {'catalog', 'early', 'late'})
        for task in report['tasks']:
            self.assertEqual(task['download_url'], registered['download_url'])
            self.assertEqual(task['scope']['account_label'], '一般会計')
        self.assertTrue(report['plan_only'])
        self.assertEqual(report['network_requests'], 0)
        self.assertEqual(report['extraction_runs'], 0)
        self.assertFalse(report['fixed_inputs_changed'])
        self.assertFalse(report['whole_public_scope_complete'])

    def test_acquisition_catalog_is_projected_from_registry(self):
        for method in ['direct', 'ckan']:
            with self.subTest(method=method):
                record = source()
                record['ingestions'] = [declaration()]
                record['acquisition'] = {'method': method}
                document = inventory(record)
                if method == 'ckan':
                    record['acquisition']['catalog'] = 'synthetic-catalog'
                    document['acquisition_catalogs'] = {'synthetic-catalog': {
                        'endpoint': 'https://example.test/api/3/action', 'org_prefix': 'test'}}
                result = self.run_cli(document)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(report['tasks'][0]['acquisition'], record['acquisition'])

    def test_options_cannot_copy_catalog_for_direct_or_ckan(self):
        for method in ['direct', 'ckan']:
            with self.subTest(method=method):
                record = source()
                record['acquisition'] = {'method': method}
                if method == 'ckan':
                    record['acquisition']['catalog'] = 'synthetic-catalog'
                record['ingestions'] = [declaration()]
                record['ingestions'][0]['options']['catalog'] = 'synthetic-catalog'
                document = inventory(record)
                document['acquisition_catalogs'] = {'synthetic-catalog': {
                    'endpoint': 'https://example.test/api/3/action', 'org_prefix': 'test'}}
                self.assert_rejected(document, "'catalog' was unexpected")

    def test_unknown_catalog_and_origin_reference_are_rejected(self):
        record = source()
        record['acquisition'] = {'method': 'ckan', 'catalog': 'missing'}
        record['ingestions'] = [declaration()]
        self.assert_rejected(inventory(record), 'unknown acquisition catalog')
        record = source()
        item = declaration(section='budget_history')
        item['options'] = {'documents': [{'source_id': 'missing'}]}
        record['ingestions'] = [item]
        self.assert_rejected(inventory(record), "unknown origin reference 'missing'")

    def test_unknown_publication_and_edition_indices_are_rejected(self):
        for field, message in [('publication_index', 'unknown publication index'),
                               ('edition_index', 'unknown edition index')]:
            with self.subTest(field=field):
                record = source()
                record['publication_links'] = [{
                    'url': 'https://example.test/alternative.csv',
                    'basis': 'synthetic alternative publication',
                }]
                record['ingestions'] = [declaration()]
                record['ingestions'][0]['profile'][field] = 1
                self.assert_rejected(inventory(record), message)

    def test_alternative_publication_requires_basis(self):
        record = source()
        record['publication_links'] = [{'url': 'https://example.test/alternative.csv'}]
        record['ingestions'] = [declaration()]
        self.assert_rejected(inventory(record), "'basis' is a required property")

    def test_catalog_org_prefix_cannot_be_empty(self):
        record = source()
        record['acquisition'] = {'method': 'ckan', 'catalog': 'synthetic-catalog'}
        record['ingestions'] = [declaration()]
        document = inventory(record)
        document['acquisition_catalogs'] = {'synthetic-catalog': {
            'endpoint': 'https://example.test/api/3/action', 'org_prefix': ''}}
        self.assert_rejected(document, 'org_prefix')

    def test_profile_and_resource_directions_must_agree(self):
        for field in ['profile', 'resource']:
            with self.subTest(field=field):
                record = source()
                record['ingestions'] = [declaration()]
                item = record['ingestions'][0]
                target = item['profile'] if field == 'profile' else item['options']['resource']
                target['direction'] = 'revenue'
                self.assert_rejected(inventory(record), 'profile and resource directions disagree')

    def test_options_cannot_copy_download_url(self):
        for section, nested in [('csv', False), ('csv', True), ('statement', False)]:
            with self.subTest(section=section, nested=nested):
                record = source()
                record['ingestions'] = [declaration(section=section)]
                options = record['ingestions'][0]['options']
                target = options['resource'] if nested else options
                target['url'] = 'https://example.test/copied-original.csv'
                self.assert_rejected(inventory(record), "'url' was unexpected")

    def test_duplicate_processing_key_is_rejected(self):
        record = source()
        record['ingestions'] = [declaration(section='statement'),
                                declaration(section='statement')]
        self.assert_rejected(inventory(record), 'duplicate processing registration')


if __name__ == '__main__':
    unittest.main()
