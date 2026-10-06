"""Komae FY2020 supplementary1 schema3 provider; no phase/approval inference."""
from __future__ import annotations
import json
from pathlib import Path
from ingestion.fiscal.komae_supplementary_2020_1_contracts import (
    CONFIG, PROVIDER, NS, APPROVAL_BASIS, load, dataset_id, validate_entry, validate_generated,
)

def komae_supplementary_2020_1_sources(path: Path=CONFIG):
    from ingestion.fiscal.sources import Source,Resource
    from ingestion.shared.jurisdictions import jurisdiction_name
    out={}
    for key,s in load(path).items():
        sourcekey='komae-suppl-2020-1:'+key
        out[sourcekey]=Source(key=sourcekey,catalog=None,jurisdiction_code='132195',
            jurisdiction_name=jurisdiction_name('132195'),fiscal_year=s['fiscal_year'],fiscal_year_label=None,
            document_kind='supplementary',document_label=s['document_title'],dataset_title=None,encoding='',
            redistribute=s['redistribute'],redistribute_basis=s['redistribute_basis'],license_id=s['license_id'],
            attribution=s['attribution'],landing_page=s['landing_page'],raw_form='extracted',
            resources=(Resource(direction=s['direction'],resource_name=s['document_title'],
                url=s['original_url'],url_basis=s['url_basis'],table_id=s['table_id']),))
    return out

def source_json(entry,spec,metadata):
    return dict(documentKind='supplementary',documentLabel=spec['document_title'],
        landingPage=spec['landing_page'],url=spec['original_url'],originalUrl=spec['original_url'],
        sha256=entry['originEdition'],licenseId=spec['license_id'],attribution=spec['attribution'],
        rawForm='extracted',tableId=spec['table_id'],pages=13,
        observationRole=entry['source']['observation_role'],grain=entry['source']['grain'],
        approvalStatus='unconfirmed',approvalBasis=APPROVAL_BASIS,sourceAmountKind=None,phases=[],
        fundLabel='一般会計',sourceAmountUnit='千円',unitMultiplier=1000,additive=False,
        nonadditiveReason=entry['source']['nonadditive_reason'],provider=PROVIDER,amendmentNumber=1,
        projectSetsuLinkage='unconfirmed',recognitionStatus='unconfirmed',
        coordinateStatus='layout/native lane retained; no newly measured bbox in this integration',
        rawTableSha256=entry['table']['sha256'],rawTableBytes=entry['table']['bytes'],
        rawSchema=metadata['raw_schema'],definitionFiles=entry['source']['definition_files'],
        sourceDeclaration=entry['source'],inputIdentity={k:entry[k] for k in ('path','jurisdiction','fiscalYear','direction','documentKind','originEdition','origin','table')},
        canonicalInitial=False,canonicalChanges=False,canonicalExecuted=False,
        inputMetadataRegenerated=True)

def register_declarations(rows,history,entries,lock_path=None):
    from ingestion.inputs import source_metadata_bytes
    if lock_path is None:
        from ingestion.paths import INPUT_LOCK
        lock_path=INPUT_LOCK
    selected=[e for e in entries if e['path'].startswith(NS)]
    if not selected:return rows,history
    if len(selected)!=2 or len({e['path'] for e in selected})!=2:raise ValueError('exact2 new input occurrences')
    specs=load();seen=set()
    for entry in selected:
        key=entry['source']['source_key'].removeprefix('komae-suppl-2020-1:')
        spec=specs[key];identity=validate_entry(entry,spec)
        if identity in seen:raise ValueError('duplicate target dataset')
        seen.add(identity)
        metadata=json.loads(source_metadata_bytes(lock_path,entry));validate_generated(entry,spec,metadata)
        row=dict(dataset_id=identity,jurisdiction_code='132195',fiscal_year=2020,
            direction=spec['direction'],document_kind='supplementary',
            source_json=json.dumps(source_json(entry,spec,metadata),ensure_ascii=False,sort_keys=True))
        structure=dict(hierarchy=['kan','kou','moku','setsu'],dimensions=[],funds=[dict(code='',label='一般会計')],
            scope=dict(granularity='kan+kou+moku+setsu+context',supplementary=True,nonadditive=True,
                additiveWithinOwnGrain=False,sourceAmountUnit='千円',unitMultiplier=1000,
                projectSetsuLinkage='unconfirmed',approvalStatus='unconfirmed'))
        if any(r['dataset_id']==identity for r in rows+history):raise ValueError('preexisting dataset identity conflict')
        rows.append(row)
        history.append(dict(**row,origin_sha256=entry['originEdition'],effective_at=None,amendment_number=1,
            fund_label='一般会計',line_count=metadata['rows'],structure_json=json.dumps(structure,ensure_ascii=False,sort_keys=True)))
    if seen!={dataset_id(s) for s in specs.values()}:raise ValueError('exact two dataset identities')
    return rows,history
