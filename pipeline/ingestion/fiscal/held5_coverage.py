"""Whole original observations and typed outputs for the five held Komae editions."""
from ingestion.inputs import source_metadata_bytes
import hashlib
import json
from pathlib import Path
import duckdb

NAMESPACE = 'held5-council-approved-detail'


def output_coverage(connection, candidate, hashes, lock_path, datasets):
    from ingestion.inputs import OBJECTS, read_lock, safe_relative, verify_object

    entries = [e for e in read_lock(lock_path)['entries'] if e['path'].startswith(NAMESPACE + '/')]
    if not entries:
        return
    from ingestion.fiscal.held5_council_provider import Held5Runtime
    from ingestion.fiscal.decode_komae_held5_observations import parse

    registered = {d['dataset_id']:d for d in datasets}
    runtime = None
    setup_error = None
    try:
        runtime = Held5Runtime()
        specs = {c['source_key']:c for c in runtime.candidates}
        if len(entries) != 5 or len(specs) != 5:
            raise ValueError('Exact five adopted held editions required')
    except (OSError, ValueError, KeyError, TypeError) as error:
        setup_error = error

    def model_rows(model, identity, columns=None):
        if columns is None:
            cursor = connection.execute(f'SELECT * FROM {model} WHERE dataset_id=?', [identity])
            columns = [c[0] for c in cursor.description]
            return columns, cursor.fetchall()
        projection = ','.join('"'+c.replace('"','""')+'"' for c in columns)
        return connection.execute(f'SELECT {projection} FROM {model} WHERE dataset_id=? ORDER BY source_row', [identity]).fetchall()

    def typed_csv(relative, model, identity):
        if relative not in hashes:
            raise ValueError('Held output CSV is not a hash-verified build artifact: '+relative)
        columns, expected = model_rows(model, identity)
        schema = [(r[0],r[1]) for r in connection.execute(f'DESCRIBE SELECT * FROM {model}').fetchall()]
        values = connection.execute("SELECT * FROM read_csv(?,columns=?,header=true,hive_partitioning=false,nullstr='',allow_quoted_nulls=false) WHERE dataset_id=?",
                                    [str(candidate / relative),dict(schema),identity]).fetchall()
        if sorted(values, key=str) != sorted(expected, key=str):
            raise ValueError('Held typed CSV differs in original fields/NULLs: '+relative)
        return columns, values

    for entry in entries:
        table = next(p.split('=',1)[1] for p in entry['path'].split('/') if p.startswith('table='))
        identity = ':'.join([entry['jurisdiction'],str(entry['fiscalYear']),entry['direction'],entry['documentKind'],entry['originEdition'],table])
        dataset = registered.get(identity)
        if dataset is None:
            dataset = dict(dataset_id=identity, jurisdiction_code=entry['jurisdiction'],fiscal_year=entry['fiscalYear'],
                           document_kind=entry['documentKind'],origin_sha256=entry['originEdition'],source_json='{}',
                           structure_json='{"funds":[]}',line_count=0,phases_json='[]',_phase_lines={},
                           output_coverage=dict(complete=False,files=[],accounts={},errors=[]))
            datasets.append(dataset)
        proof = dataset['output_coverage']
        try:
            if setup_error is not None:
                raise ValueError(str(setup_error))
            if identity not in registered or not proof['complete']:
                raise ValueError('Held edition has no current verified registered phase output')
            provenance = json.loads(source_metadata_bytes(lock_path, entry))
            spec = specs[provenance['source_key']]
            result = runtime.verify_result(spec, parse(spec,runtime))
            original = result['rows']
            raw_path = OBJECTS / safe_relative(entry['table']['key'])
            verify_object(entry['table'],raw_path.read_bytes())
            cursor = connection.execute('SELECT * FROM read_parquet(?,hive_partitioning=false) ORDER BY source_row',[str(raw_path)])
            columns = [c[0] for c in cursor.description]
            raw_values = cursor.fetchall()
            if (raw_values != [tuple(row[c] for c in columns) for row in original]
                    or len(raw_values) != provenance['rows'] or len(raw_values) != dataset['line_count']
                    or len(columns) != 52):
                raise ValueError('Held raw table differs from full original observation replay')
            for model in ['stg_132195__held5_council_approved_detail','int_132195_held5_council_expenditure_changes']:
                if model_rows(model,identity,columns) != raw_values:
                    raise ValueError('Held original fields or row population differ: '+model)
            source = json.loads(dataset['source_json'])
            approval = {**spec['approval_proof'],'original_identity_evidence':[
                e for e in spec['approval_proof']['original_identity_evidence']
                if '上記の議案' in e['observed_text'] or '地方自治法' in e['observed_text']]}
            expected = dict(url=spec['url'],sha256=entry['originEdition'],tableId=spec['table_id'],
                            observationRole='authoritative-held5-council-supplementary-detail',canonicalChanges=True,
                            sourceAmountUnit='千円',unitMultiplier=1000,approvalProof=approval,
                            approvalDate=provenance['council_resolution_date'],councilResolutionDate=provenance['council_resolution_date'],
                            printedSubmissionDate=provenance['printed_submission_date'],effectiveDate=None,
                            executiveDispositionDate=None,independentControls=result['totals'],
                            
                            rawTableSha256=entry['table']['sha256'],reserveExceptionRows=provenance['reserve_null_rows'])
            if (any(source.get(k) != value for k,value in expected.items())
                    or provenance['totals'] != result['totals'] or provenance['approval_proof'] != approval
                    or entry['fiscalYear'] != spec['fiscal_year'] or entry['originEdition'] != spec['expected_sha256']
                    or provenance['source_page_range'] != result['source_page_range']):
                raise ValueError('Held whole scope/metadata/independent original controls differ')
            models = [('fiscal/132195/held5_raw_detail.csv','csv_132195_held5_raw_detail'),
                      ('fiscal/132195/expenditure_budget_changes.csv','fiscal_132195_held5_council_expenditure_budget_changes')]
            for relative,model in models:
                if model.startswith('csv_'):
                    typed_csv(relative,model,identity)
                else:
                    # The shared CSV is a strict superset of the finite held model.
                    columns_mart,values = typed_csv(relative,model,identity)
                    change_rows = [dict(zip(columns_mart,row,strict=True)) for row in values]
            raw_by_row = {r['source_row']:r for r in original}
            if len(change_rows) != len(raw_by_row):
                raise ValueError('Held change rows repeat or omit original rows')
            for row in change_rows:
                raw = raw_by_row[row['source_row']]
                detail = json.loads(row['details_json'])
                line_id = identity+':'+str(raw['source_row'])
                if (len(detail) != 1 or detail[0]['rawSource'] != raw
                        or detail[0]['fiscalLineId'] != line_id
                        or row['change_id'] != 'c-'+hashlib.sha256(line_id.encode()).hexdigest()
                        or row['amount_delta'] != raw['amount_delta']*1000
                        or row['effective_at'] is not None or row['sequence'] != spec['amendment_number']):
                    raise ValueError('Held change original JSON/amount/date/identity differs')
            invalid_legal = connection.execute('''SELECT count(*) FROM int_132195_held5_council_expenditure_changes c
                LEFT JOIN fiscal_expenditure_setsu_master m ON c.expenditure_setsu_id=m.expenditure_setsu_id
                WHERE c.dataset_id=? AND ((c.setsu_code IS NOT NULL AND
                 (m.expenditure_setsu_id IS NULL OR try_cast(m.code AS integer)<>try_cast(c.setsu_code AS integer)
                  OR m.label<>c.full_legal_setsu_label OR c.fiscal_year<coalesce(m.valid_from_fiscal_year,-9999)
                  OR c.fiscal_year>coalesce(m.valid_to_fiscal_year,9999))) OR
                 (c.setsu_code IS NULL AND (c.expenditure_setsu_id IS NOT NULL OR c.moku_label<>'予備費')))''',[identity]).fetchone()[0]
            if invalid_legal:
                raise ValueError('Held printed code/full legal name/active year or reserve NULL differs')
            invalid_target = connection.execute('''SELECT count(*) FROM int_132195_held5_council_expenditure_changes c
                LEFT JOIN int_132195_initial_detail i ON c.target_identity_json=i.supplementary_compatibility_identity_json
                LEFT JOIN (
                 SELECT target_identity_json,budget_item_id,fiscal_line_id FROM int_supplementary_expenditure_changes
                 UNION ALL SELECT target_identity_json,budget_item_id,fiscal_line_id FROM int_132195_council_expenditure_changes
                 UNION ALL SELECT target_identity_json,budget_item_id,fiscal_line_id FROM int_132195_native_council_expenditure_changes
                ) e ON c.exact_existing_fiscal_line_id=e.fiscal_line_id
                WHERE c.dataset_id=? AND
                 ((i.fiscal_line_id IS NOT NULL AND (c.budget_item_id<>i.budget_item_id
                    OR c.exact_initial_fiscal_line_id IS DISTINCT FROM i.fiscal_line_id OR c.initial_state<>'recorded'))
                 OR (i.fiscal_line_id IS NULL AND (c.exact_initial_fiscal_line_id IS NOT NULL OR c.initial_state<>'unconfirmed'
                    OR (c.exact_existing_fiscal_line_id IS NOT NULL AND (e.fiscal_line_id IS NULL
                       OR c.target_identity_json<>e.target_identity_json OR c.budget_item_id<>e.budget_item_id
                       OR c.exact_existing_target_identity_json IS DISTINCT FROM e.target_identity_json))
                    OR (c.exact_existing_fiscal_line_id IS NULL AND (c.budget_item_id<>c.native_namespace_budget_item_id
                       OR c.exact_existing_target_identity_json IS NOT NULL)))))''',[identity]).fetchone()[0]
            if invalid_target:
                raise ValueError('Held target equivalence is not exact complete original identity')
            provided = connection.execute("SELECT * FROM read_csv(?,columns=?,header=true,hive_partitioning=false,nullstr='',allow_quoted_nulls=false)",
                [str(candidate/'fiscal/132195/expenditure_budget_items.csv'),dict((r[0],r[1]) for r in connection.execute('DESCRIBE SELECT * FROM fiscal_expenditure_budget_items').fetchall())]).fetchall()
            all_columns = [r[0] for r in connection.execute('DESCRIBE SELECT * FROM fiscal_expenditure_budget_items').fetchall()]
            ids = {row['budget_item_id'] for row in change_rows}
            idx = all_columns.index('budget_item_id')
            actual_items = [row for row in provided if row[idx] in ids]
            expected_items = connection.execute('SELECT * FROM fiscal_expenditure_budget_items WHERE budget_item_id IN (SELECT budget_item_id FROM int_132195_held5_council_expenditure_changes WHERE dataset_id=?)',[identity]).fetchall()
            if ('fiscal/132195/expenditure_budget_items.csv' not in hashes
                    or sorted(actual_items,key=str) != sorted(expected_items,key=str)):
                raise ValueError('Held target CSV differs in typed fields or NULL baseline')
            proof['files'] = sorted(set(proof['files'] + [r for r,_ in models]+['fiscal/132195/expenditure_budget_items.csv']))
            proof.update(raw_fields_model='int_132195_held5_council_expenditure_changes',raw_original_rows=len(original),
                         raw_original_columns=len(columns),fixed_input=entry['path'],whole_attachment_pages=len(range(spec['first_page'],spec['last_page']+1)),
                         independent_controls=result['totals'],immutable_evidence_objects=len(runtime.inputs))
        except (OSError,ValueError,KeyError,TypeError,StopIteration,duckdb.Error) as error:
            proof['complete'] = False
            proof['errors'].append(str(error))
