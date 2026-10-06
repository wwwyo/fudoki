"""Git-managed Komae initial detail source/provider registration.

Account-specific resources distinguish rows from the same physical PDF. This
module never allocates amounts, weakens target identities or reads .agent files.
"""
from __future__ import annotations
import json
from pathlib import Path
import tomllib

CONFIG = Path(__file__).with_name('sources-initial-detail.toml')
FAMILY = 'initial-expenditure-project-setsu'
ACCOUNT_SLUGS = {'一般会計':'general','国民健康保険特別会計':'national-health',
                 '後期高齢者医療特別会計':'elderly','介護保険特別会計':'care','駐車場事業特別会計':'parking'}


def load_initial_detail(path: Path = CONFIG) -> dict[str, dict]:
    specs = tomllib.loads(path.read_text())['initial_detail']
    for key, spec in specs.items():
        expected = f'132195:{spec["fiscal_year"]}:{ACCOUNT_SLUGS[spec["fund_label"]]}'
        if key != expected or spec['table_id'] != FAMILY+'-'+spec['account_slug']:
            raise ValueError('Initial account resource identity differs from Git-managed declaration')
        if spec['approval_status'] != 'cover-approved' or spec['edition_status'] != 'published':
            raise ValueError('Only explicitly approved published initial detail is supported')
    return specs


def initial_detail_sources(path: Path = CONFIG):
    from ingestion.fiscal.sources import Source, Resource
    from ingestion.shared.jurisdictions import jurisdiction_name
    return {'initial-detail:'+key: Source(
        key='initial-detail:'+key,catalog=None,jurisdiction_code='132195',jurisdiction_name=jurisdiction_name('132195'),
        fiscal_year=spec['fiscal_year'],fiscal_year_label=None,document_kind='budget',document_label=spec['document_title'],
        dataset_title=None,encoding='',redistribute=spec['redistribute'],redistribute_basis=spec['redistribute_basis'],
        license_id=spec['license_id'],attribution=spec['attribution'],landing_page=spec['landing_page'],raw_form='extracted',
        resources=(Resource(direction='expenditure',resource_name=spec['document_title'],url=spec['url'],
            url_basis=spec['url_basis'],table_id=spec['table_id']),)) for key,spec in load_initial_detail(path).items()}


def initial_dataset_id(year, origin_sha256, resource):
    return f'132195:{year}:expenditure:budget:{origin_sha256}:{resource}'


def register_initial_declarations(rows, history, entries):
    """Append adopted initial datasets and tag frozen moku pilot as reference.

    Intended shared declarations.py hook. No initial dataset is declared unless
    its original/table/provenance is actually adopted in the current lock.
    """
    from ingestion.inputs import source_metadata_bytes
    from ingestion.paths import INPUT_LOCK
    specs=load_initial_detail();initial=[];adopted_accounts=set()
    for entry in entries:
        if not entry['path'].startswith('initial-detail/'):
            continue
        prov=json.loads(source_metadata_bytes(INPUT_LOCK,entry));key=prov['source_key'].removeprefix('initial-detail:')
        spec=specs[key]
        if (prov['table_id']!=spec['table_id'] or entry['originEdition']!=spec['expected_sha256']
            or entry['table']['sha256']!=spec['expected_table_sha256'] or prov['rows']!=spec['expected_rows']):
            raise ValueError('Adopted initial source identity/table bytes/count differ from canonical declaration')
        dataset=initial_dataset_id(entry['fiscalYear'],entry['originEdition'],prov['table_id'])
        source=dict(documentKind='budget',documentLabel=spec['document_title'],landingPage=spec['landing_page'],
            url=spec['url'],sha256=entry['originEdition'],licenseId=spec['license_id'],attribution=spec['attribution'],
            rawForm='extracted',tableId=spec['table_id'],pages=prov['pages'],observationRole='authoritative-initial-detail',
            grain=prov['grain'],approvalDate=spec['approval_date'],approvalStatus='cover-approved',fundLabel=spec['fund_label'],
            sourceAmountUnit='千円',unitMultiplier=1000,
            rawTableSha256=entry['table']['sha256'],
            reserveExceptionRows=spec['reserve_exception_rows'],canonicalInitial=True,
            initialTargetNamespace='initial-printed-target',equivalentSupplementaryNamespace='supplementary-printed-target',
            equivalenceRule='exact-observed-identity-including-sourceGrain; explicit nonadditive proof')
        row=dict(dataset_id=dataset,jurisdiction_code='132195',fiscal_year=spec['fiscal_year'],direction='expenditure',
            document_kind='budget',source_json=json.dumps(source,ensure_ascii=False,sort_keys=True))
        structure=dict(hierarchy=['kan','kou','moku','project','setsu'],dimensions=['department'],
            funds=[dict(code='',label=spec['fund_label'])],scope=dict(granularity=prov['grain'],
            authoritativeInitial=True,sourceAmountUnit='千円',reserveExceptionRows=spec['reserve_exception_rows'],
            expenditureSetsuStatus='printed-code-name-active-year-master; blank-code reserve unconfirmed'))
        initial.append(dict(**row,origin_sha256=entry['originEdition'],effective_at=spec['approval_date'],amendment_number=0,
            fund_label=spec['fund_label'],line_count=prov['rows'],structure_json=json.dumps(structure,ensure_ascii=False,sort_keys=True)))
        adopted_accounts.add(('132195',spec['fiscal_year'],spec['fund_label']))
        rows.append(row)
    history.extend(initial)
    # Frozen pilot identifiers and bytes survive; only its declaration role
    # changes when the exact same year/account has complete authoritative detail.
    for collection in [rows,history]:
        for row in collection:
            source=json.loads(row['source_json'])
            key=(row['jurisdiction_code'],row['fiscal_year'],source.get('fundLabel','一般会計'))
            if (row['document_kind']=='budget' and source.get('tableId')=='expenditure-detail' and key in adopted_accounts):
                source.update(observationRole='nonadditive-initial-moku-reference',canonicalInitial=False,
                    supersededByInitialDetail=True)
                row['source_json']=json.dumps(source,ensure_ascii=False,sort_keys=True)
    return rows,history
