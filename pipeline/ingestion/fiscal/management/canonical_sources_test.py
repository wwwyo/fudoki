"""Publisher-selection contracts exercised through the public CLI only."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ingestion.fiscal.management.source_registry_test import PIPELINE, inventory, source


def revised_source(identifier, form, status, date):
    record = source(identifier, form, status)
    record['publisher_revision'] = {
        'revision_at': date, 'basis': 'Synthetic publisher correction notice',
        'evidence_urls': ['https://example.test/correction-notice'],
    }
    return record


class CanonicalSourcesCliTest(unittest.TestCase):
    def run_cli(self, *records):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'inventory.json'
            lock = root / 'sources.lock.json'
            path.write_text(json.dumps(inventory(*records), ensure_ascii=False), encoding='utf-8')
            lock.write_text(json.dumps({'schemaVersion': 3, 'entries': []}), encoding='utf-8')
            before = {item.name: item.read_bytes() for item in root.iterdir()}
            result = subprocess.run(
                [sys.executable, '-m', 'ingestion.fiscal.management.canonical_sources',
                 '--inventory', str(path), '--lock', str(lock), '--json'],
                cwd=PIPELINE, capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual({item.name: item.read_bytes() for item in root.iterdir()}, before)
            report = json.loads(result.stdout)
            self.assertEqual(report['network_requests'], 0)
            self.assertEqual(report['original_hashes_computed'], 0)
            self.assertFalse(report['whole_public_scope_complete'])
            self.assertFalse(report['provided_data_verified'])
            self.assertEqual(len(report['groups']), 1, result.stdout)
            return report['groups'][0]

    def test_latest_publisher_revision_precedes_csv_readability(self):
        old_csv = revised_source('old-csv', 'csv', 'csv_inspected', '2026-03-01')
        corrected_pdf = revised_source('corrected-image-pdf', 'pdf', 'image_only', '2026-03-20')
        group = self.run_cli(old_csv, corrected_pdf)
        self.assertEqual(group['canonical_source_id'], 'corrected-image-pdf')
        self.assertEqual(group['preferred_source_id'], 'corrected-image-pdf')
        self.assertEqual(group['adoption_status'], 'no_candidate_has_adopted_inputs')

    def test_same_revision_prefers_csv_then_text_pdf_then_image_pdf(self):
        records = [revised_source('image-pdf', 'pdf', 'image_only', '2026-03-20'),
                   revised_source('text-pdf', 'pdf', 'text_probed', '2026-03-20'),
                   revised_source('csv', 'csv', 'csv_inspected', '2026-03-20')]
        for candidates, expected in [(records, 'csv'), (records[:2], 'text-pdf')]:
            with self.subTest(expected=expected):
                group = self.run_cli(*candidates)
                self.assertEqual(group['canonical_source_id'], expected)
                self.assertEqual(group['preferred_source_id'], expected)

    def test_unconfirmed_revision_order_retains_preference_with_null_canonical(self):
        csv = source('unknown-revision-csv')
        pdf = source('unknown-revision-pdf', 'pdf', 'text_probed')
        group = self.run_cli(pdf, csv)
        self.assertIsNone(group['canonical_source_id'])
        self.assertEqual(group['preferred_source_id'], 'unknown-revision-csv')
        self.assertEqual(group['selection_status'], 'revision_order_unconfirmed')


if __name__ == '__main__':
    unittest.main()
