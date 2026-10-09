"""Black-box conversion and registry-boundary checks with supplied local originals."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import duckdb
import jsonschema

from ingestion.fiscal import manifest
from ingestion.fiscal.run import convert
from ingestion.fiscal.migrate import import_tables
from ingestion.fiscal.run import table_receipt


class ManifestWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.code = self.root / 'ingestion'
        self.pipeline = self.root / 'pipeline'
        self.source = self.pipeline / 'source_selection'
        self.source.mkdir(parents=True)
        self.files = {}
        original_code = manifest.INGESTION
        for name in ('fiscal/layouts/csv/convert.py', 'fiscal/layouts/csv/options.schema.json',
                     'lib/conversion.py', 'lib/parquet.py'):
            target = self.code / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original_code / name, target)
        self.patch = patch.multiple(manifest, INGESTION=self.code, PIPELINE=self.pipeline,
                                    JURISDICTIONS=self.root/'jurisdictions')
        self.patch.start()
        self.target = {'jurisdiction': '131016', 'fiscal_year': 2024, 'document_kind': 'initial'}
        originals = []
        archived = []
        conversions = []
        for index, (ident, data) in enumerate([('one', '名称,金額\n事業A,"1,000"\n'), ('two', '名称,金額\n事業B,0\n')], 1):
            file = self.root / f'{ident}.csv'
            file.write_text(data)
            sha = manifest.sha_file(file)
            self.files[sha] = str(file)
            originals.append({'format': 'csv', 'sha256': sha, 'download_url': f'https://example.test/{ident}.csv',
                              'scope': [{'account': '一般会計', 'direction': 'expenditure'}]})
            archived.append({'sha256': sha, 'key': f'fiscal/source-selection/131016/2024/initial-{index}.csv'})
            conversions.append({'id': ident, 'converter': 'fiscal/layouts/csv/convert.py',
                'inputs': [{'sha256': sha}],
                'options': {'encoding': 'utf-8', 'table_id': ident},
                'expected_tables': [{'table_id': ident}]})
        self.selection = {'target': self.target, 'selected_candidate_id': 'chosen',
                          'candidates': [{'id': 'chosen', 'files': originals}],
                          'archive': {'bucket': 'fudoki-inputs', 'candidate_id': 'chosen', 'files': archived}}
        self.ledger = self.source / '131016.json'
        self.ledger.write_text(json.dumps({'selections': [self.selection]}))
        self.document = {'schema_version': 1, 'target': self.target, 'direction': 'expenditure',
                         'conversions': conversions, 'tables': []}
        self.path = self.root / 'jurisdictions/131016/2024/initial/expenditure.json'
        manifest.write(self.path, self.document)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_multiple_originals_and_conversions_preserve_raw_values_and_do_not_claim_saved(self):
        result = convert(self.path, self.files, self.root / 'candidate')
        self.assertEqual(result['status'], 'candidate')
        self.assertEqual(result['tables'], 2)
        checks = json.loads((self.root/'candidate/one.checks.json').read_text())
        self.assertEqual(checks['status'], 'passed')
        self.assertEqual(checks['check'], 'csv_to_parquet_preservation')
        self.assertEqual(checks['origin_sha256'], manifest.sha_file(Path(next(iter(self.files.values())))))
        self.assertEqual(checks['parquet_sha256'], manifest.sha_file(self.root/'candidate/one.parquet'))
        self.assertEqual(manifest.read(self.path)['tables'], [])
        candidate = json.loads(Path(result['candidate']).read_text())
        manifest.validate(candidate)
        manifest.require_current(candidate)
        with duckdb.connect() as con:
            values = con.execute('select 名称, 金額 from read_parquet(?)', [str(self.root/'candidate/one.parquet')]).fetchall()
        self.assertEqual(values, [('事業A', '1,000')])

    def test_csv_preservation_failure_stops_before_saving_or_registry_update(self):
        before = self.path.read_bytes()
        with patch('ingestion.lib.conversion.verify_csv', side_effect=ValueError('CSV preservation failed')), \
             patch('ingestion.fiscal.run.save') as save, patch('ingestion.fiscal.run.cleanup') as cleanup:
            with self.assertRaisesRegex(ValueError, 'CSV preservation failed'):
                convert(self.path, self.files, self.root/'rejected', remote=True)
        save.assert_not_called()
        cleanup.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((self.root/'rejected/manifest.json').exists())
        self.assertFalse((self.root/'rejected/one.parquet').exists())
        self.assertEqual(json.loads((self.root/'rejected/one.checks.json').read_text())['status'], 'failed')

    def test_converter_metadata_survives_registry_readback_and_unchanged_reconversion(self):
        metadata = {
            'units': [{'text': '千円', 'scope': {'kind': 'columns', 'columns': ['金額']}}],
            'notes': [{'text': '原典の注記', 'scope': {'kind': 'table'}}],
            'column_contexts': [
                {'columns': ['名称'], 'header_path': [], 'grain_columns': ['名称'], 'semantic_role': 'project'},
                {'columns': ['金額'], 'header_path': [], 'grain_columns': ['名称'], 'semantic_role': 'setsu'},
            ],
        }
        code = self.code/'fiscal/layouts/csv/convert.py'
        code.write_text(code.read_text().replace('    return {table_id: output}',
            f"    return {{table_id: {{'path': output, 'metadata': {metadata!r}}}}}"))
        with patch('ingestion.fiscal.run.save'), patch('ingestion.fiscal.run.cleanup'):
            convert(self.path, self.files, self.root/'annotated', remote=True)
        saved = manifest.read(self.path)
        self.assertEqual(saved['tables'][0]['metadata'], metadata)
        # A path-only caller can retain annotations only for identical inputs and bytes.
        receipt = table_receipt(saved, saved['conversions'][0], 'one', self.root/'annotated/one.parquet')
        self.assertEqual(receipt['metadata'], metadata)
        with self.assertRaisesRegex(ValueError, 'Changed annotated table'):
            table_receipt(saved, saved['conversions'][0], 'one', self.root/'annotated/one.parquet',
                          input_fingerprint='0'*64)
        with duckdb.connect() as con:
            columns = con.execute('describe select * from read_parquet(?)',
                                  [str(self.root/'annotated/one.parquet')]).fetchall()
            values = con.execute('select 金額 from read_parquet(?)',
                                 [str(self.root/'annotated/one.parquet')]).fetchall()
        self.assertEqual([row[0] for row in columns], ['名称', '金額', 'source_line_start', 'source_line_end'])
        self.assertEqual(values, [('1,000',)])

    def test_metadata_unknown_columns_stop_before_upload_and_invalid_scopes_are_rejected(self):
        code = self.code/'fiscal/layouts/csv/convert.py'
        metadata = {'units': [{'text': '千円', 'scope': {'kind': 'columns', 'columns': ['存在しない列']}}]}
        code.write_text(code.read_text().replace('    return {table_id: output}',
            f"    return {{table_id: {{'path': output, 'metadata': {metadata!r}}}}}"))
        before = self.path.read_bytes()
        with patch('ingestion.fiscal.run.save') as save:
            with self.assertRaisesRegex(ValueError, 'missing Parquet columns'):
                convert(self.path, self.files, self.root/'bad-metadata', remote=True)
        save.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)
        for invalid in (
            {'units': [{'text': '千円', 'scope': {'kind': 'table', 'columns': ['金額']}}]},
            {'units': [{'text': '千円', 'scope': {'kind': 'columns', 'columns': []}}]},
            {'column_contexts': [{'columns': ['金額'], 'header_path': [], 'grain_columns': ['別の目']}]},
            {'column_contexts': [{'columns': ['金額'], 'header_path': [], 'grain_columns': ['名称']}]*2},
            {'column_contexts': [{'columns': ['金額'], 'header_path': [], 'grain_columns': ['名称'], 'semantic_role': 'unknown'}]},
            {'aggregation': 'sum'},
        ):
            with self.subTest(metadata=invalid), self.assertRaises((ValueError, jsonschema.ValidationError)):
                manifest.validate_metadata(invalid, ['名称', '金額'])

    def test_original_changed_during_conversion_stops_before_saving(self):
        code = self.code / 'fiscal/layouts/csv/convert.py'
        code.write_text(code.read_text().replace('    return {table_id: output}',
                                                "    source['path'].write_text('changed')\n    return {table_id: output}"))
        before = self.path.read_bytes()
        with patch('ingestion.fiscal.run.save') as save:
            with self.assertRaisesRegex(ValueError, 'original changed during conversion'):
                convert(self.path, self.files, self.root/'changed', remote=True)
        save.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((self.root/'changed/manifest.json').exists())

    def test_structural_errors_and_unknown_options_are_rejected_before_conversion(self):
        for mutate in (lambda d: d.update(extra=True),
                       lambda d: d['conversions'].append(deepcopy(d['conversions'][0])),
                       lambda d: d['conversions'][1]['expected_tables'][0].update(table_id='one'),
                       lambda d: d['conversions'][0]['expected_tables'][0].update(declaration={'definition_files': {}}),
                       lambda d: d['conversions'][0]['expected_tables'][0].update(legacy_path='dbt/path'),
                       lambda d: d['conversions'][0].update(converter='../../outside.py'),
                       lambda d: d['conversions'][0]['options'].update(typo=True)):
            document = deepcopy(self.document)
            mutate(document)
            with self.assertRaises((ValueError, jsonschema.ValidationError)):
                manifest.validate(document)
        with self.assertRaises(ValueError):
            manifest.write(self.path.with_name('revenue.json'), self.document)

    def test_upstream_changes_account_mismatch_and_changed_bytes_stop_execution(self):
        altered = deepcopy(self.document)
        altered['direction'] = 'revenue'
        manifest.validate(altered)
        with self.assertRaises(ValueError):
            manifest.resolved_inputs(altered, altered['conversions'][0])
        manifest.write(self.path, self.document)
        self.selection['selected_candidate_id'] = 'other'
        self.ledger.write_text(json.dumps({'selections': [self.selection]}))
        with self.assertRaises(ValueError):
            convert(self.path, self.files, self.root / 'bad-selection')
        self.selection['selected_candidate_id'] = 'chosen'
        self.ledger.write_text(json.dumps({'selections': [self.selection]}))
        Path(next(iter(self.files.values()))).write_text('changed')
        with self.assertRaises(ValueError):
            convert(self.path, self.files, self.root / 'bad-bytes')

    def test_fingerprint_tracks_only_relevant_conditions_and_not_result_fields(self):
        conversion = self.document['conversions'][0]
        before = manifest.fingerprint(self.document, conversion)
        self.document['tables'] = [{'anything': 'result fields excluded'}]
        self.assertEqual(manifest.fingerprint(self.document, conversion), before)
        (self.code/'unrelated.py').write_text('# unrelated')
        self.assertEqual(manifest.fingerprint(self.document, conversion), before)
        with (self.code/'lib/parquet.py').open('a') as stream:
            stream.write('\n# relevant code change\n')
        self.assertNotEqual(manifest.fingerprint(self.document, conversion), before)

    def test_relative_imports_and_literal_config_files_invalidate_fingerprint(self):
        conversion = self.document['conversions'][0]
        layout = self.code/'fiscal/layouts/csv'
        (layout/'__init__.py').write_text('')
        (layout/'decoder.py').write_text('VALUE = 1\n')
        code = layout/'convert.py'
        code.write_text(code.read_text() + '\nfrom . import decoder\n')
        before = manifest.fingerprint(self.document, conversion)
        (layout/'decoder.py').write_text('VALUE = 2\n')
        self.assertNotEqual(manifest.fingerprint(self.document, conversion), before)
        extra = layout/'dictionary.json'
        extra.write_text('{}')
        code.write_text(code.read_text() + '\nCONFIG = \"dictionary.json\"\n')
        manifest.validate(self.document)
        before = manifest.fingerprint(self.document, conversion)
        extra.write_text('{"word":"new"}')
        self.assertNotEqual(manifest.fingerprint(self.document, conversion), before)

    def test_saved_table_keys_ownership_completeness_and_empty_outputs(self):
        result = convert(self.path, self.files, self.root/'candidate')
        candidate = json.loads(Path(result['candidate']).read_text())
        for mutate in (lambda d: d['tables'][0]['object'].update(key=d['tables'][0]['object']['key'].replace('expenditure', 'revenue')),
                       lambda d: d['tables'].pop(),
                       lambda d: d['tables'][0].update(conversion_id='two'),
                       lambda d: d['tables'][0].update(row_count=0)):
            bad = deepcopy(candidate)
            mutate(bad)
            with self.assertRaises((ValueError, jsonschema.ValidationError)):
                manifest.validate(bad)

    def test_partial_execution_cannot_drop_unsaved_tables(self):
        with self.assertRaises(ValueError):
            convert(self.path, self.files, self.root/'partial', conversion_ids=['one'])

    def test_partial_remote_conversion_only_uploads_selected_table(self):
        result = convert(self.path, self.files, self.root/'partial-baseline')
        saved = json.loads(Path(result['candidate']).read_text())
        saved['tables'][0]['metadata'] = {
            'notes': [{'text': '既存の原典注記', 'scope': {'kind': 'table'}}]}
        manifest.write(self.path, saved)
        local = {t['object']['sha256']: self.root/'partial-baseline'/f'{t["table_id"]}.parquet'
                 for t in saved['tables']}
        old_bytes = {sha: path.read_bytes() for sha, path in local.items()}
        with patch('ingestion.fiscal.run.fetch', side_effect=lambda ref, **kwargs: local[ref['sha256']]), \
             patch('ingestion.fiscal.run.save') as save, patch('ingestion.fiscal.run.cleanup'):
            convert(self.path, self.files, self.root/'partial-remote',
                    conversion_ids=['two'], remote=True)
        save.assert_called_once()
        self.assertEqual(save.call_args.args[1]['table_id'], 'two')
        published = manifest.read(self.path)
        self.assertEqual(published['tables'][0], saved['tables'][0])
        self.assertEqual(published['conversions'], saved['conversions'])
        self.assertEqual({sha: path.read_bytes() for sha, path in local.items()}, old_bytes)
        manifest.require_current(published)

    def test_failed_upload_does_not_replace_registry_or_delete_old_objects(self):
        before = self.path.read_bytes()
        with patch('ingestion.fiscal.run.save', side_effect=[None, RuntimeError('upload failed')]), \
             patch('ingestion.fiscal.run.cleanup') as cleanup:
            with self.assertRaisesRegex(RuntimeError, 'upload failed'):
                convert(self.path, self.files, self.root/'failed-upload', remote=True)
        self.assertEqual(self.path.read_bytes(), before)
        cleanup.assert_not_called()

    def test_readback_rejects_changed_conversion_code(self):
        result = convert(self.path, self.files, self.root/'candidate')
        candidate = json.loads(Path(result['candidate']).read_text())
        manifest.require_current(candidate)
        with (self.code/'lib/parquet.py').open('a') as stream:
            stream.write('\n# changed extraction dependency\n')
        with self.assertRaisesRegex(ValueError, 'Stale saved table'):
            manifest.require_current(candidate)

    def test_import_extension_preserves_saved_registry_until_full_upload_and_refuses_redefinitions(self):
        candidate = convert(self.path, self.files, self.root/'candidate')
        generated = json.loads(Path(candidate['candidate']).read_text())
        real_code = Path(__file__).with_name('layouts') / 'retained'
        retained = self.code / 'fiscal/layouts/retained'
        retained.mkdir(parents=True)
        for name in ('convert.py', 'options.schema.json'):
            shutil.copyfile(real_code/name, retained/name)
        document = deepcopy(self.document)
        local = {}
        for conversion, table in zip(document['conversions'], generated['tables'], strict=True):
            conversion.update(converter='fiscal/layouts/retained/convert.py')
            conversion['options'] = {'objects': [{'table_id': table['table_id'],
                'key': 'inputs/table/sha256/' + table['object']['sha256'],
                'sha256': table['object']['sha256'], 'bytes': table['object']['bytes']}]}
            local[table['object']['sha256']] = self.root/'candidate'/f'{table["table_id"]}.parquet'
        previous = deepcopy(document)
        previous['conversions'] = previous['conversions'][:1]
        conversion = previous['conversions'][0]
        reference = conversion['options']['objects'][0]
        previous['tables'] = [table_receipt(previous, conversion, reference['table_id'], local[reference['sha256']])]
        previous['tables'][0]['metadata'] = {'notes': [{'text': '保存済み注記', 'scope': {'kind': 'table'}}]}
        manifest.write(self.path, previous)
        from dbt_inputs import path_for, write as write_bindings, read as read_bindings
        binding = {'schema_version': 1, 'target': self.target, 'direction': 'expenditure',
                   'tables': [{'table_id': conversion['id'], 'raw_path':
                     f"jurisdiction=131016/year=2024/document_kind=budget/edition={conversion['inputs'][0]['sha256']}/direction=expenditure/table={conversion['id']}/data.parquet"}
                     for conversion in document['conversions']]}
        old_binding = deepcopy(binding)
        old_binding['tables'] = old_binding['tables'][:1]
        write_bindings(old_binding, previous)
        binding_before = path_for(previous).read_bytes()
        before = self.path.read_bytes()
        with patch('ingestion.fiscal.migrate.fetch', side_effect=lambda ref, **kwargs: local[ref['sha256']]), \
             patch('ingestion.fiscal.migrate.save') as save, patch('ingestion.fiscal.migrate.cleanup') as cleanup:
            with self.assertRaisesRegex(ValueError, 'differs'):
                import_tables(document, remote=True)
            save.assert_not_called()
            save.side_effect = RuntimeError('upload failed')
            with self.assertRaisesRegex(RuntimeError, 'upload failed'):
                import_tables(document, remote=True, extend_plans=True, bindings=binding)
            self.assertEqual(path_for(previous).read_bytes(), binding_before)
            self.assertEqual(self.path.read_bytes(), before)
            cleanup.assert_not_called()
            save.side_effect = None
            save.reset_mock()
            # A binding write error leaves both prior registrations usable.
            with patch('dbt_inputs.write', side_effect=OSError('binding write failed')):
                with self.assertRaisesRegex(OSError, 'binding write failed'):
                    import_tables(document, remote=True, extend_plans=True, bindings=binding)
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(path_for(previous).read_bytes(), binding_before)
            cleanup.assert_not_called()
            save.reset_mock()
            # Cleanup failure happens after both usable registrations are published.
            cleanup.side_effect = RuntimeError('cleanup failed')
            with self.assertRaisesRegex(RuntimeError, 'cleanup failed'):
                import_tables(document, remote=True, extend_plans=True, bindings=binding)
            save.assert_called_once()
            self.assertEqual(save.call_args.args[1]['table_id'], 'two')
            cleanup.side_effect = None
            result = import_tables(document, remote=True, extend_plans=True, bindings=binding)
            self.assertEqual(result['tables'], 2)
            self.assertEqual(set(read_bindings(manifest.read(self.path))), {'one', 'two'})
            saved = manifest.read(self.path)
            self.assertEqual(saved['conversions'][0], previous['conversions'][0])
            self.assertEqual(saved['tables'][0], previous['tables'][0])
            manifest.require_current(saved)
            altered = deepcopy(document)
            altered['conversions'][0]['options']['objects'][0]['bytes'] += 1
            with self.assertRaisesRegex(ValueError, 'differs'):
                import_tables(altered, remote=True, extend_plans=True)

    def test_plan_only_extension_rejects_before_changing_bindings(self):
        from dbt_inputs import path_for, write as write_bindings
        from ingestion.fiscal.migrate import main
        previous = deepcopy(self.document)
        previous['conversions'] = previous['conversions'][:1]
        manifest.write(self.path, previous)
        binding = {'schema_version': 1, 'target': self.target, 'direction': 'expenditure',
                   'tables': [{'table_id': conversion['id'], 'raw_path':
                     f"jurisdiction=131016/year=2024/document_kind=budget/edition={conversion['inputs'][0]['sha256']}/direction=expenditure/table={conversion['id']}/data.parquet"}
                     for conversion in self.document['conversions']]}
        old_binding = deepcopy(binding)
        old_binding['tables'] = old_binding['tables'][:1]
        write_bindings(old_binding, previous)
        before = self.path.read_bytes(), path_for(previous).read_bytes()
        lock = self.root/'lock.json'
        lock.write_text('{}')
        report = {'dbt_bindings': [binding]}
        with patch('ingestion.fiscal.migrate.plan', return_value=([self.document], report)), \
             patch('sys.argv', ['migrate', '--lock', str(lock), '--report', str(self.root/'report.json'),
                                '--write-plans', '--extend-plans']):
            with self.assertRaisesRegex(ValueError, 'import additional tables'):
                main()
        self.assertEqual((self.path.read_bytes(), path_for(previous).read_bytes()), before)

    def retained_extension(self):
        generated = json.loads(Path(convert(self.path, self.files, self.root/'baseline')['candidate']).read_text())
        real_code = Path(__file__).with_name('layouts') / 'retained'
        retained = self.code / 'fiscal/layouts/retained'
        retained.mkdir(parents=True)
        for name in ('convert.py', 'options.schema.json'):
            shutil.copyfile(real_code/name, retained/name)
        saved = deepcopy(self.document)
        local = {t['object']['sha256']: self.root/'baseline'/f'{t["table_id"]}.parquet' for t in generated['tables']}
        for conversion, table in zip(saved['conversions'], generated['tables'], strict=True):
            conversion['converter'] = 'fiscal/layouts/retained/convert.py'
            conversion['options'] = {'objects': [{'table_id': table['table_id'], 'key': 'inputs/table/sha256/' + table['object']['sha256'],
                                                  'sha256': table['object']['sha256'], 'bytes': table['object']['bytes']}]}
            saved['tables'].append(table_receipt(saved, conversion, table['table_id'], local[table['object']['sha256']]))
        saved['tables'][0]['metadata'] = {'notes': [{'text': '既存の原典注記', 'scope': {'kind': 'table'}}]}
        manifest.write(self.path, saved)
        manifest.require_current(saved)
        plan = deepcopy(saved)
        plan['tables'] = []
        plan['conversions'].append({'id': 'three', 'converter': 'fiscal/layouts/csv/convert.py',
                                   'inputs': deepcopy(self.document['conversions'][0]['inputs']),
                                   'options': {'encoding': 'utf-8', 'table_id': 'three'}, 'expected_tables': [{'table_id': 'three'}]})
        plan_path = self.root/'extension.json'
        plan_path.write_text(json.dumps(plan))
        new_files = {sha: self.files[sha] for sha in [plan['conversions'][-1]['inputs'][0]['sha256']]}
        return saved, local, plan, plan_path, new_files

    def test_convert_extension_preserves_retained_bytes_receipts_and_only_saves_new_table(self):
        saved, local, plan, plan_path, new_files = self.retained_extension()
        before = self.path.read_bytes()
        old_bytes = {sha: path.read_bytes() for sha, path in local.items()}
        fingerprints = manifest.fingerprints(saved)
        with patch('ingestion.fiscal.run.fetch', side_effect=lambda ref, **kwargs: local[ref['sha256']]), \
             patch('ingestion.fiscal.run.save') as save, patch('ingestion.fiscal.run.cleanup') as cleanup:
            result = convert(self.path, new_files, self.root/'extended-local', extend_plan=plan_path)
            candidate = json.loads(Path(result['candidate']).read_text())
            self.assertEqual(result['tables'], 3)
            self.assertEqual(candidate['tables'][:2], saved['tables'])
            self.assertEqual(self.path.read_bytes(), before)
            save.assert_not_called()
            cleanup.assert_not_called()
            self.assertEqual({sha: path.read_bytes() for sha, path in local.items()}, old_bytes)
            with patch('ingestion.fiscal.run.manifest.write', wraps=manifest.write) as write:
                result = convert(self.path, new_files, self.root/'extended-remote', extend_plan=plan_path, remote=True)
                write.assert_called_once()
            save.assert_called_once()
            self.assertEqual(save.call_args.args[1]['table_id'], 'three')
            published = manifest.read(self.path)
            self.assertEqual(published['tables'][:2], saved['tables'])
            self.assertEqual(published['conversions'], plan['conversions'])
            self.assertEqual({key: value for key, value in manifest.fingerprints(published).items() if key in fingerprints}, fingerprints)
            self.assertEqual(cleanup.call_args.args[0]['tables'], published['tables'])
            self.assertEqual({sha: path.read_bytes() for sha, path in local.items()}, old_bytes)
            manifest.require_current(published)

    def test_convert_extension_upload_failure_or_retained_hash_size_mismatch_keeps_registry(self):
        saved, local, plan, plan_path, new_files = self.retained_extension()
        before = self.path.read_bytes()
        with patch('ingestion.fiscal.run.fetch', side_effect=lambda ref, **kwargs: local[ref['sha256']]), \
             patch('ingestion.fiscal.run.save', side_effect=RuntimeError('new upload failed')) as save, \
             patch('ingestion.fiscal.run.cleanup') as cleanup, patch('ingestion.fiscal.run.manifest.write') as write:
            with self.assertRaisesRegex(RuntimeError, 'new upload failed'):
                convert(self.path, new_files, self.root/'extension-failed', extend_plan=plan_path, remote=True)
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(save.call_args.args[1]['table_id'], 'three')
            cleanup.assert_not_called()
            write.assert_not_called()
        for case in ('bytes', 'sha256'):
            invalid = deepcopy(saved)
            if case == 'bytes':
                invalid['tables'][0]['object']['bytes'] += 1
                wrong = local[saved['tables'][0]['object']['sha256']]
            else:
                wrong = self.root/'corrupted.parquet'
                wrong.write_bytes(b'changed')
            manifest.write(self.path, invalid)
            before = self.path.read_bytes()
            with patch('ingestion.fiscal.run.fetch', return_value=wrong), patch('ingestion.fiscal.run.save') as save:
                with self.subTest(case=case), self.assertRaisesRegex(ValueError, 'hash/size'):
                    convert(self.path, new_files, self.root/('corrupt-' + case), extend_plan=plan_path, remote=True)
                self.assertEqual(self.path.read_bytes(), before)
                save.assert_not_called()

    def test_convert_extension_rejects_changed_definitions_scope_receipts_and_ambiguous_new_ids(self):
        saved, local, plan, plan_path, new_files = self.retained_extension()
        before = self.path.read_bytes()
        changes = (
            lambda p: p.update(target={**p['target'], 'fiscal_year': 2025}),
            lambda p: p.update(direction='revenue'),
            lambda p: p['conversions'][0]['options']['objects'][0].update(bytes=1),
            lambda p: p['tables'].extend(saved['tables']),
            lambda p: p['conversions'][-1].update(id='one'),
            lambda p: p['conversions'][-1]['expected_tables'][0].update(table_id='one'),
            lambda p: p['conversions'][-1]['expected_tables'].append({'table_id': 'four'}),
            lambda p: p['conversions'].pop(),
        )
        with patch('ingestion.fiscal.run.fetch') as fetch, patch('ingestion.fiscal.run.save') as save:
            for index, mutate in enumerate(changes):
                invalid = deepcopy(plan)
                mutate(invalid)
                plan_path.write_text(json.dumps(invalid))
                with self.subTest(case=index), self.assertRaises((ValueError, jsonschema.ValidationError)):
                    convert(self.path, new_files, self.root/f'invalid-{index}', extend_plan=plan_path, remote=True)
                self.assertEqual(self.path.read_bytes(), before)
            plan_path.write_text(json.dumps(plan))
            for ids in (['one'], ['three', 'three'], ['one', 'three']):
                with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, 'one new ID'):
                    convert(self.path, new_files, self.root/'invalid-choice', extend_plan=plan_path, conversion_ids=ids)
            fetch.assert_not_called()
            save.assert_not_called()

    def test_dbt_input_preparation_reads_jurisdiction_json_and_parquet_without_legacy_lock(self):
        from build_inputs import prepare
        result = convert(self.path, self.files, self.root/'candidate')
        saved = json.loads(Path(result['candidate']).read_text())
        saved['tables'][0]['metadata'] = {
            'column_contexts': [{'columns': ['金額'], 'header_path': [], 'grain_columns': ['名称']}]}
        manifest.write(self.path, saved)
        local = {table['object']['sha256']: self.root/'candidate'/f'{table["table_id"]}.parquet'
                 for table in saved['tables']}
        with patch('build_inputs.fetch', side_effect=lambda ref: local[ref['sha256']]):
            snapshot = prepare([self.path], cache=self.root/'snapshots')
            repeated = prepare([self.path], cache=self.root/'snapshots')
        self.assertEqual(snapshot, repeated)
        raw = Path(snapshot['inputs'])
        files = sorted(raw.rglob('data.parquet'))
        self.assertEqual(len(files), 2)
        self.assertEqual({manifest.sha_file(path) for path in files}, set(local))
        catalog = json.loads(Path(snapshot['catalog']).read_text())
        self.assertEqual(catalog['manifests'][0]['document'], saved)
        self.assertEqual(catalog['tables'][0]['table']['metadata'], saved['tables'][0]['metadata'])
        self.assertEqual({item['inputs'][0]['scope'][0]['account'] for item in catalog['tables']},
                         {'一般会計'})
        self.assertNotIn('declarations', snapshot)
        self.assertFalse((Path(snapshot['catalog']).parent/'declarations').exists())
        with duckdb.connect() as db:
            rows = db.execute('''select "名称", "金額", jurisdiction, year, document_kind, direction
                from read_parquet(?, hive_partitioning=true) order by "名称"''',
                [str(raw/'jurisdiction=*/year=*/document_kind=*/edition=*/direction=*/table=*/data.parquet')]).fetchall()
        self.assertEqual(rows, [('事業A', '1,000', 131016, 2024, 'budget', 'expenditure'),
                                ('事業B', '0', 131016, 2024, 'budget', 'expenditure')])
        import dbt_inputs
        from build_inputs import raw_path
        bindings = {'schema_version': 1, 'target': saved['target'], 'direction': saved['direction'],
                    'tables': [{'table_id': table['table_id'], 'raw_path': 'statement/' + raw_path(saved, owner, table)}
                               for owner in saved['conversions'] for table in owner['expected_tables']]}
        before = self.path.read_bytes()
        dbt_inputs.write(bindings, saved)
        with patch('build_inputs.fetch', side_effect=lambda ref: local[ref['sha256']]):
            changed = prepare([self.path], cache=self.root/'snapshots')
        self.assertNotEqual(changed['inputFingerprint'], snapshot['inputFingerprint'])
        self.assertEqual(self.path.read_bytes(), before)
        manifest.require_current(manifest.read(self.path))
        next(Path(changed['inputs']).rglob('data.parquet')).write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError, 'hash/size'):
            prepare([self.path], cache=self.root/'snapshots')

    def test_dbt_legacy_partition_is_preserved_and_wrong_scope_rejected(self):
        from build_inputs import raw_path
        import dbt_inputs
        document = manifest.read(self.path)
        conversion = document['conversions'][0]
        expected = deepcopy(conversion['expected_tables'][0])
        sha = conversion['inputs'][0]['sha256']
        relative = (f'statement-moku-setsu/jurisdiction=131016/year=2024/'
                    f'document_kind=budget/edition={sha}/direction=expenditure/table=legal-setsu')
        bindings = {'schema_version': 1, 'target': document['target'], 'direction': document['direction'],
                    'tables': [{'table_id': table['table_id'], 'raw_path':
                        relative.replace('table=legal-setsu', 'table='+table['table_id']).replace(
                            'edition='+sha, 'edition='+owner['inputs'][0]['sha256'])+'/data.parquet'}
                        for owner in document['conversions'] for table in owner['expected_tables']]}
        entries = dbt_inputs.validate(bindings, document)
        binding = entries[expected['table_id']]
        self.assertEqual(raw_path(document, conversion, expected, binding), binding['raw_path'])
        bindings['tables'][0]['raw_path'] = binding['raw_path'].replace('year=2024', 'year=2023')
        with self.assertRaisesRegex(ValueError, 'scope'):
            dbt_inputs.validate(bindings, document)

    def test_schema_rejects_removed_input_and_conversion_fields(self):
        for fields in ({'format': 'csv'}, {'scope': [{'account': '一般会計'}]}):
            bad = deepcopy(self.document)
            bad['conversions'][0]['inputs'][0].update(fields)
            with self.assertRaises(jsonschema.ValidationError):
                manifest.validate(bad)
        for fields in ({'dependencies': []}, {'dependencies': ['lib/parquet.py']}, {'options_schema': 'fiscal/layouts/csv/options.schema.json'}):
            bad = deepcopy(self.document)
            bad['conversions'][0].update(fields)
            with self.assertRaises(jsonschema.ValidationError):
                manifest.validate(bad)
        for field, value in (('candidate_id', 'chosen'), ('status', 'planned')):
            bad = deepcopy(self.document)
            bad[field] = value
            with self.assertRaises(jsonschema.ValidationError):
                manifest.validate(bad)
        result = convert(self.path, self.files, self.root/'candidate')
        saved = json.loads(Path(result['candidate']).read_text())
        for field, value in (('runtime', {}), ('origins', []), ('empty_confirmed', False), ('schema', [])):
            bad = deepcopy(saved)
            bad['tables'][0][field] = value
            with self.assertRaises(jsonschema.ValidationError):
                manifest.validate(bad)



if __name__ == '__main__':
    unittest.main()
