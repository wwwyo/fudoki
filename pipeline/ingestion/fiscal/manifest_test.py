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
                'options_schema': 'fiscal/layouts/csv/options.schema.json',
                'dependencies': ['lib/conversion.py', 'lib/parquet.py'],
                'inputs': [{'format': 'csv', 'sha256': sha, 'scope': [{'account': '一般会計'}]}],
                'options': {'encoding': 'utf-8', 'table_id': ident},
                'expected_tables': [{'table_id': ident}]})
        self.selection = {'target': self.target, 'selected_candidate_id': 'chosen',
                          'candidates': [{'id': 'chosen', 'files': originals}],
                          'archive': {'bucket': 'fudoki-inputs', 'candidate_id': 'chosen', 'files': archived}}
        self.ledger = self.source / '131016.json'
        self.ledger.write_text(json.dumps({'selections': [self.selection]}))
        self.document = {'schema_version': 2, 'target': self.target, 'direction': 'expenditure',
                         'candidate_id': 'chosen', 'status': 'planned', 'conversions': conversions, 'tables': []}
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
        altered['conversions'][0]['inputs'][0]['scope'][0]['account'] = '別会計'
        manifest.write(self.path, altered)
        with self.assertRaises(ValueError):
            convert(self.path, self.files, self.root / 'bad-account')
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
        self.document.update(status='ready', tables=[{'anything': 'result fields excluded'}])
        self.assertEqual(manifest.fingerprint(self.document, conversion), before)
        (self.code/'unrelated.py').write_text('# unrelated')
        self.assertEqual(manifest.fingerprint(self.document, conversion), before)
        with (self.code/'lib/parquet.py').open('a') as stream:
            stream.write('\n# relevant code change\n')
        self.assertNotEqual(manifest.fingerprint(self.document, conversion), before)

    def test_saved_table_keys_ownership_completeness_and_empty_confirmation(self):
        result = convert(self.path, self.files, self.root/'candidate')
        candidate = json.loads(Path(result['candidate']).read_text())
        for mutate in (lambda d: d['tables'][0]['object'].update(key=d['tables'][0]['object']['key'].replace('expenditure', 'revenue')),
                       lambda d: d['tables'].pop(),
                       lambda d: d['tables'][0].update(conversion_id='two'),
                       lambda d: d['tables'][0].update(row_count=0)):
            bad = deepcopy(candidate)
            mutate(bad)
            with self.assertRaises(ValueError):
                manifest.validate(bad)

    def test_partial_execution_cannot_drop_unsaved_tables(self):
        with self.assertRaises(ValueError):
            convert(self.path, self.files, self.root/'partial', conversion_ids=['one'])

    def test_failed_upload_does_not_replace_registry_or_delete_old_objects(self):
        before = self.path.read_bytes()
        with patch('ingestion.fiscal.run.save', side_effect=[None, RuntimeError('upload failed')]), \
             patch('ingestion.fiscal.run.cleanup') as cleanup:
            with self.assertRaisesRegex(RuntimeError, 'upload failed'):
                convert(self.path, self.files, self.root/'failed-upload', remote=True)
        self.assertEqual(self.path.read_bytes(), before)
        cleanup.assert_not_called()

    def test_readback_uses_recorded_runtime_and_still_rejects_changed_code(self):
        result = convert(self.path, self.files, self.root/'candidate')
        candidate = json.loads(Path(result['candidate']).read_text())
        with patch('ingestion.fiscal.manifest.runtime', return_value={'python':'different','duckdb':'different'}):
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
        sizes = {sha: Path(path).stat().st_size for sha, path in self.files.items()}
        for conversion, table in zip(document['conversions'], generated['tables'], strict=True):
            conversion.update(converter='fiscal/layouts/retained/convert.py',
                              options_schema='fiscal/layouts/retained/options.schema.json', dependencies=[])
            conversion['options'] = {'objects': [{'table_id': table['table_id'],
                'key': 'inputs/table/sha256/' + table['object']['sha256'],
                'sha256': table['object']['sha256'], 'bytes': table['object']['bytes']}]}
            local[table['object']['sha256']] = self.root/'candidate'/f'{table["table_id"]}.parquet'
        previous = deepcopy(document)
        previous['conversions'] = previous['conversions'][:1]
        conversion = previous['conversions'][0]
        reference = conversion['options']['objects'][0]
        previous.update(status='ready', tables=[table_receipt(previous, conversion, reference['table_id'],
            local[reference['sha256']], origins=[{'sha256': item['sha256'], 'bytes': sizes[item['sha256']]}
                                               for item in conversion['inputs']])])
        manifest.write(self.path, previous)
        before = self.path.read_bytes()
        with patch('ingestion.fiscal.migrate.fetch', side_effect=lambda ref, **kwargs: local[ref['sha256']]), \
             patch('ingestion.fiscal.migrate.save') as save, patch('ingestion.fiscal.migrate.cleanup') as cleanup:
            with self.assertRaisesRegex(ValueError, 'differs'):
                import_tables(document, remote=True, origin_sizes=sizes)
            save.assert_not_called()
            save.side_effect = [None, RuntimeError('upload failed')]
            with self.assertRaisesRegex(RuntimeError, 'upload failed'):
                import_tables(document, remote=True, origin_sizes=sizes, extend_plans=True)
            self.assertEqual(self.path.read_bytes(), before)
            cleanup.assert_not_called()
            save.side_effect = None
            result = import_tables(document, remote=True, origin_sizes=sizes, extend_plans=True)
            self.assertEqual(result['tables'], 2)
            saved = manifest.read(self.path)
            self.assertEqual(saved['conversions'][0], previous['conversions'][0])
            manifest.require_current(saved)
            altered = deepcopy(document)
            altered['conversions'][0]['options']['objects'][0]['bytes'] += 1
            with self.assertRaisesRegex(ValueError, 'differs'):
                import_tables(altered, remote=True, origin_sizes=sizes, extend_plans=True)

    def test_dbt_input_preparation_reads_saved_manifests_and_supplied_declarations_without_legacy_lock(self):
        from build_inputs import prepare
        result = convert(self.path, self.files, self.root/'candidate')
        saved = json.loads(Path(result['candidate']).read_text())
        manifest.write(self.path, saved)
        declarations = self.root/'confirmed'
        declarations.mkdir()
        sources = [{'dataset_id': 'declared-one', 'jurisdiction_code': '131016',
            'fiscal_year': 2024, 'direction': 'expenditure', 'document_kind': 'budget',
            'source_json': json.dumps({'rawTableSha256': saved['tables'][0]['object']['sha256']})}]
        (declarations/'sources.json').write_text(json.dumps(sources))
        (declarations/'history.json').write_text('[]\n')
        local = {table['object']['sha256']: self.root/'candidate'/f'{table["table_id"]}.parquet'
                 for table in saved['tables']}
        with patch('build_inputs.fetch', side_effect=lambda ref: local[ref['sha256']]):
            snapshot = prepare(declarations, [self.path], cache=self.root/'snapshots')
            repeated = prepare(declarations, [self.path], cache=self.root/'snapshots')
        self.assertEqual(snapshot, repeated)
        raw = Path(snapshot['inputs'])
        files = sorted(raw.rglob('data.parquet'))
        self.assertEqual(len(files), 2)
        self.assertEqual({manifest.sha_file(path) for path in files}, set(local))
        self.assertEqual((Path(snapshot['declarations'])/'sources.json').read_bytes(),
                         (declarations/'sources.json').read_bytes())
        with duckdb.connect() as db:
            rows = db.execute('''select "名称", "金額", jurisdiction, year, document_kind, direction
                from read_parquet(?, hive_partitioning=true) order by "名称"''',
                [str(raw/'jurisdiction=*/year=*/document_kind=*/edition=*/direction=*/table=*/data.parquet')]).fetchall()
        self.assertEqual(rows, [('事業A', '1,000', 131016, 2024, 'budget', 'expenditure'),
                                ('事業B', '0', 131016, 2024, 'budget', 'expenditure')])
        import dbt_inputs
        from build_inputs import raw_path
        bindings = {'schema_version': 1, 'target': saved['target'], 'direction': saved['direction'],
                    'tables': [{'table_id': table['table_id'], 'raw_path': raw_path(saved, owner, table),
                                'declaration': {'definition_files': {'pipeline/dbt/models/example.sql':
                                    {'bytes': 1, 'sha256': 'a'*64}}}}
                               for owner in saved['conversions'] for table in owner['expected_tables']]}
        before = self.path.read_bytes()
        dbt_inputs.write(bindings, saved)
        with patch('build_inputs.fetch', side_effect=lambda ref: local[ref['sha256']]):
            changed = prepare(declarations, [self.path], cache=self.root/'snapshots')
        self.assertNotEqual(changed['inputFingerprint'], snapshot['inputFingerprint'])
        self.assertEqual(self.path.read_bytes(), before)
        manifest.require_current(manifest.read(self.path))
        sources[0]['jurisdiction_code'] = '132047'
        (declarations/'sources.json').write_text(json.dumps(sources))
        with self.assertRaisesRegex(ValueError, 'scope'):
            prepare(declarations, [self.path], cache=self.root/'snapshots')
        (declarations/'sources.json').write_text((Path(snapshot['declarations'])/'sources.json').read_text())
        next(Path(changed['inputs']).rglob('data.parquet')).write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError, 'hash/size'):
            prepare(declarations, [self.path], cache=self.root/'snapshots')

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
                            'edition='+sha, 'edition='+owner['inputs'][0]['sha256'])+'/data.parquet',
                        'declaration': {}}
                        for owner in document['conversions'] for table in owner['expected_tables']]}
        entries = dbt_inputs.validate(bindings, document)
        binding = entries[expected['table_id']]
        self.assertEqual(raw_path(document, conversion, expected, binding), binding['raw_path'])
        bindings['tables'][0]['raw_path'] = binding['raw_path'].replace('year=2024', 'year=2023')
        with self.assertRaisesRegex(ValueError, 'scope'):
            dbt_inputs.validate(bindings, document)

    def test_split_metadata_preserves_receipts_and_is_idempotent(self):
        from build_inputs import raw_path
        import dbt_inputs
        from ingestion.fiscal.split_metadata import migrate
        converted = convert(self.path, self.files, self.root/'candidate')
        legacy = json.loads(Path(converted['candidate']).read_text())
        legacy['schema_version'] = 1
        for conversion in legacy['conversions']:
            for table in conversion['expected_tables']:
                table['legacy_path'] = raw_path(legacy, conversion, table).removesuffix('/data.parquet')
                table['declaration'] = {'definition_files': {'pipeline/dbt/models/example.sql':
                    {'bytes': 1, 'sha256': 'a'*64}}, 'approval_status': 'unconfirmed'}
        fingerprints = manifest.fingerprints(legacy, runtimes={table['conversion_id']: table['runtime']
                                                               for table in legacy['tables']})
        for table in legacy['tables']:
            table['input_fingerprint'] = fingerprints[table['conversion_id']]
        self.path.write_text(json.dumps(legacy))
        original_files = {path.name: manifest.sha_file(path) for path in (self.root/'candidate').glob('*.parquet')}
        self.assertEqual(migrate([self.path], apply=True)['tables'], 2)
        saved = manifest.read(self.path)
        manifest.require_current(saved)
        bindings = dbt_inputs.read(saved)
        for previous, current in zip(legacy['tables'], saved['tables'], strict=True):
            self.assertEqual({k:v for k,v in previous.items() if k != 'input_fingerprint'},
                             {k:v for k,v in current.items() if k != 'input_fingerprint'})
        for conversion in saved['conversions']:
            for table in conversion['expected_tables']:
                self.assertEqual(set(table), {'table_id'})
                self.assertIn('definition_files', bindings[table['table_id']]['declaration'])
        self.assertEqual(migrate([self.path], apply=True)['manifests'], 0)
        self.assertEqual(original_files, {path.name: manifest.sha_file(path)
                            for path in (self.root/'candidate').glob('*.parquet')})


if __name__ == '__main__':
    unittest.main()
