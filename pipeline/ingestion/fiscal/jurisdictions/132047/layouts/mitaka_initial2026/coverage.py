"""Normal five-argument observation coverage, schema3 only; no sidecar results."""
import csv, hashlib, json
from pathlib import Path
from .registration import (NAMESPACE, SOURCE_KEY, TABLE_ID, DATASET_ID, INPUT_PATH,
    ORIGIN_SHA, RAW_SHA, ROWS, F25, RAW_SCHEMA, CSV_SCHEMA, metadata, dataset_record)

FIELDS = ['dataset_id','jurisdiction_code','fiscal_year','direction','document_kind',
          'origin_sha256','phases_json','line_count','source_json','structure_json']
LAYERS = ['stg_mitaka_initial2026','int_mitaka_initial2026','mart_mitaka_initial2026']
CSV_REL = 'fiscal/132047/mitaka_initial2026_observation.csv'
REGISTRY_SCHEMA = [(name, 'BIGINT' if name == 'fiscal_year' else
                    'BIGINT' if name == 'line_count' else 'VARCHAR') for name in FIELDS]


def _describe(connection, query, args=()):
    return [(r[0], r[1]) for r in connection.execute('describe ' + query, list(args)).fetchall()]


def _diff(connection, left, left_args, right, right_args):
    return [connection.execute('select count(*) from (' + a + ' except all ' + b + ')', [*aa, *bb]).fetchone()[0]
            for a, aa, b, bb in [(left, left_args, right, right_args), (right, right_args, left, left_args)]]


def _record_equal(left, right, keys=FIELDS):
    return all(json.loads(left[k]) == json.loads(right[k]) if k in ('source_json','structure_json')
               else left[k] == right[k] for k in keys)


def _guard_rows(connection, query, args):
    bad = connection.execute('select count(*) from (' + query + ') q where '
        'source_key is distinct from ? or fiscal_year is distinct from ? or document_kind is distinct from ? '
        'or page is null or line is null or row_type is null or phase is not null '
        'or json_extract_string(amount_semantics,\'$.monetary_column_roles\') is distinct from ? '
        'or json_extract_string(amount_semantics,\'$.unit_conversion_applied\') is distinct from ? '
        'or json_extract_string(col_context,\'$.column_roles_status\') is distinct from ?',
        [*args, SOURCE_KEY, '2026', 'budget', 'unconfirmed', 'false',
         'printed headers retained; cell/year/role linkage unconfirmed']).fetchone()[0]
    if bad:
        raise ValueError('Observation key/edition/phase/cell-role guard failed')
    duplicates = connection.execute('select count(*) from (select source_key,page,line,row_type,count(*) n '
        'from (' + query + ') group by all having n<>1)', list(args)).fetchone()[0]
    if duplicates or connection.execute('select count(*) from (' + query + ')', list(args)).fetchone()[0] != ROWS:
        raise ValueError('Observation row identity/count changed')


def output_coverage(connection, candidate, hashes, lock_path, datasets):
    from ingestion.inputs import read_lock, OBJECTS, safe_relative, verify_object
    entries = [e for e in read_lock(lock_path)['entries'] if e['path'].startswith(NAMESPACE + '/')]
    if not entries:
        return
    if len(entries) != 1 or entries[0]['path'] != INPUT_PATH:
        raise ValueError('Coverage requires one exact schema3 Mitaka input')
    entry = entries[0]
    value = metadata(lock_path, entry)
    expected = dataset_record(value)
    callers = [row for row in datasets if row['dataset_id'] == DATASET_ID]
    if len(callers) > 1:
        raise ValueError('Duplicate Mitaka caller dataset')
    row = callers[0] if callers else dict(expected)
    if not callers:
        datasets.append(row)
    proof = dict(complete=False, files=[], errors=[], accounts={}, original_rows=0,
        recognition_status='unconfirmed', legal_correspondence_status='unconfirmed',
        phase=None, approval_status='unconfirmed', nonadditive=True)
    row['output_coverage'] = proof
    try:
        if not _record_equal(row, expected):
            raise ValueError('Caller changed dataset metadata or phase')
        query = 'select ' + ','.join(FIELDS) + " from int_fiscal_datasets where dataset_id=? or json_extract_string(source_json,'$.provider')=?"
        if _describe(connection, query, [DATASET_ID, NAMESPACE]) != REGISTRY_SCHEMA:
            raise ValueError('Registry names/types/order differ')
        registered = connection.execute(query, [DATASET_ID, NAMESPACE]).fetchall()
        if len(registered) != 1 or not _record_equal(dict(zip(FIELDS, registered[0], strict=True)), expected):
            raise ValueError('int_fiscal_datasets must contain exact one observation row')
        common_keys = [k for k in FIELDS if k != 'phases_json']
        common_query = 'select ' + ','.join(common_keys) + ',source_amount_kind from fiscal_datasets where dataset_id=?'
        if _describe(connection, common_query, [DATASET_ID]) != [s for s in REGISTRY_SCHEMA if s[0]!='phases_json'] + [('source_amount_kind','VARCHAR')]:
            raise ValueError('Common mart names/types/order differ')
        common = connection.execute(common_query, [DATASET_ID]).fetchall()
        if len(common) != 1 or common[0][-1] is not None or not _record_equal(dict(zip(common_keys, common[0][:-1], strict=True)), expected, common_keys):
            raise ValueError('Common mart must preserve metadata and NULL source_amount_kind exactly once')
        # This dataset must not acquire generic financial-line or amount rows.
        if connection.execute('select count(*) from int_fiscal_lines where dataset_id=?', [DATASET_ID]).fetchone()[0]:
            raise ValueError('Observation leaked into generic fiscal lines')
        if connection.execute('select count(*) from int_fiscal_amounts a join int_fiscal_lines l using(fiscal_line_id) '
                'where l.dataset_id=?', [DATASET_ID]).fetchone()[0]:
            raise ValueError('Observation leaked into generic fiscal amounts')
        for ref in [entry['origin']['object'], entry['table']]:
            verify_object(ref, (OBJECTS / safe_relative(ref['key'])).read_bytes())
        raw = str(OBJECTS / safe_relative(entry['table']['key']))
        projection = ','.join('"' + name + '"' for name in F25)
        raw_query = 'select ' + projection + ' from read_parquet(?,hive_partitioning=false)'
        raw_args = [raw]
        if _describe(connection, raw_query, raw_args) != RAW_SCHEMA:
            raise ValueError('Required physical25 raw names/types/order differ')
        _guard_rows(connection, raw_query, raw_args)
        unknown, unlinked = connection.execute("select count(*) filter(where json_extract_string(t.value,'$.class')='unknown'), "
            "count(*) filter(where json_extract_string(t.value,'$.basis')='printed-monetary-table-context') "
            "from read_parquet(?,hive_partitioning=false) r, json_each(r.amount_semantics,'$.token_classes') t", [raw]).fetchone()
        if (unknown, unlinked) != (1047, 1112):
            raise ValueError('Unconfirmed numeric observation boundaries changed')
        proof['unconfirmed_numeric_tokens'] = unknown
        proof['cell_year_role_unconfirmed_tokens'] = unlinked
        for layer in LAYERS:
            shape = CSV_SCHEMA if layer == LAYERS[-1] else RAW_SCHEMA
            if _describe(connection, 'select * from ' + layer) != shape:
                raise ValueError('Layer exact schema differs: ' + layer)
            layer_query = 'select ' + projection + ' from ' + layer
            _guard_rows(connection, layer_query, [])
            if _diff(connection, raw_query, raw_args, layer_query, []) != [0, 0]:
                raise ValueError('All-field typed multiset differs: ' + layer)
        if connection.execute("select count(*) from mart_mitaka_initial2026 where jurisdiction_code is distinct from '132047'").fetchone()[0]:
            raise ValueError('Added jurisdiction column differs')
        if CSV_REL not in hashes:
            raise ValueError('Verified CSV artifact missing')
        csv_path = Path(candidate) / safe_relative(CSV_REL)
        if hashlib.sha256(csv_path.read_bytes()).hexdigest() != hashes[CSV_REL]:
            raise ValueError('CSV bytes differ from verified inventory')
        with csv_path.open(newline='', encoding='utf-8') as stream:
            if next(csv.reader(stream)) != [name for name, _ in CSV_SCHEMA]:
                raise ValueError('CSV26 header/order differs')
        types = '{' + ','.join("'" + name + "':'" + typ + "'" for name, typ in CSV_SCHEMA) + '}'
        csv_query = 'select * from read_csv(?,header=true,auto_detect=false,columns=' + types + ",allow_quoted_nulls=false,nullstr='')"
        if _describe(connection, csv_query, [str(csv_path)]) != CSV_SCHEMA:
            raise ValueError('CSV26 physical types differ')
        if _diff(connection, 'select * from mart_mitaka_initial2026', [], csv_query, [str(csv_path)]) != [0, 0]:
            raise ValueError('CSV26 typed multiset differs from mart')
        proof.update(complete=True, files=[CSV_REL], original_rows=value['rows'],
            all_original_fields_preserved=True, schema_columns=25, csv_columns=26,
            phase_all_null=True, duplicate_identity_surplus=0)
    except Exception as error:
        proof['errors'].append(str(error))
