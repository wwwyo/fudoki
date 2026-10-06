"""固定入力の欠落・改変・版の食い違いを build の前に拒否する。"""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ingestion import inputs


class FixedInputs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(inputs, 'CACHE', self.root), patch.object(inputs, 'OBJECTS', self.root / 'objects')]
        for item in self.patches:
            item.start()
        origin = inputs.save_object('origin', b'unchanged synthetic original\n')
        self.lock = self.root / 'sources.lock.json'
        self.entry = {'jurisdiction': '000001', 'fiscalYear': 2026, 'documentKind': 'settlement', 'direction': 'expenditure', 'originEdition': origin['sha256'],
                      'path': f'jurisdiction=000001/year=2026/document_kind=settlement/edition={origin["sha256"]}/direction=expenditure',
                      'origin': {'availability': 'stored', 'sha256': origin['sha256'], 'object': origin},
                      'table': inputs.save_object('table', b'synthetic table bytes\n')}
        self.entry['source'] = {'request_url': 'https://example.test/original.csv', 'raw_form': 'verbatim'}
        self.write_lock(self.entry)

    def write_lock(self, entry):
        self.lock.write_bytes(inputs.encode({'schemaVersion': 3, 'entries': [entry]}))

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_offline_restore_uses_fixed_bytes_and_never_requests_current_url(self):
        with patch.object(inputs, 'remote_object', side_effect=AssertionError('network requested')):
            target = inputs.restore(self.lock)
        self.assertEqual((target / self.entry['path'] / 'data.parquet').read_bytes(), b'synthetic table bytes\n')
        self.assertEqual(list(target.rglob('provenance.json')), [])

    def test_source_cannot_contain_execution_results_or_another_scope(self):
        for field in ['extracted', 'rows', 'fiscal_year', 'roundtrip_verified']:
            entry = copy.deepcopy(self.entry)
            entry['source'][field] = 1
            self.write_lock(entry)
            with self.assertRaisesRegex(ValueError, 'execution results'):
                inputs.read_lock(self.lock)

    def test_pinning_uploads_only_originals_and_tables_without_sidecars(self):
        raw = inputs.restore(self.lock)
        (raw / self.entry['path'] / 'inputs.lock.json').write_bytes(self.lock.read_bytes())
        canonical = self.root / 'ingestion/fiscal/sources.lock.json'
        with patch.object(inputs, 'LOCK', canonical), patch.object(inputs, 'remote_object') as remote:
            result = inputs.migrate(raw, remote=True)
        self.assertEqual(result, canonical)
        self.assertCountEqual([(args[0]['key'], args[1]) for args, _ in remote.call_args_list],
                              [(ref['key'], operation) for ref in [self.entry['table'], self.entry['origin']['object']] for operation in ['put', 'get']])
        restored = inputs.restore(canonical)
        self.assertEqual(list(restored.rglob('provenance.json')), [])
        self.assertEqual(inputs.read_lock(canonical)['entries'][0]['source'], self.entry['source'])

    def test_failed_remote_transfer_does_not_replace_git_snapshot(self):
        raw = inputs.restore(self.lock)
        (raw / self.entry['path'] / 'inputs.lock.json').write_bytes(self.lock.read_bytes())
        before = self.lock.read_bytes()
        with patch.object(inputs, 'LOCK', self.lock), patch.object(inputs, 'remote_object', side_effect=RuntimeError('transfer failed')), patch('ingestion.fiscal.sources.all_sources', return_value={}):
            with self.assertRaisesRegex(RuntimeError, 'transfer failed'):
                inputs.migrate(raw, remote=True)
        self.assertEqual(self.lock.read_bytes(), before)
        inputs.restore(self.lock)

    def test_modified_cached_table_is_rejected(self):
        (inputs.OBJECTS / self.entry['table']['key']).write_bytes(b'modified table\n')
        with self.assertRaisesRegex(ValueError, 'hash or size'):
            inputs.restore(self.lock)

    def test_missing_original_is_rejected_without_latest_document_fallback(self):
        (inputs.OBJECTS / self.entry['origin']['object']['key']).unlink()
        with self.assertRaisesRegex(FileNotFoundError, 'Origin not cached'):
            inputs.restore(self.lock)

    def test_incomplete_edition_or_wrong_kind_cannot_be_pinned(self):
        for change in ['missing-origin', 'wrong-edition', 'wrong-kind', 'wrong-partition']:
            with self.subTest(change=change):
                entry = copy.deepcopy(self.entry)
                if change == 'missing-origin':
                    del entry['origin']['object']
                elif change == 'wrong-edition':
                    entry['originEdition'] = '0' * 64
                elif change == 'wrong-kind':
                    entry['table']['key'] = entry['table']['key'].replace('/table/', '/origin/')
                else:
                    entry['path'] = entry['path'].replace('year=2026', 'year=2025')
                self.write_lock(entry)
                with self.assertRaises(ValueError):
                    inputs.read_lock(self.lock)

    def test_path_traversal_and_noncanonical_aliases_are_rejected(self):
        for path in ['../outside', '/absolute', '.', 'a//b', 'a/./b', 'a\\b', 'a\n']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                inputs.safe_relative(path)

    def test_backup_restores_an_empty_cache_without_requesting_the_origin(self):
        archive = self.root / 'backup.zip'
        inputs.backup(self.lock, archive)
        import zipfile
        with zipfile.ZipFile(archive) as stored:
            self.assertFalse(any('provenance' in name for name in stored.namelist()))
        empty = self.root / 'empty'
        with patch.object(inputs, 'CACHE', empty), patch.object(inputs, 'OBJECTS', empty / 'objects'), patch.object(inputs, 'remote_object', side_effect=AssertionError('network requested')):
            restored = inputs.restore_backup(self.lock, archive)
            self.assertEqual((restored / self.entry['path'] / 'data.parquet').read_bytes(), b'synthetic table bytes\n')

    def test_backup_of_another_snapshot_cannot_replace_fixed_inputs(self):
        archive = self.root / 'backup.zip'
        inputs.backup(self.lock, archive)
        entry = copy.deepcopy(self.entry)
        entry['table'] = inputs.save_object('table', b'another table')
        self.write_lock(entry)
        with self.assertRaisesRegex(ValueError, 'another fixed input'):
            inputs.restore_backup(self.lock, archive)


if __name__ == '__main__':
    unittest.main()
