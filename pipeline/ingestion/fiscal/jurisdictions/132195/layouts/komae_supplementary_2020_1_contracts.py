"""Schema3 declarations and regenerated metadata guards; no import-time IO.

Installed code is checked by declaration definition_files. Lock and run results
are excluded from that definition set, so its seals are acyclic.
"""
from __future__ import annotations
import hashlib, json, os, re, stat, tomllib
from pathlib import Path, PurePosixPath

PROVIDER='ingestion.fiscal.jurisdictions.132195.layouts.komae_supplementary_2020_1_provider'
NS='komae-supplementary-2020-1/'
FISCAL='pipeline/ingestion/fiscal/jurisdictions/132195/layouts/'
ORIGIN='55b99cec58e42222cfdd93d59821ab92d25464f23f2fcead40d0e19a3f17492a'
ORIGIN_BYTES=471659
CONFIG=Path(__file__).with_name('sources-supplementary-2020-1.toml')
AMOUNT_ROLE='authoritative-supplementary-council-book'
APPROVAL_BASIS='physical1「計数整理中」、physical3「令和２年４月２８日 専決」。専決の原典観測だけで議会承認や金額phaseは確定しない'

def require(ok,message):
    if not ok:raise ValueError(message)

def same_typed(value,want):
    if type(value) is not type(want):return False
    if isinstance(want,dict):return set(value)==set(want) and all(same_typed(value[k],v) for k,v in want.items())
    if isinstance(want,list):return len(value)==len(want) and all(same_typed(a,b) for a,b in zip(value,want,strict=True))
    return value==want

def checked_bytes(path):
    p=Path(path).absolute();require('..' not in p.parts,'absolute traversal')
    directory=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in p.parts[1:-1]:
            nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
            os.close(directory);directory=nxt
        fd=os.open(p.name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory)
        try:
            before=os.fstat(fd);require(stat.S_ISREG(before.st_mode),'regular file required')
            parts=[]
            while body:=os.read(fd,65536):parts.append(body)
            after=os.fstat(fd);now=os.stat(p.name,dir_fd=directory,follow_symlinks=False)
            ident=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
            require(ident(before)==ident(after)==ident(now),'resource changed while reading')
            return b''.join(parts)
        finally:os.close(fd)
    finally:os.close(directory)

def verified_bytes(path,pin):
    require(set(pin)=={'sha256','bytes'} and type(pin['bytes']) is int and pin['bytes']>=0
            and type(pin['sha256']) is str and re.fullmatch('[a-f0-9]{64}',pin['sha256']),'SHA+bytes pin')
    body=checked_bytes(path)
    require(len(body)==pin['bytes'] and hashlib.sha256(body).hexdigest()==pin['sha256'],'resource seal differs: '+str(path))
    return body

def repo_root():
    from ingestion.paths import REPO
    return REPO

def load(path=CONFIG):
    specs=tomllib.loads(checked_bytes(path).decode('utf-8'))
    require(set(specs)=={'general-1-expenditure','general-1-revenue'},'exact two specifications')
    for d in ('expenditure','revenue'):
        s=specs['general-1-'+d]
        for name,want in dict(fiscal_year=2020,direction=d,fund_label='一般会計',
            table_id='saiin-saishutsu-hosei-1-'+d,expected_sha256=ORIGIN,
            expected_table_sha256=FACTS[d]['sha256'],expected_rows=FACTS[d]['rows'],
            expected_table_bytes=FACTS[d]['bytes']).items():
            require(name in s and same_typed(s[name],want),'typed specification '+name)
    return specs

def input_path(spec):
    return (NS+'jurisdiction=132195/year=2020/document_kind=supplementary/edition='+ORIGIN+
            '/direction='+spec['direction']+'/resource='+spec['table_id'])

def dataset_id(spec):
    return '132195:2020:'+spec['direction']+':supplementary:'+ORIGIN+':'+spec['table_id']

def declaration(spec,definitions):
    return dict(source_key='komae-suppl-2020-1:general-1-'+spec['direction'],
        request_url=spec['original_url'],original_url=spec['original_url'],
        document_title=spec['document_title'],document_label=spec['document_title'],
        landing_page=spec['landing_page'],url_basis=spec['url_basis'],
        table_id=spec['table_id'],observation_role=AMOUNT_ROLE,
        grain='kan+kou+moku+setsu+context',pages=13,raw_form='extracted',
        fund_label='一般会計',account='一般会計',amendment_number=1,
        source_amount_unit='千円',unit_multiplier=1000,source_amount_kind=None,
        phase=None,phases=[],approval_status='unconfirmed',approval_evidence=APPROVAL_BASIS,
        recognition_status='unconfirmed',legal_correspondence_status='unconfirmed',
        project_setsu_linkage='unconfirmed',additive=False,additive_within_own_grain=False,
        canonical_changes=False,canonical_initial=False,canonical_executed=False,
        executive_disposition_date='2020-04-28',effective_at=None,
        effective_at_basis='金額phaseの有効日・議会承認は原典内では確定しない',
        nonadditive_reason='科目・節・総括・control・contextが混在する補正資料の観測。事業×節へ推論しない',
        source_grain='kan+kou+moku+setsu+context',source_position_method='pdftotext -layout/native lane',
        original_observation_identity=dict(physical_pages=13,title_page=1,disposition_page=3,
            printed_title_status='計数整理中',printed_disposition='令和２年４月２８日 専決'),
        redistribute=spec['redistribute'],redistribute_basis=spec['redistribute_basis'],
        license_id=spec['license_id'],attribution=spec['attribution'],definition_files=definitions)

def verify_definitions(definitions,root=None):
    root=Path(root) if root is not None else repo_root()
    require(type(definitions) is dict and set(definitions)==set(DEFINITION_PATHS),'exact definition roots')
    for name,ref in definitions.items():
        p=PurePosixPath(name)
        require(name==str(p) and not p.is_absolute() and '..' not in p.parts
                and set(ref)=={'path','sha256','bytes'} and ref['path']==name,'installed definition identity')
        require(not name.endswith('sources.lock.json') and '/provenance/' not in name
                and not any(part in ('.agent','.cache','.build','objects') for part in p.parts),'definition cycle/corpus member')
        verified_bytes(root/name,{k:ref[k] for k in ('sha256','bytes')})

def validate_entry(entry,spec,verify=True):
    from ingestion.inputs import SOURCE_FIELDS
    d=spec['direction'];facts=FACTS[d]
    want=dict(path=input_path(spec),jurisdiction='132195',fiscalYear=2020,
        documentKind='supplementary',direction=d,originEdition=ORIGIN,
        origin=dict(availability='stored',sha256=ORIGIN,
                    object=dict(key='inputs/origin/sha256/'+ORIGIN,sha256=ORIGIN,bytes=ORIGIN_BYTES)),
        table=dict(key='inputs/table/sha256/'+facts['sha256'],sha256=facts['sha256'],bytes=facts['bytes']))
    require(set(entry)==set(want)|{'source'},'schema3 target entry exact keys; no sidecars')
    require(same_typed({k:entry[k] for k in want},want),'typed object/dataset/path identity')
    source=entry['source'];require(type(source) is dict and not set(source)-SOURCE_FIELDS,'declarations only')
    require('definition_files' in source,'definition declarations required')
    require(same_typed(source,declaration(spec,source['definition_files'])),'exact source declaration')
    if verify:verify_definitions(source['definition_files'])
    return dataset_id(spec)

def validate_generated(entry,spec,metadata):
    # source_metadata is generated from immutable original/table, never persisted in the lock.
    validate_entry(entry,spec)
    d=spec['direction'];facts=FACTS[d]
    for name,value in entry['source'].items():
        require(name in metadata and same_typed(metadata[name],value),'regenerated declaration '+name)
    wanted=dict(rows=facts['rows'],raw_schema=[dict(name=n,type=t) for n,t in RAW_SCHEMA],
        header=[n for n,t in RAW_SCHEMA],jurisdiction_code='132195',fiscal_year=2020,
        direction=d,document_kind='supplementary',origin_sha256=ORIGIN,origin_bytes=ORIGIN_BYTES,
        raw_table_sha256=facts['sha256'],raw_table_bytes=facts['bytes'],sha256=ORIGIN,
        bytes=ORIGIN_BYTES,input_hashes_verified=True,reserve_rows=NULL_COUNTS[d]['setsu_code'],
        reserve_null_rows=NULL_COUNTS[d]['setsu_code'],printed_zero_rows=0,
        extraction_evidence=dict(reserve_exception_rows=NULL_COUNTS[d]['setsu_code']))
    for name,value in wanted.items():
        require(name in metadata and same_typed(metadata[name],value),'generated metadata '+name)
    require(type(metadata.get('schema')) is list and len(metadata['schema'])==22,'generated physical22 schema')
    require([[r[0],r[1],r[2]] for r in metadata['schema']]==[[n,t,'YES'] for n,t in RAW_SCHEMA],
            'generated ordered types/nullability')
    return metadata

RAW_SCHEMA = [['source_row', 'BIGINT'], ['kind', 'VARCHAR'], ['direction', 'VARCHAR'], ['kan_code', 'VARCHAR'], ['kou_code', 'VARCHAR'], ['moku_code', 'VARCHAR'], ['moku_label', 'VARCHAR'], ['setsu_code', 'VARCHAR'], ['setsu_label', 'VARCHAR'], ['setsu_level', 'VARCHAR'], ['setsu_x', 'BIGINT'], ['block_id', 'VARCHAR'], ['before_amt', 'BIGINT'], ['delta', 'BIGINT'], ['total', 'BIGINT'], ['natl', 'BIGINT'], ['metro', 'BIGINT'], ['bond', 'BIGINT'], ['other', 'BIGINT'], ['general', 'BIGINT'], ['physical_page', 'BIGINT'], ['raw_text', 'VARCHAR']]
FACTS = {'expenditure': {'sha256': 'a3d334e638c43d472ccfa43a47d3ff67aacc21acad51a015846be98c3ba77c68', 'bytes': 13068, 'rows': 291}, 'revenue': {'sha256': 'a0ce026498e70e919079136261411c1eab50598aa57d7c9c882a540f234b58ef', 'bytes': 8287, 'rows': 100}}
NULL_COUNTS = {'expenditure': {'source_row': 0, 'kind': 0, 'direction': 49, 'kan_code': 66, 'kou_code': 109, 'moku_code': 135, 'moku_label': 285, 'setsu_code': 260, 'setsu_label': 260, 'setsu_level': 260, 'setsu_x': 201, 'block_id': 195, 'before_amt': 263, 'delta': 232, 'total': 263, 'natl': 282, 'metro': 284, 'bond': 286, 'other': 286, 'general': 276, 'physical_page': 0, 'raw_text': 0}, 'revenue': {'source_row': 0, 'kind': 0, 'direction': 49, 'kan_code': 51, 'kou_code': 66, 'moku_code': 79, 'moku_label': 96, 'setsu_code': 95, 'setsu_label': 95, 'setsu_level': 95, 'setsu_x': 90, 'block_id': 86, 'before_amt': 82, 'delta': 77, 'total': 82, 'natl': 100, 'metro': 100, 'bond': 100, 'other': 100, 'general': 100, 'physical_page': 0, 'raw_text': 0}}
DEFINITION_PATHS = ('packages/jurisdictions/jurisdictions.json', 'pipeline/dbt/dbt_project.yml', 'pipeline/dbt/macros/fiscal_csv.sql', 'pipeline/dbt/macros/fiscal_units.sql', 'pipeline/dbt/models/intermediate/fiscal/records/int_132195_supplementary_2020_1_expenditure.sql', 'pipeline/dbt/models/intermediate/fiscal/records/int_132195_supplementary_2020_1_revenue.sql', 'pipeline/dbt/models/intermediate/fiscal/records/int_fiscal_datasets.sql', 'pipeline/dbt/models/marts/csv/csv_132195_supplementary_2020_1_expenditure.sql', 'pipeline/dbt/models/marts/csv/csv_132195_supplementary_2020_1_revenue.sql', 'pipeline/dbt/models/marts/records/fiscal_132195_supplementary_2020_1_expenditure_lines.sql', 'pipeline/dbt/models/marts/records/fiscal_132195_supplementary_2020_1_revenue_lines.sql', 'pipeline/dbt/models/marts/records/fiscal_datasets.sql', 'pipeline/dbt/models/staging/fiscal/_komae_supplementary_2020_1_sources.yml', 'pipeline/dbt/models/staging/fiscal/stg_132195__supplementary_2020_1_expenditure.sql', 'pipeline/dbt/models/staging/fiscal/stg_132195__supplementary_2020_1_revenue.sql', 'pipeline/dbt/profiles.yml', 'pipeline/ingestion/__init__.py', 'pipeline/ingestion/declarations.py', 'pipeline/ingestion/fiscal/__init__.py', 'pipeline/ingestion/fiscal/jurisdictions/132195/layouts/extract_komae_supplementary_2020_1.py', 'pipeline/ingestion/fiscal/jurisdictions/132195/layouts/extract_komae_supplementary_2020_1_candidate.py', 'pipeline/ingestion/fiscal/jurisdictions/132195/layouts/extract_komae_supplementary_2020_1_lanes.py', 'pipeline/ingestion/fiscal/jurisdictions/132195/layouts/held5-runtime-manifest.json', 'pipeline/ingestion/fiscal/jurisdictions/132195/layouts/komae_supplementary_2020_1_contracts.py', 'pipeline/ingestion/fiscal/jurisdictions/132195/layouts/komae_supplementary_2020_1_coverage.py', 'pipeline/ingestion/fiscal/jurisdictions/132195/layouts/komae_supplementary_2020_1_provider.py', 'pipeline/ingestion/fiscal/management/source_registry.py', 'pipeline/ingestion/fiscal/jurisdictions/132195/layouts/sources-supplementary-2020-1.toml', 'pipeline/ingestion/fiscal/management/sources.json', 'pipeline/ingestion/fiscal/management/sources.py', 'pipeline/ingestion/fiscal/management/sources.schema.json', 'pipeline/ingestion/inputs.py', 'pipeline/ingestion/paths.py', 'pipeline/ingestion/shared/jurisdictions.py', 'pipeline/pyproject.toml', 'pyproject.toml', 'uv.lock')
