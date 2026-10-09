"""Cleanup confirms deletion without touching current tables or other object scopes."""
from copy import deepcopy
import json
import subprocess
import unittest
from unittest.mock import patch

from ingestion.fiscal import manifest, storage


class CleanupTest(unittest.TestCase):
    def setUp(self):
        self.document = {
            'target': {'jurisdiction': '131041', 'fiscal_year': 2025, 'document_kind': 'settlement'},
            'direction': 'expenditure',
            'tables': [{'object': {'key': 'fiscal/ingestion/131041/2025/settlement/expenditure/current.parquet'}}],
        }
        self.prefix = manifest.object_key(self.document, 'placeholder').rsplit('/', 1)[0] + '/'
        self.wanted = self.document['tables'][0]['object']['key']
        self.old = self.prefix + 'old.parquet'
        self.keys = {self.wanted, self.old, self.old + '.backup',
                     self.prefix + 'notes.json', self.prefix + 'nested/old.parquet'}
        self.aborted = False
        self.validate = self.enterContext(patch.object(manifest, 'validate'))
        self.current = self.enterContext(patch.object(manifest, 'require_current'))
        self.read = self.enterContext(patch.object(manifest, 'read', return_value=self.document))
        self.list = self.enterContext(patch.object(storage.subprocess, 'check_output', side_effect=self.list_objects))
        self.delete = self.enterContext(patch.object(storage.subprocess, 'run', side_effect=self.delete_object))

    def list_objects(self, command):
        self.assertEqual(command[:4], ['cf', 'r2', 'objects', 'list'])
        self.assertEqual(command[command.index('--bucket-name') + 1], manifest.BUCKET)
        prefix = command[command.index('--prefix') + 1]
        after = command[command.index('--start-after') + 1] if '--start-after' in command else ''
        return json.dumps([{'key': key} for key in sorted(self.keys) if key.startswith(prefix) and key > after]).encode()

    def delete_object(self, command, **kwargs):
        self.assertEqual(command, ['cf', 'r2', 'objects', 'delete', self.old,
                                   '--bucket-name', manifest.BUCKET, '--force', '--quiet'])
        self.assertTrue(kwargs['check'])
        if not self.aborted:
            self.keys.remove(command[4])
        return subprocess.CompletedProcess(command, 0, stdout='Aborted.' if self.aborted else '')

    def test_forced_delete_confirms_absence_and_preserves_wanted_and_other_files(self):
        before = deepcopy(self.document)
        expected = self.keys - {self.old}
        self.assertEqual(storage.cleanup(self.document), 1)
        self.assertEqual(self.keys, expected)
        self.assertEqual(self.document, before)
        self.delete.assert_called_once()
        self.validate.assert_called_once_with(self.document)
        self.current.assert_called_once_with(self.document)
        commands = [call.args[0] for call in self.list.call_args_list]
        self.assertEqual(commands[1][commands[1].index('--prefix') + 1], self.old)
        self.assertNotIn('--start-after', commands[1])
        self.assertIn('--start-after', commands[2])

    def test_exit_zero_aborted_delete_is_rejected_when_key_remains(self):
        self.aborted = True
        before = set(self.keys)
        with self.assertRaisesRegex(ValueError, 'R2 object remains after delete'):
            storage.cleanup(self.document)
        self.assertEqual(self.keys, before)
        self.delete.assert_called_once()
        self.assertEqual(self.list.call_count, 2)

    def test_invalid_deletion_confirmation_is_rejected(self):
        responses = ({'objects': []}, [{'key': 'outside.parquet'}],
                     [{'key': self.old + '.backup'}, {'key': self.old + '.backup'}])
        for response in responses:
            with self.subTest(response=response):
                self.list.side_effect = [json.dumps([{'key': self.old}]), json.dumps(response)]
                self.delete.side_effect = None
                with self.assertRaisesRegex(ValueError, 'deletion not confirmed'):
                    storage.cleanup(self.document)

    def test_nonzero_delete_stops_before_confirmation(self):
        self.delete.side_effect = subprocess.CalledProcessError(1, ['cf', 'r2', 'objects', 'delete'])
        with self.assertRaises(subprocess.CalledProcessError):
            storage.cleanup(self.document)
        self.assertEqual(self.list.call_count, 1)
        self.assertIn(self.old, self.keys)

    def test_manifest_change_stops_before_delete(self):
        self.read.side_effect = [self.document, {**self.document, 'tables': []}]
        with self.assertRaisesRegex(ValueError, 'Saved manifest changed'):
            storage.cleanup(self.document)
        self.delete.assert_not_called()

    def test_stale_manifest_stops_before_any_r2_command(self):
        self.current.side_effect = ValueError('Stale saved table')
        with self.assertRaisesRegex(ValueError, 'Stale saved table'):
            storage.cleanup(self.document)
        self.list.assert_not_called()
        self.delete.assert_not_called()

    def test_outside_prefix_and_invalid_pagination_remain_rejected(self):
        cases = [
            ([json.dumps([{'key': 'other/old.parquet'}])], 'outside the target/direction'),
            ([json.dumps([{'key': self.old}, {'key': self.old}])], 'Non-advancing'),
            ([json.dumps([{'key': self.old}, {'key': self.wanted}])], 'Non-advancing'),
            ([json.dumps([{'key': self.wanted}]), json.dumps([{'key': self.wanted}])], 'Non-advancing'),
            ([json.dumps({'objects': []})], 'Unrecognized R2'),
        ]
        for responses, message in cases:
            with self.subTest(message=message, responses=responses):
                self.list.side_effect = responses
                with self.assertRaisesRegex(ValueError, message):
                    storage.cleanup(self.document)
                self.delete.assert_not_called()


if __name__ == '__main__':
    unittest.main()
