"""Coverage adapter for the eight recovered Komae FY2019-22 initial-detail chapters.

Called once from coverage_audit with the audit's dataset list (expenditure-only
for Komae: 4 rows). The adapter additionally fetches ALL 8 registered datasets
of this provider from int_fiscal_datasets and appends the missing revenue rows
to the audit list — same pattern as chiyoda2025_native_coverage.

Per dataset it verifies: provenance/origin/table byte SHAs; required binds
(year/direction/provider/grain/unit/phases[]/approval/coordinateStatus/yStatus);
lock-selected snapshot (sha256 of lock bytes); typed bidirectional EXCEPT ALL on
all 47 printed columns for raw<->stg<->int<->mart; recomputed printed kou
(kan+kou composite) and kan controls; phase NULL / approval unconfirmed /
amount-kind NULL; all-column typed mart<->CSV compare (read_csv columns from
mart DESCRIBE, nullstr='' , allow_quoted_nulls=false keeps NULL distinct from
empty string). complete=True only after every check incl. the shared CSV gate.
"""
from __future__ import annotations
from ingestion.inputs import source_metadata_bytes
import hashlib, json
from pathlib import Path

PRINTED_FIELDS = ['source_row','physical_page','y','bbox_json','record_kind','printed_text',
 'kan_code','kan_label','kou_code','kou_label','printed_kan_total','printed_kou_total',
 'moku_code','moku_label','current_text','current_amount','prior_text','prior_amount',
 'change_text','change_amount','natl_text','natl_amount','metro_text','metro_amount',
 'bond_text','bond_amount','other_src_text','other_src_amount','general_text','general_amount',
 'setsu_no','setsu_label','setsu_text','setsu_amount','parent_moku_code','parent_moku_label',
 'parent_moku_source_row','parent_evidence','description','fiscal_year','source_amount_unit',
 'source_url','source_sha256','wayback_url','wayback_capture','dataset_id','fiscal_line_id']
CSV_REL = 'fiscal/132195/initial_detail_recovered.csv'
DATASET_FIELDS = ['dataset_id','jurisdiction_code','fiscal_year','document_kind',
 'origin_sha256','structure_json','source_json','phases_json','line_count','direction']
DATASET_SELECT = 'select ' + ', '.join(DATASET_FIELDS) + ' from int_fiscal_datasets'
PROVIDER = 'ingestion.fiscal.komae_recovered_provider'

def _snapshot_dir(pipeline_dir: Path, lock_bytes: bytes) -> Path:
    snap = hashlib.sha256(lock_bytes).hexdigest()
    root = pipeline_dir / '.cache' / 'inputs' / snap / 'raw'
    if not root.exists():
        raise FileNotFoundError(f'lock-selected snapshot missing: {snap}')
    return root

def _both(connection, a: str, b: str) -> tuple[int, int]:
    fwd = connection.execute(f'select count(*) from (({a}) except all ({b})) x').fetchone()[0]
    rev = connection.execute(f'select count(*) from (({b}) except all ({a})) x').fetchone()[0]
    return fwd, rev

def output_coverage(connection, candidate: Path, hashes: dict, lock_path: Path,
                    datasets: list[dict]) -> None:
    pipeline_dir = Path(lock_path).parents[2]
    lock_bytes = Path(lock_path).read_bytes()
    entries = [e for e in json.loads(lock_bytes)['entries']
               if e['path'].startswith('initial-detail-recovered/')]
    if not entries:
        return
    raw_root = _snapshot_dir(pipeline_dir, lock_bytes)
    csv_path = candidate / CSV_REL
    if CSV_REL not in hashes:
        raise ValueError('CSV not in verified artifacts')
    if hashes[CSV_REL] != hashlib.sha256(csv_path.read_bytes()).hexdigest():
        raise ValueError('CSV sha differs from artifact hash')
    # audit passes only expenditure rows for Komae; fetch the full provider
    # registry from int_fiscal_datasets and append what's missing (e.g. revenue).
    selected = [d for d in datasets
                if json.loads(d.get('source_json') or '{}').get('provider') == PROVIDER]
    seen = {d['dataset_id'] for d in selected}
    registry = {}
    for values in connection.execute(
            DATASET_SELECT + " where json_extract_string(source_json,'$.provider')=?",
            [PROVIDER]).fetchall():
        row = dict(zip(DATASET_FIELDS, values, strict=True))
        registry[row['dataset_id']] = row
        if row['dataset_id'] not in seen:
            datasets.append(row)
            selected.append(row)
    if len(selected) != len(entries):
        raise ValueError(f'registry {len(selected)} != lock {len(entries)} recovered datasets')
    sel = ','.join(f'"{c}"' for c in PRINTED_FIELDS)
    for e in entries:
        identity = ':'.join([e['jurisdiction'], str(e['fiscalYear']), e['direction'],
                             e['documentKind'], e['originEdition'], e['path'].split('resource=')[-1]])
        # bind to the actual caller/registry row object inside `datasets`
        dataset = next((d for d in datasets if d.get('dataset_id') == identity), None)
        if dataset is None:
            raise ValueError(f'recovered dataset missing from int_fiscal_datasets: {identity}')
        reg = registry.get(identity)
        if reg:
            for k in DATASET_FIELDS:
                dataset.setdefault(k, reg[k])
        proof = dict(complete=False, files=[], errors=[])
        dataset['output_coverage'] = proof
        try:
            sj_raw = dataset.get('source_json')
            if not sj_raw: raise ValueError('source_json empty')
            sj = json.loads(sj_raw)
            prov = json.loads(source_metadata_bytes(lock_path, e))
            binds = [('fiscal_year', prov['fiscal_year'], e['fiscalYear']),
                     ('direction', prov['direction'], e['direction']),
                     ('provider', sj.get('provider'), PROVIDER),
                     ('grain', sj.get('grain'), prov.get('grain')),
                     ('unit', sj.get('sourceAmountUnit'), prov.get('source_amount_unit')),
                     ('phases', sj.get('phases'), []),
                     ('phases_json', dataset.get('phases_json'), '[]'),
                     ('line_count', dataset.get('line_count'), prov.get('rows')),
                     ('approval', sj.get('approvalStatus'), 'unconfirmed'),
                     ('coordinateStatus', sj.get('coordinateStatus'),
                      'x-estimate-only: bbox_json carries x-bounds; y/height are synthetic row bounds, not measured'),
                     ('yStatus', sj.get('yStatus'), 'unobserved-null')]
            for name, got, want in binds:
                if got != want: raise ValueError(f'{name} bind: {got!r} != {want!r}')
            if sj.get('sourceAmountKind') is not None or prov.get('source_amount_kind') is not None:
                raise ValueError('amount-kind NULL guard failed')
            if sj.get('additive') is not False or prov.get('additive') is not False:
                raise ValueError('additive guard failed')
            origin = pipeline_dir/'.cache/objects'/e['origin']['object']['key']
            if hashlib.sha256(origin.read_bytes()).hexdigest() != e['origin']['object']['sha256']:
                raise ValueError('origin bytes differ')
            pq = raw_root/e['path']/'data.parquet'
            if hashlib.sha256(pq.read_bytes()).hexdigest() != e['table']['sha256']:
                raise ValueError('table bytes differ')
            raw_q = f"select {sel} from '{pq}'"
            where = f"where dataset_id='{identity}'"
            for layer, ref in (('stg','main.stg_132195__initial_detail_recovered'),
                               ('int','main.int_132195_initial_detail_recovered'),
                               ('mart','main.fiscal_132195_initial_detail_recovered_lines')):
                fwd, rev = _both(connection,
                    f"select {sel} from ({raw_q}) r",
                    f"select {sel} from (select * from {ref} {where}) l")
                if fwd or rev: raise ValueError(f'{layer}: {fwd}/{rev} diffs')
            bad = connection.execute(
                f"select count(*) from (select kan_code,kou_code,max(printed_kou_total) t,"
                f" sum(current_amount) s from ({raw_q}) m where record_kind='moku'"
                f" group by kan_code,kou_code) v where t<>s").fetchone()[0]
            bad += connection.execute(
                f"select count(*) from (select kan_code,max(printed_kan_total) t,"
                f" sum(printed_kou_total) s from ({raw_q}) m where record_kind='kou_header'"
                f" group by kan_code) v where t<>s").fetchone()[0]
            if bad: raise ValueError(f'printed controls do not recompute: {bad}')
            nn = connection.execute(
                f"select count(phase), count(*) filter (approval_status<>'unconfirmed')"
                f" from main.fiscal_132195_initial_detail_recovered_lines {where}").fetchone()
            if nn != (0, 0): raise ValueError('phase/approval guard failed')
            proof['files'] = [e['path']+'/data.parquet', CSV_REL]
        except Exception as exc:
            proof['errors'].append(str(exc))
    mcols = [(c[0], c[1]) for c in connection.execute(
        'describe main.fiscal_132195_initial_detail_recovered_lines').fetchall()]
    cols_spec = '{' + ','.join(f"'{c}': '{t}'" for c, t in mcols) + '}'
    msel = ','.join(f'"{c}"' for c, _ in mcols)
    try:
        fwd, rev = _both(connection,
            f'select {msel} from main.fiscal_132195_initial_detail_recovered_lines',
            f"select {msel} from read_csv('{csv_path}', header=true, columns={cols_spec},"
            " nullstr='', allow_quoted_nulls=false)")
        if fwd or rev: raise ValueError(f'CSV<->mart diffs: {fwd}/{rev}')
    except Exception as exc:
        for d in selected:
            if 'output_coverage' in d:
                d['output_coverage']['errors'].append(f'csv: {exc}')
    for d in selected:
        if 'output_coverage' in d:
            d['output_coverage']['complete'] = not d['output_coverage']['errors']
