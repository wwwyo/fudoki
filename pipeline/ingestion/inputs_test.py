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
        provenance = {'jurisdiction_code': '000001', 'fiscal_year': 2026, 'sha256': origin['sha256']}
        self.lock = self.root / 'sources.lock.json'
        self.entry = {'jurisdiction': '000001', 'fiscalYear': 2026, 'documentKind': 'settlement', 'direction': 'expenditure', 'originEdition': origin['sha256'],
                      'path': f'jurisdiction=000001/year=2026/document_kind=settlement/edition={origin["sha256"]}/direction=expenditure',
                      'origin': {'availability': 'stored', 'sha256': origin['sha256'], 'object': origin},
                      'table': inputs.save_object('table', b'synthetic table bytes\n')}
        self.entry['provenance'] = inputs.save_provenance(self.lock, self.entry['path'], inputs.encode(provenance))
        self.write_lock(self.entry)

    def write_lock(self, entry):
        self.lock.write_bytes(inputs.encode({'schemaVersion': 2, 'entries': [entry]}))

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_offline_restore_uses_fixed_bytes_and_never_requests_current_url(self):
        with patch.object(inputs, 'remote_object', side_effect=AssertionError('network requested')):
            target = inputs.restore(self.lock)
        self.assertEqual((target / self.entry['path'] / 'data.parquet').read_bytes(), b'synthetic table bytes\n')
        self.assertEqual((target / self.entry['path'] / 'provenance.json').read_bytes(), (self.lock.parent / self.entry['provenance']['path']).read_bytes())

    def test_changed_git_provenance_is_rejected_before_any_remote_request(self):
        (self.lock.parent / self.entry['provenance']['path']).write_bytes(b'{}\n')
        with patch.object(inputs, 'remote_object', side_effect=AssertionError('network requested')):
            with self.assertRaisesRegex(ValueError, 'hash or size'):
                inputs.restore(self.lock, remote=True)

    def test_missing_git_provenance_does_not_fall_back_to_r2(self):
        (self.lock.parent / self.entry['provenance']['path']).unlink()
        with patch.object(inputs, 'remote_object', side_effect=AssertionError('network requested')):
            with self.assertRaises(FileNotFoundError):
                inputs.restore(self.lock, remote=True)

    def test_pinning_uploads_only_originals_and_tables_and_keeps_provenance_in_git(self):
        raw = inputs.restore(self.lock)
        canonical = self.root / 'ingestion/fiscal/sources.lock.json'
        obsolete = canonical.parent / 'provenance/obsolete/provenance.json'
        obsolete.parent.mkdir(parents=True)
        obsolete.write_text('{}')
        with patch.object(inputs, 'LOCK', canonical), patch.object(inputs, 'remote_object') as remote, patch('ingestion.fiscal.sources.all_sources', return_value={}):
            result = inputs.migrate(raw, remote=True)
        self.assertEqual(result, canonical)
        self.assertFalse(obsolete.exists())
        self.assertCountEqual([(args[0]['key'], args[1]) for args, _ in remote.call_args_list],
                              [(ref['key'], operation) for ref in [self.entry['table'], self.entry['origin']['object']] for operation in ['put', 'get']])
        restored = inputs.restore(canonical)
        self.assertEqual((restored / self.entry['path'] / 'provenance.json').read_bytes(), (canonical.parent / self.entry['provenance']['path']).read_bytes())

    def test_failed_remote_transfer_does_not_replace_git_snapshot(self):
        raw = inputs.restore(self.lock)
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

    def test_valid_provenance_hash_cannot_refer_to_another_scope(self):
        entry = copy.deepcopy(self.entry)
        entry['provenance'] = inputs.save_provenance(self.lock, entry['path'], inputs.encode({'jurisdiction_code': '000002', 'fiscal_year': 2026, 'sha256': entry['originEdition']}))
        self.write_lock(entry)
        with self.assertRaisesRegex(ValueError, 'scope or edition'):
            inputs.restore(self.lock)

    def test_path_traversal_and_noncanonical_aliases_are_rejected(self):
        for path in ['../outside', '/absolute', '.', 'a//b', 'a/./b', 'a\\b', 'a\n']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                inputs.safe_relative(path)

    def test_backup_restores_an_empty_cache_without_requesting_the_origin(self):
        archive = self.root / 'backup.zip'
        inputs.backup(self.lock, archive)
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
