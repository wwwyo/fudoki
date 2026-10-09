"""Current-schema3 five-argument ordinary coverage; results require actual runtime checks."""
from __future__ import annotations

from importlib import import_module as _ingestion_module
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
import duckdb
from ingestion.inputs import OBJECTS, digest, read_lock, safe_relative, verify_object, source_metadata_bytes
records = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.native_settlement_coverage').records
registration = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.registration')
NAMESPACE = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.contracts').NAMESPACE
TABLES = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.contracts').TABLES
bounded_read = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.contracts').bounded_read
resource_seal = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.contracts').resource_seal
require = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.contracts').require
read_reviewed_definitions = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.contracts').read_reviewed_definitions
expected_raw_columns = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.contracts').expected_raw_columns
validate_source_metadata = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.contracts').validate_source_metadata
validate_keys = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.contracts').validate_keys
verify_descriptor = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.contracts').verify_descriptor
verify_duck_runtime = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.contracts').verify_duck_runtime
verify_physical_schema = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.contracts').verify_physical_schema
DEFINITION_PATH = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.contracts').DEFINITION_PATH

FIELDS=['dataset_id','jurisdiction_code','fiscal_year','document_kind','origin_sha256',
        'structure_json','source_json','phases_json','line_count','direction']
SELECT='select '+','.join(FIELDS)+' from int_fiscal_datasets'
STAGE_EXTRA=[('direction','VARCHAR'),('fiscal_year','INTEGER'),('jurisdiction_code','VARCHAR'),
             ('dataset_id','VARCHAR'),('fiscal_line_id','VARCHAR'),('document_kind','VARCHAR'),
             ('source_role','VARCHAR'),('original_table_id','VARCHAR'),('source_json','VARCHAR')]

def incomplete():
    return dict(complete=False,files=[],accounts={},errors=[],original_rows=0,
                all_original_fields_preserved=False,recognition_status='unconfirmed',
                project_legal_setsu_correspondence='unconfirmed')

def provider(row):
    return json.loads(row['source_json']).get('provider')

def unique_occurrences(rows,label):
    counts=Counter(row['dataset_id'] for row in rows)
    require(all(type(k) is str and k and v==1 for k,v in counts.items()),label+': duplicate/NULL dataset occurrence')

def output_coverage(connection, candidate: Path, hashes: dict, lock_path: Path, datasets: list[dict]) -> None:
    selected=[]
    expected={}
    try:
        selected=[r for r in datasets if provider(r)==NAMESPACE]
        for r in selected:r['output_coverage']=incomplete()
        # Both raw occurrence lists are authenticated BEFORE any set/dict collapse.
        specs=registration.specifications()
        for source_key,s in specs.items():
            for t in s['tables']:
                did=registration.dataset_id(s,t)
                require(did not in expected,'repeated specification dataset')
                expected[did]=(source_key,s,t)
        require(len(expected)==38,'exact38 specification occurrences')
        unique_occurrences(selected,'caller')
        definitions=read_reviewed_definitions(registration.DIRECTORY)
        verify_duck_runtime(registration.DIRECTORY,duckdb)
        registry_rows=[dict(zip(FIELDS,v,strict=True)) for v in connection.execute(
            SELECT+" where json_extract_string(source_json,'$.provider')=?",[NAMESPACE]).fetchall()]
        unique_occurrences(registry_rows,'raw registry')
        require(len(registry_rows)==38 and {r['dataset_id'] for r in registry_rows}==set(expected),
                'registry exact38 scope; missing/extra dataset')
# Validate the fourth actual macro CSV and common-mart observed phase semantics.
# Run inside the existing outer fail-closed guard, before any table is complete.
        registry_csv='fiscal/132241/tama_ordinary_history_datasets.csv'
        require(registry_csv in hashes,'registry CSV missing from verified artifacts')
        registry_path=candidate/safe_relative(registry_csv)
        require(resource_seal(registry_path)['sha256']==hashes[registry_csv],'registry CSV hash differs')
        registry_mart='fiscal_132241_tama_ordinary_history_datasets'
        registry_schema=[('dataset_id','VARCHAR'),('jurisdiction_code','VARCHAR'),('fiscal_year','INTEGER'),
          ('direction','VARCHAR'),('document_kind','VARCHAR'),('origin_sha256','VARCHAR'),
          ('phases_json','VARCHAR'),('source_json','VARCHAR'),('structure_json','VARCHAR'),('line_count','BIGINT')]
        registry_desc=connection.execute('describe select * from '+registry_mart).fetchall()
        require([(r[0],r[1]) for r in registry_desc]==registry_schema,'registry provided exact field types/order')
        with registry_path.open('r',encoding='utf-8',newline='') as f:
            require(next(csv.reader(f),None)==[k for k,_ in registry_schema],'registry CSV exact header')
        registry_types=dict(registry_schema)
        registry_csv_rows=records(connection,"select * from read_csv(?,header=true,auto_detect=false,columns=?,allow_quoted_nulls=false,nullstr='')",[str(registry_path),registry_types])
        unique_occurrences(registry_csv_rows,'registry CSV')
        require(len(registry_csv_rows)==38 and {r['dataset_id'] for r in registry_csv_rows}==set(expected),'registry CSV exact38 scope')
        projected=','.join(FIELDS)
        registry_diff=connection.execute(f"""select
          (select count(*) from ({SELECT} where json_extract_string(source_json,'$.provider')=? except all
            select {projected} from read_csv(?,header=true,auto_detect=false,columns=?,allow_quoted_nulls=false,nullstr='')))+
          (select count(*) from (select {projected} from read_csv(?,header=true,auto_detect=false,columns=?,allow_quoted_nulls=false,nullstr='') except all
            {SELECT} where json_extract_string(source_json,'$.provider')=?))""",
          [NAMESPACE,str(registry_path),registry_types,str(registry_path),registry_types,NAMESPACE]).fetchone()[0]
        require(registry_diff==0,'registry CSV required values/types/NULL multiplicities differ')
        common_rows=records(connection,"select dataset_id,source_amount_kind from fiscal_datasets where json_extract_string(source_json,'$.provider')=?",[NAMESPACE])
        unique_occurrences(common_rows,'common mart')
        require(len(common_rows)==38 and {r['dataset_id'] for r in common_rows}==set(expected),'common mart exact38 occurrences')
        require(all(r['source_amount_kind']==('executed' if expected[r['dataset_id']][2]['table_id']=='project-rows' else None)
                    for r in common_rows),'common mart lexical30 NULL; financial8 observation only')

        registry={r['dataset_id']:r for r in registry_rows}
        seen=set()
        for r in selected:
            require(r['dataset_id'] in registry,'caller dataset absent from registry')
            original=registry[r['dataset_id']]
            require(all(r[k]==original[k] for k in FIELDS if k in r),'caller/registry field differs')
            r.setdefault('direction',original['direction']);seen.add(r['dataset_id'])
        for r in registry_rows:
            if r['dataset_id'] not in seen:
                r['output_coverage']=incomplete();selected.append(r);datasets.append(r);seen.add(r['dataset_id'])
        require(len(selected)==38,'exact38 caller+registry supplementation')
        registered={r['dataset_id']:r for r in selected}
        # Initial lock IO is in this try: schema/IO failures leave all38 incomplete.
        entries=[e for e in read_lock(lock_path)['entries'] if e['path'].startswith(NAMESPACE+'/')]
        require(len(entries)==38 and len({e['path'] for e in entries})==38,'exact38 unique lock occurrences')
        entry_ids=[];by_table=defaultdict(list)
        for entry in entries:
            tid=entry['path'].rsplit('table=',1)[-1]
            did=f"132241:{entry['fiscalYear']}:{entry['direction']}:{entry['documentKind']}:{entry['originEdition']}:{tid}"
            require(did in registered and did in expected,'unregistered adopted entry')
            entry_ids.append(did);row=registered[did]
            try:
                require('provenance' not in entry,'no separate provenance in schema3')
                p=json.loads(source_metadata_bytes(lock_path,entry));source_key,s,t=expected[did]
                s={**s,'source_spec_key':source_key}
                require(p['source_key']=='ordinary-history:'+source_key,'exact source key')
                require(entry['path']==registration.input_path(s,t),'exact logical input path')
                validate_source_metadata(entry,p,s,t,definitions)
                require(row['jurisdiction_code']=='132241' and row['fiscal_year']==s['financial_year']
                        and row['direction']==t['direction'] and row['document_kind']=='settlement'
                        and row['origin_sha256']==s['origin_sha256']
                        and type(row['line_count']) is int and row['line_count']==t['rows'],'registry required values/types')
                phases=['executed'] if tid=='project-rows' else []
                require(json.loads(row['phases_json'])==phases,'exact observed phases')
                src=json.loads(row['source_json'])
                require(src['provider']==NAMESPACE and src['tableId']==tid and src['observationRole']==TABLES[tid][1]
                        and src['recognitionStatus']==src['projectSetsuLinkage']==src['expenditureSetsuStatus']=='unconfirmed',
                        'registered role/unknown legal correspondence')
                require((src['sourceAmountUnit'],src['unitMultiplier'])==
                        (t.get('source_amount_unit'),t.get('unit_multiplier')),'registered NULL unit')
                require(src['rawSchema']==p['raw_schema'] and src['definitionFiles']=={DEFINITION_PATH:definitions[DEFINITION_PATH]},'registered schema/definition trust anchor')
                seal = _ingestion_module('ingestion.fiscal.jurisdictions.132241.layouts.tama_ordinary_history.contracts').seal
                source_seal=seal((json.dumps(entry['source'],ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode())
                require(src['sourceDeclarationSeal']==source_seal and src['sourceDeclaration']=={k:v for k,v in entry['source'].items() if k!='definition_files'},'exact full inline source seal/declaration')
                path=OBJECTS/safe_relative(entry['table']['key']);verify_object(entry['table'],bounded_read(path))
                by_table[tid].append((entry,p,row,path))
            except (ValueError,KeyError,TypeError,OSError) as error:
                row['output_coverage']['errors'].append(str(error))
        require(len(entry_ids)==len(set(entry_ids))==38 and set(entry_ids)==set(expected),'exact lock/spec occurrence keys')
        for tid,members in by_table.items():
            relative=f'fiscal/132241/tama_ordinary_history_{tid.replace("-","_")}.csv'
            try:
                require(relative in hashes,'CSV not in verified artifact hashes')
                csv_path=candidate/safe_relative(relative)
                require(resource_seal(csv_path)['sha256']==hashes[relative],'CSV hash differs')
                mart='fiscal_132241_tama_ordinary_history_'+tid.replace('-','_')
                desc=connection.execute('describe select * from '+mart).fetchall()
                require(len({r[0] for r in desc})==len(desc),'duplicate mart columns')
                raw=expected_raw_columns(members[0][1])
                stage_extra=[x for x in STAGE_EXTRA if tid!='project-rows' or x[0]!='direction']
                wanted_names=[c['name'] for c in raw]+[x[0] for x in stage_extra]
                wanted_types=[c['type'] for c in raw]+[x[1] for x in stage_extra]
                require([(r[0],r[1]) for r in desc]==list(zip(wanted_names,wanted_types,strict=True)),'exact provided column order/types')
                # Text-only header parsing; no inferred Duck types and no duplicate header collapse.
                with csv_path.open('r',encoding='utf-8',newline='') as f:
                    require(next(csv.reader(f),None)==wanted_names,'exact CSV header')
                types=dict(zip(wanted_names,wanted_types,strict=True))
                all_csv=records(connection,"select * from read_csv(?,header=true,auto_detect=false,columns=?,allow_quoted_nulls=false,nullstr='')",[str(csv_path),types])
                expected_group={registration.dataset_id(s,t) for _,s,t in expected.values() if t['table_id']==tid}
                require({r['dataset_id'] for r in all_csv}==expected_group,'CSV exact group dataset scope')
                require(all(r['dataset_id'] is not None for r in all_csv),'CSV NULL dataset')
                for entry,p,row,path in members:
                    try:
                        verify_physical_schema(connection,path,tid)
                        expected_schema=expected_raw_columns(p)
                        verify_descriptor(connection.execute('describe select * from read_parquet(?)',[str(path)]).fetchall(),expected_schema,'raw')
                        # Nullable original cells stay nullable. Every raw field/type is exact,
                        # and EXCEPT ALL below preserves actual NULL multiplicity in both directions.
                        require([(r[0],r[1]) for r in desc[:len(expected_schema)]]==
                                [(c['name'],c['type']) for c in expected_schema],'raw/provided exact types')
                        rows=[r for r in all_csv if r['dataset_id']==row['dataset_id']]
                        require(len(rows)==p['rows']==row['line_count'],'provided exact row count')
                        validate_keys(rows,tid)
                        cols=','.join('"'+c['name']+'"' for c in expected_schema)
                        diff=connection.execute(f"""select
                         (select count(*) from (select {cols} from read_parquet(?) except all
                          select {cols} from read_csv(?,header=true,auto_detect=false,columns=?,allow_quoted_nulls=false,nullstr='') where dataset_id=?))+
                         (select count(*) from (select {cols} from read_csv(?,header=true,auto_detect=false,columns=?,allow_quoted_nulls=false,nullstr='') where dataset_id=? except all
                          select {cols} from read_parquet(?)))""",
                         [str(path),str(csv_path),types,row['dataset_id'],str(csv_path),types,row['dataset_id'],str(path)]).fetchone()[0]
                        require(diff==0,'original fields/values/NULL multiplicity differ')
                        require(all(r['origin_sha256']==row['origin_sha256'] and r['direction']==row['direction']
                            and r['fiscal_year']==row['fiscal_year'] and r['document_kind']=='settlement'
                            and r['jurisdiction_code']=='132241' and r['source_role']==TABLES[tid][1]
                            and r['original_table_id']==tid and json.loads(r['source_json'])==json.loads(row['source_json'])
                            for r in rows),'provided required identity/role/source fields')
                        proof=row['output_coverage'];proof.update(complete=True,files=[relative,registry_csv],
                            original_rows=len(rows),all_original_fields_preserved=True)
                    except (ValueError,KeyError,TypeError,OSError,duckdb.Error) as error:
                        row['output_coverage']['errors'].append(str(error))
            except (ValueError,KeyError,TypeError,OSError,duckdb.Error) as error:
                for _,_,row,_ in members:row['output_coverage']['errors'].append(str(error))
    except (ValueError,KeyError,TypeError,OSError,ImportError,AttributeError,duckdb.Error) as error:
        # Initialization is inside the guard. No existing non-ordinary dataset is changed.
        for row in selected:
            proof=row.setdefault('output_coverage',incomplete())
            if not proof['complete']:proof['errors'].append(str(error))
        # Expose absent registry registrations explicitly; never invent a passing row.
        present={r.get('dataset_id') for r in selected}
        for did,(_,s,t) in expected.items():
            if did not in present:
                proof=incomplete();proof['errors'].append('registry/readback initialization failed: '+str(error))
                datasets.append(dict(dataset_id=did,jurisdiction_code='132241',fiscal_year=s['financial_year'],
                    direction=t['direction'],document_kind='settlement',origin_sha256=s['origin_sha256'],
                    source_json=json.dumps(dict(provider=NAMESPACE,diagnosticOnly=True,missingRegistration=True)),
                    phases_json=None,line_count=None,structure_json=None,output_coverage=proof))
