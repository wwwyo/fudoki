"""Current schema3 inline-source contracts; no import-time IO.
Declarations are fixed; rows/schema/results are regenerated from actual tables.
No provenance sidecars. Exact definition files are distinct from global fingerprint.
"""
from __future__ import annotations
import hashlib,json,os,platform,re,stat,sys
from pathlib import Path,PurePosixPath
NAMESPACE = 'tama-ordinary-history'
PACKAGE = 'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_ordinary_history'
EXPECTED_REPOSITORY = '/Users/yuito_watanabe/orca/workspaces/fudoki/pilchard'
MAX_BYTES = 20000000
TABLES = {'pdf-word-observations': ('word_observations', 'positioned-original-text-layer-observation', ('physical_page', 'source_ordinal')), 'pdf-page-observations': ('page_observations', 'whole-physical-page-observation', ('physical_page',)), 'project-rows': ('project_rows', 'project-expenditure-original-rows', ('source_ordinal',))}
EXPECTED_SCHEMAS = {'project_rows': [{'name': 'source_ordinal', 'type': 'BIGINT', 'nullable': True}, {'name': 'physical_page', 'type': 'BIGINT', 'nullable': True}, {'name': 'printed_kan', 'type': 'VARCHAR', 'nullable': True}, {'name': 'printed_kou', 'type': 'VARCHAR', 'nullable': True}, {'name': 'printed_moku', 'type': 'VARCHAR', 'nullable': True}, {'name': 'printed_project_major', 'type': 'VARCHAR', 'nullable': True}, {'name': 'printed_project_minor', 'type': 'VARCHAR', 'nullable': True}, {'name': 'printed_project_name', 'type': 'VARCHAR', 'nullable': True}, {'name': 'printed_department', 'type': 'VARCHAR', 'nullable': True}, {'name': 'decided_amount', 'type': 'BIGINT', 'nullable': True}, {'name': 'funding_national', 'type': 'BIGINT', 'nullable': True}, {'name': 'funding_prefectural', 'type': 'BIGINT', 'nullable': True}, {'name': 'funding_bonds', 'type': 'BIGINT', 'nullable': True}, {'name': 'funding_specific', 'type': 'BIGINT', 'nullable': True}, {'name': 'funding_general', 'type': 'BIGINT', 'nullable': True}, {'name': 'raw_block', 'type': 'VARCHAR', 'nullable': True}, {'name': 'origin_sha256', 'type': 'VARCHAR', 'nullable': True}, {'name': 'document', 'type': 'VARCHAR', 'nullable': True}, {'name': 'year', 'type': 'BIGINT', 'nullable': True}, {'name': 'account', 'type': 'VARCHAR', 'nullable': True}, {'name': 'direction', 'type': 'VARCHAR', 'nullable': True}, {'name': 'printed_unit', 'type': 'VARCHAR', 'nullable': True}, {'name': 'source_unit_status', 'type': 'VARCHAR', 'nullable': True}, {'name': 'printed_amount_raw', 'type': 'VARCHAR', 'nullable': True}, {'name': 'complete_capture', 'type': 'BOOLEAN', 'nullable': True}, {'name': 'normalized_unit', 'type': 'VARCHAR', 'nullable': True}, {'name': 'unit_judgment_evidence', 'type': 'VARCHAR', 'nullable': True}], 'word_observations': [{'name': 'origin_sha256', 'type': 'VARCHAR', 'nullable': True}, {'name': 'document', 'type': 'VARCHAR', 'nullable': True}, {'name': 'physical_page', 'type': 'BIGINT', 'nullable': True}, {'name': 'source_ordinal', 'type': 'BIGINT', 'nullable': True}, {'name': 'printed_word', 'type': 'VARCHAR', 'nullable': True}, {'name': 'x_min', 'type': 'DOUBLE', 'nullable': True}, {'name': 'y_min', 'type': 'DOUBLE', 'nullable': True}, {'name': 'x_max', 'type': 'DOUBLE', 'nullable': True}, {'name': 'y_max', 'type': 'DOUBLE', 'nullable': True}], 'page_observations': [{'name': 'origin_sha256', 'type': 'VARCHAR', 'nullable': True}, {'name': 'document', 'type': 'VARCHAR', 'nullable': True}, {'name': 'physical_page', 'type': 'BIGINT', 'nullable': True}, {'name': 'width', 'type': 'DOUBLE', 'nullable': True}, {'name': 'height', 'type': 'DOUBLE', 'nullable': True}, {'name': 'word_count', 'type': 'BIGINT', 'nullable': True}]}
CORE_DEFINITIONS = ['pipeline/dbt/dbt_project.yml', 'pipeline/dbt/macros/fiscal_csv.sql', 'pipeline/dbt/macros/fiscal_units.sql', 'pipeline/dbt/models/intermediate/fiscal/records/int_132241__tama_ordinary_history_datasets.sql', 'pipeline/dbt/models/intermediate/fiscal/records/int_132241__tama_ordinary_history_pdf_page_observations.sql', 'pipeline/dbt/models/intermediate/fiscal/records/int_132241__tama_ordinary_history_pdf_word_observations.sql', 'pipeline/dbt/models/intermediate/fiscal/records/int_132241__tama_ordinary_history_project_rows.sql', 'pipeline/dbt/models/intermediate/fiscal/records/int_fiscal_datasets.sql', 'pipeline/dbt/models/marts/csv/csv_132241_tama_ordinary_history_datasets.sql', 'pipeline/dbt/models/marts/csv/csv_132241_tama_ordinary_history_pdf_page_observations.sql', 'pipeline/dbt/models/marts/csv/csv_132241_tama_ordinary_history_pdf_word_observations.sql', 'pipeline/dbt/models/marts/csv/csv_132241_tama_ordinary_history_project_rows.sql', 'pipeline/dbt/models/marts/records/fiscal_132241_tama_ordinary_history_datasets.sql', 'pipeline/dbt/models/marts/records/fiscal_132241_tama_ordinary_history_pdf_page_observations.sql', 'pipeline/dbt/models/marts/records/fiscal_132241_tama_ordinary_history_pdf_word_observations.sql', 'pipeline/dbt/models/marts/records/fiscal_132241_tama_ordinary_history_project_rows.sql', 'pipeline/dbt/models/marts/records/fiscal_datasets.sql', 'pipeline/dbt/models/staging/fiscal/stg_132241__tama_ordinary_history_pdf_page_observations.sql', 'pipeline/dbt/models/staging/fiscal/stg_132241__tama_ordinary_history_pdf_word_observations.sql', 'pipeline/dbt/models/staging/fiscal/stg_132241__tama_ordinary_history_project_rows.sql', 'pipeline/dbt/models/staging/fiscal/tama_ordinary_history_sources.yml', 'pipeline/ingestion/declarations.py', 'pipeline/ingestion/fiscal/management/coverage_audit.py', 'pipeline/ingestion/fiscal/jurisdictions/132195/layouts/held5-runtime-manifest.json', 'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/native_settlement_coverage.py', 'pipeline/ingestion/fiscal/management/sources.py', 'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_ordinary_history/__init__.py', 'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_ordinary_history/contracts.py', 'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_ordinary_history/evidence-manifest.json', 'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_ordinary_history/raw-schema.json', 'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_ordinary_history/reconstruct.py', 'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_ordinary_history/registration.py', 'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_ordinary_history/replay-manifest.json', 'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_ordinary_history/source-declarations.json', 'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_ordinary_history/sources.toml', 'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_ordinary_history_coverage.py', 'pipeline/ingestion/inputs.py', 'pipeline/ingestion/paths.py', 'pipeline/ingestion/shared/jurisdictions.py', 'pyproject.toml', 'uv.lock']

def require(ok, message):
    if not ok:
        raise ValueError(message)

def relative(value):
    require(type(value) is str and value and not any(ord(c)<32 for c in value), 'unsafe path text')
    p = PurePosixPath(value)
    require(not p.is_absolute() and '..' not in p.parts and '\\' not in value and str(p)==value, 'unsafe relative path')
    return value

def exact_keys(value, keys, label):
    require(type(value) is dict and set(value)==set(keys), label + ': exact keys required')

def pin(value):
    exact_keys(value, ('sha256','bytes'), 'pin')
    require(type(value['bytes']) is int and 0<=value['bytes']<=MAX_BYTES
            and type(value['sha256']) is str and re.fullmatch('[a-f0-9]{64}',value['sha256']), 'invalid SHA/bytes')
    return dict(value)

def seal(body):
    require(type(body) is bytes, 'bytes body required')
    return dict(sha256=hashlib.sha256(body).hexdigest(),bytes=len(body))

def object_identity(value, kind=None):
    require(type(value) is dict and {'key','sha256','bytes'}<=set(value)
            and set(value)<={'key','sha256','bytes','role'}, 'object ref keys')
    checked=resource_pin({k:value[k] for k in ('sha256','bytes')})
    key=relative(value['key'])
    kinds=(kind,) if kind else ('origin','table','proof')
    require(key in {f'inputs/{k}/sha256/{checked["sha256"]}' for k in kinds}, 'object key kind/SHA differs')
    return dict(key=key,**checked)

def resource_pin(value):
    # Input objects and installed runtime binaries are read-in-place resources,
    # not bounded transaction bodies or owned artifacts. Do not cap old originals.
    exact_keys(value,('sha256','bytes'),'resource pin')
    require(type(value['bytes']) is int and value['bytes']>=0 and type(value['sha256']) is str
            and re.fullmatch('[a-f0-9]{64}',value['sha256']),'resource SHA/bytes')
    return dict(value)

def merge_evidence_refs(existing, additions):
    out=dict(existing)
    for raw in additions:
        ref=object_identity(raw,'origin')
        if ref['key'] in out:
            require(object_identity(out[ref['key']])==ref, 'conflicting ordinary-history evidence identity')
        else:
            out[ref['key']]=ref
    return out

def evidence_metadata(manifest):
    exact_keys(manifest,('inputs',),'replay manifest')
    require(type(manifest['inputs']) is list and len(manifest['inputs'])==20,'exact20 replay inputs')
    ordinary={'4-1.pdf','7-1.pdf','13-1.pdf','16-1.pdf','3-1.pdf','6-1.pdf','12-1.pdf','15-1.pdf'}
    excluded={'3-1.pdf','9-1.pdf','10-1.pdf','2020/9-1.pdf','2020/10-1.pdf'}
    out={}
    documents=set()
    for item in manifest['inputs']:
        path=relative(item['path'])
        require(path not in documents and type(item['complete_capture']) is bool,'repeated document or bad capture type')
        require(item['year'] in (2019,2020),'replay year')
        documents.add(path)
        ref=object_identity(dict(key='inputs/origin/sha256/'+item['sha256'],sha256=item['sha256'],bytes=item['bytes']),'origin')
        require(ref['key'] not in out,'duplicate original hash')
        adopted=item['complete_capture'] and PurePosixPath(path).name in ordinary
        require(adopted==(path not in excluded),'exact observed excluded5 criteria')
        out[ref['key']]=dict(ref=ref,role='adopted' if adopted else 'replay-evidence',document=path,
                             complete_capture=item['complete_capture'])
    require(excluded<=documents and sum(x['role']=='adopted' for x in out.values())==15,'15 adopted / 5 replay-only')
    return out

def plain_path(path):
    """Do not resolve away symlink evidence. Every absolute ancestor is checked."""
    p=Path(path).absolute()
    require('..' not in p.parts,'absolute traversal')
    current=Path(p.anchor)
    for part in p.parts[1:]:
        current/=part
        require(not current.is_symlink(),'symlink ancestor: '+str(current))
    return p

def bounded_read(path):
    p=plain_path(path)
    # Walk all ancestors through O_NOFOLLOW dirfds, then open the leaf similarly.
    directory=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in p.parts[1:-1]:
            nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
            os.close(directory);directory=nxt
        fd=os.open(p.name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory)
    finally:os.close(directory)
    with os.fdopen(fd,'rb') as f:
        before=os.fstat(f.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size<=MAX_BYTES,'bounded regular file required')
        body=f.read(MAX_BYTES+1)
        after=os.fstat(f.fileno())
    now=p.stat(follow_symlinks=False)
    identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(len(body)<=MAX_BYTES and identity(before)==identity(after)==identity(now),'file changed during read')
    return body

def resource_read(path, expected):
    """Read an exact original resource, no symlink at leaf or any ancestor.

    Bound reads by that resource's independently declared integer byte count,
    not the transaction/artifact cap. Hash and fd/name/ancestor identities are
    checked before returning bytes. Extraction is never run on failed evidence.
    """
    expected=resource_pin(expected);p=plain_path(path)
    flags=os.O_RDONLY|os.O_NOFOLLOW
    directory=os.open('/',flags|os.O_DIRECTORY);fd=None
    inode=lambda s:(s.st_dev,s.st_ino)
    ident=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    chain=[inode(os.fstat(directory))]
    try:
        for part in p.parts[1:-1]:
            nxt=os.open(part,flags|os.O_DIRECTORY,dir_fd=directory)
            os.close(directory);directory=nxt;chain.append(inode(os.fstat(directory)))
        fd=os.open(p.name,flags|os.O_NONBLOCK,dir_fd=directory)
        before=os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_size==expected['bytes'],
                'original must be an exact-size regular resource')
        chunks=[];size=0;h=hashlib.sha256()
        while chunk:=os.read(fd,65536):
            size+=len(chunk);require(size<=expected['bytes'],'original grew beyond declared bytes')
            chunks.append(chunk);h.update(chunk)
        after=os.fstat(fd)
        require(ident(before)==ident(after)==ident(os.stat(p.name,dir_fd=directory,follow_symlinks=False)),
                'original fd/leaf changed during read')
        # Rewalk every absolute ancestor through O_NOFOLLOW, not Path.resolve().
        check=os.open('/',flags|os.O_DIRECTORY)
        try:
            require(inode(os.fstat(check))==chain[0],'original root ancestor replaced')
            for index,part in enumerate(p.parts[1:-1],start=1):
                nxt=os.open(part,flags|os.O_DIRECTORY,dir_fd=check);os.close(check);check=nxt
                require(inode(os.fstat(check))==chain[index],'original ancestor replaced')
            require(ident(os.stat(p.name,dir_fd=check,follow_symlinks=False))==ident(before),
                    'original path identity changed')
        finally:os.close(check)
        require({'sha256':h.hexdigest(),'bytes':size}==expected,'original SHA/int-bytes mismatch')
        return b''.join(chunks)
    finally:
        if fd is not None:os.close(fd)
        os.close(directory)

def resource_seal(path):
    p=plain_path(path);directory=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in p.parts[1:-1]:
            nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
            os.close(directory);directory=nxt
        fd=os.open(p.name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory)
    finally:os.close(directory)
    with os.fdopen(fd,'rb') as f:
        before=os.fstat(f.fileno());require(stat.S_ISREG(before.st_mode),'runtime regular file')
        h=hashlib.sha256();size=0
        while chunk:=f.read(65536):h.update(chunk);size+=len(chunk)
        after=os.fstat(f.fileno())
    now=p.stat(follow_symlinks=False)
    ident=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(ident(before)==ident(after)==ident(now) and size==before.st_size,'runtime changed during hash')
    return dict(sha256=h.hexdigest(),bytes=size)

def installed_root(directory):
    d=plain_path(directory)
    # Fixed reference workspace authority, not "any directory containing pipeline".
    # A .agent/provider snapshot must never authenticate as installed canonical.
    # Moving to another worktree requires a separately reviewed configuration rebase.
    root=plain_path(EXPECTED_REPOSITORY)
    require(d==root/PACKAGE,'one exact installed package root required')
    return root

def schema_contract(raw_schema):
    exact_keys(raw_schema,('namespace','tables'),'raw schema')
    require(raw_schema['namespace']==NAMESPACE and raw_schema['tables']==EXPECTED_SCHEMAS,'raw column/type/nullable contract changed')
    return raw_schema['tables']

def validate_specs(specs, evidence, raw_schema, replay):
    schema_contract(raw_schema)
    metadata=evidence_metadata(replay)
    require(type(evidence['originals']) is list and len(evidence['originals'])==20 and len({o['sha256'] for o in evidence['originals']})==20,'exact20 unique original occurrences before collapse')
    originals={o['sha256']:o for o in evidence['originals']}
    require(len(originals)==20 and len(specs)==15,'spec/original scope')
    adopted={k for k,v in metadata.items() if v['role']=='adopted'}
    seen=set();source_hashes=set();role_counts={k:0 for k in TABLES}
    for source_key,s in specs.items():
        sha=s['origin_sha256'];source_hashes.add('inputs/origin/sha256/'+sha)
        original=originals[sha]
        require(original['complete_capture'] is True and original['ordinary_scope'] is True,'complete ordinary source required')
        require(s['jurisdiction_code']=='132241' and type(s['financial_year']) is int
                and s['financial_year'] in (2019,2020) and s['document_kind']=='settlement'
                and s['raw_form']=='extracted','spec scope/types')
        require(s['url']==original['url'] and s['origin_bytes']==original['bytes']
                and s['recognition_status']=='unconfirmed','spec origin identity')
        for t in s['tables']:
            tid=t['table_id'];require(tid in TABLES,'unknown table')
            require((source_key,tid) not in seen,'duplicate source/table occurrence');seen.add((source_key,tid))
            role_counts[tid]+=1
            require(t['role']==TABLES[tid][1] and t['direction']==original['direction'],'exact table/role/direction')
            financial=tid=='project-rows'
            unit=('千円',1000) if financial and s['financial_year']==2020 else (None,None)
            require((t.get('phase'),t.get('source_amount_unit'),t.get('unit_multiplier'))==
                    (('executed' if financial else None),*unit),'observed phase/unit; unknown remains NULL')
            require(not financial or original['direction']=='expenditure','project expenditure only')
            require(t['additive_within_own_grain'] is False and type(t['rows']) is int and t['rows']>0,'nonadditive row count')
            pin(dict(sha256=t['candidate_table_sha256'],bytes=t['candidate_table_bytes']))
    require(source_hashes==adopted and role_counts=={'pdf-word-observations':15,'pdf-page-observations':15,'project-rows':8},'exact15 sources/38 roles')

def expected_raw_columns(provenance):
    tid=provenance['table_id'];require(tid in TABLES,'unknown raw table id')
    expected=EXPECTED_SCHEMAS[TABLES[tid][0]]
    require(provenance['raw_schema']==[{k:c[k] for k in ('name','type')} for c in expected],'provenance raw schema differs')
    return expected

def verify_descriptor(description, expected, label):
    require([(r[0],r[1],r[2]=='YES') for r in description]==
            [(c['name'],c['type'],c['nullable']) for c in expected],label+': exact ordered schema/type/nullability')

def validate_keys(rows, table_id):
    require(table_id in TABLES,'key table')
    keys=TABLES[table_id][2]
    for r in rows:
        require(all(r.get(k) is not None for k in (*keys,'fiscal_line_id','origin_sha256','dataset_id')),'NULL required observation key')
        require(all(type(r[k]) is int and r[k]>0 for k in keys),'positive integral observation key')
        suffix=':'.join(str(r[k]) for k in keys)
        require(r['fiscal_line_id']==r['dataset_id']+':'+suffix,'exact fiscal line ID')
    require(len({tuple(r[k] for k in keys) for r in rows})==len(rows),'duplicate native key')
    require(len({r['fiscal_line_id'] for r in rows})==len(rows),'duplicate fiscal line ID')

# Current API: declaration is input; physical results are regenerated separately.
DEFINITION_PATH = PACKAGE + '/definition-files.json'
METADATA_CONTRACT = 'inline-source-v3'

def declaration(spec,table,definitions):
    from ingestion.inputs import SOURCE_FIELDS
    configured=json.loads(bounded_read(installed_root(Path(__file__).absolute().parent)/PACKAGE/'source-declarations.json'))
    identity='ordinary-history:'+spec['source_spec_key']+':'+table['table_id']
    require(identity in configured,'missing configured source declaration')
    out={**configured[identity],'definition_files':definitions}
    require(set(out)<=SOURCE_FIELDS,'declaration fields incompatible with current inputs API')
    return out

def definitions_document(directory):
    root=installed_root(directory);body=bounded_read(root/DEFINITION_PATH);document=json.loads(body)
    exact_keys(document,('schema_version','metadata_contract','repository_root','required_roots','files','runtime'),'definition files')
    require(type(document['schema_version']) is int and document['schema_version']==1
            and document['metadata_contract']==METADATA_CONTRACT
            and document['repository_root']==EXPECTED_REPOSITORY,'definition contract/root')
    require(type(document['required_roots']) is list and document['required_roots']==sorted(document['files'])
            and len(document['required_roots'])==len(set(document['required_roots'])),'complete static file keyset')
    require(set(CORE_DEFINITIONS)<=set(document['files']),'required current support definitions absent')
    for name,expected in document['files'].items():
        relative(name);pin(expected)
        require(name!=DEFINITION_PATH and not name.endswith(('sources.lock.json','.pyc'))
                and '__pycache__' not in name and '/provenance/' not in name
                and not any(x in ('.agent','.cache','.build','objects') for x in PurePosixPath(name).parts),
                'cyclic/mutable definition member')
    exact_keys(document['runtime'],('python','duckdb','pdftotext'),'runtime resources')
    for name,item in document['runtime'].items():
        exact_keys(item,('path','sha256','bytes','version','version_basis'),'runtime '+name)
        resource_pin({k:item[k] for k in ('sha256','bytes')})
        require(type(item['path']) is str and Path(item['path']).is_absolute(),'absolute runtime identity')
        require(item['version'] is None or type(item['version']) is str,'runtime version annotation')
    return root,body,document

def read_reviewed_definitions(directory):
    root,body,document=definitions_document(directory)
    for name,expected in document['files'].items():
        require(seal(bounded_read(root/name))==expected,'current installed definition changed: '+name)
    return {**document['files'],DEFINITION_PATH:seal(body)}

def verify_runtime_resources(directory,approved_definitions=None):
    root,_,document=definitions_document(directory)
    if approved_definitions is not None:
        require({**document['files'],DEFINITION_PATH:seal(bounded_read(root/DEFINITION_PATH))}==approved_definitions,
                'execution definition anchor changed after inline-lock authentication')
    for name,item in document['runtime'].items():
        require(resource_seal(item['path'])=={k:item[k] for k in ('sha256','bytes')},'runtime bytes changed: '+name)
    python=document['runtime']['python']
    require(os.path.samefile(sys.executable,python['path']) and platform.python_version()==python['version'],
            'normal Python identity/version changed')
    return document['runtime']

def runtime_executable(directory,name,approved_definitions=None):
    current=read_reviewed_definitions(directory)
    require(approved_definitions is None or current==approved_definitions,'native extractor definition anchor drift')
    require(name=='pdftotext','only approved original native extractor')
    return verify_runtime_resources(directory,approved_definitions)[name]['path']

def verify_duck_runtime(directory,duckdb_module,approved_definitions=None):
    import _duckdb as native
    resources=verify_runtime_resources(directory,approved_definitions);item=resources['duckdb']
    require(duckdb_module.connect is native.connect and duckdb_module.__version__==item['version']
            and os.path.samefile(native.__file__,item['path']),'DuckDB normal wrapper/native identity')

def validate_entry_source(entry,spec,table,definitions):
    require('provenance' not in entry and entry['source']==declaration(spec,table,definitions),
            'inline source declaration exact binding; no sidecar provenance')
    require(entry['jurisdiction']=='132241' and entry['fiscalYear']==spec['financial_year']
            and entry['documentKind']=='settlement' and entry['direction']==table['direction']
            and entry['originEdition']==spec['origin_sha256'],'current entry scope')
    require(object_identity(entry['origin']['object'],'origin')==dict(key='inputs/origin/sha256/'+spec['origin_sha256'],
            sha256=spec['origin_sha256'],bytes=spec['origin_bytes']),'current origin identity')
    require(object_identity(entry['table'],'table')==dict(key='inputs/table/sha256/'+table['candidate_table_sha256'],
            sha256=table['candidate_table_sha256'],bytes=table['candidate_table_bytes']),'current raw identity')

def validate_source_metadata(entry,p,spec,table,definitions):
    validate_entry_source(entry,spec,table,definitions)
    require(all(p.get(k)==v for k,v in entry['source'].items()),'regenerated metadata changed a declaration')
    require(p['input_hashes_verified'] is True and type(p['rows']) is int and p['rows']==table['rows']
            and p['origin_sha256']==entry['originEdition'] and p['origin_bytes']==spec['origin_bytes']
            and p['raw_table_sha256']==entry['table']['sha256'] and p['raw_table_bytes']==entry['table']['bytes'],
            'regenerated physical table results/identity')
    require(p['jurisdiction_code']=='132241' and p['fiscal_year']==spec['financial_year']
            and p['direction']==table['direction'] and p['document_kind']=='settlement','metadata scope')
    expected_raw_columns(p)
    require(p['header']==[c['name'] for c in EXPECTED_SCHEMAS[TABLES[table['table_id']][0]]],
            'actual regenerated raw header/name/order')

def verify_physical_schema(connection,path,table_id):
    expected=EXPECTED_SCHEMAS[TABLES[table_id][0]]
    description=connection.execute('describe select * from read_parquet(?,hive_partitioning=false)',[str(path)]).fetchall()
    verify_descriptor(description,expected,'physical raw logical columns')
    leaves=connection.execute('select name,repetition_type from parquet_schema(?) where num_children is null',[str(path)]).fetchall()
    require(leaves==[(c['name'],'OPTIONAL' if c['nullable'] else 'REQUIRED') for c in expected],
            'physical Parquet leaf name/order/repetition must match declared nullable schema')

def bind_cli_definition_lock(path,expected,definitions,directory):
    """External SHA+bytes -> schema3 inline declarations -> installed definitions.

    The parent's sealed joint input body is the trust anchor, not a self-hashing
    definition ledger or TAMA_OH_DEFINITION_OVERLAY. This pure metadata check
    does not read tables or pretend to regenerate physical execution results.
    """
    import tomllib
    body=bounded_read(path);require(seal(body)==pin(expected),'externally sealed CLI input lock differs')
    lock=json.loads(body)
    require(type(lock['schemaVersion']) is int and lock['schemaVersion']==3 and type(lock['entries']) is list,
            'CLI current schema3 input envelope')
    all_paths=[e['path'] for e in lock['entries']]
    require(len(all_paths)==len(set(all_paths)),'CLI duplicate input occurrence')
    entries=[e for e in lock['entries'] if e['path'].startswith(NAMESPACE+'/')]
    require(len(entries)==38,'CLI exact38 Tama adopted inputs in parent joint lock')
    specs=tomllib.loads(bounded_read(Path(directory)/'sources.toml').decode())['ordinary_history']
    by_hash={s['origin_sha256']:(key,s) for key,s in specs.items()}
    require(len(by_hash)==15,'CLI fifteen source occurrences')
    seen=set()
    for entry in entries:
        key,spec=by_hash[entry['originEdition']];spec={**spec,'source_spec_key':key}
        tid=entry['path'].rsplit('table=',1)[-1]
        tables=[t for t in spec['tables'] if t['table_id']==tid]
        require(len(tables)==1,'CLI raw table binding');table=tables[0]
        wanted=(f"{NAMESPACE}/jurisdiction=132241/year={spec['financial_year']}"
                f"/document_kind=settlement/edition={spec['origin_sha256']}"
                f"/direction={table['direction']}/table={tid}")
        require(entry['path']==wanted,'CLI exact logical source/table/scope path')
        validate_entry_source(entry,spec,table,definitions)
        identity=(key,tid);require(identity not in seen,'CLI duplicate source/table occurrence');seen.add(identity)
    require(seen=={(key,t['table_id']) for key,s in specs.items() for t in s['tables']},'CLI complete source/table mapping')
    return seal(body)
