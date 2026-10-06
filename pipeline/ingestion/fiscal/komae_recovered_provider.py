"""Recovered Komae FY2019-22 initial-detail chapter provider (private mirror).

Mirrors initial_detail_provider: declarations come from a finite manifest, are
adopted only through the private lock, and never infer approval (chapter
documents carry no cover page). Revenue rows stay a separate direction; setsu
rows keep printed-parent evidence, no project mapping.
"""
from pathlib import Path
import json
import tomllib
from ingestion.fiscal.source_registry import INVENTORY, load_registry, project_sources

CONFIG = INVENTORY
PROVIDER_VERSION = 1

def load_recovered(path: Path = CONFIG):
    if path.suffix == '.toml':
        return tomllib.loads(path.read_text(encoding='utf-8'))['recovered']
    return project_sources(load_registry(path))['recovered_initial_detail']

def komae_recovered_sources(path: Path = CONFIG):
    from ingestion.fiscal.sources import Source, Resource
    from ingestion.shared.jurisdictions import jurisdiction_name
    out = {}
    for key, spec in load_recovered(path).items():
        title = spec['document_title']
        out['komae-recovered:' + key] = Source(
            key='komae-recovered:' + key, catalog=None, jurisdiction_code='132195',
            jurisdiction_name=jurisdiction_name('132195'), fiscal_year=spec['fiscal_year'],
            fiscal_year_label=None, document_kind='budget', document_label=title,
            dataset_title=None, encoding='', redistribute=spec['redistribute'],
            redistribute_basis=spec['redistribute_basis'], license_id=spec['license_id'],
            attribution=spec['attribution'], landing_page=spec['landing_page'],
            raw_form='extracted',
            resources=(Resource(direction=spec['direction'], resource_name=title,
                                url=spec['wayback_url'], url_basis=spec['url_basis'],
                                table_id=spec['table_id']),))
    return out

def register_komae_recovered_declarations(rows, history, entries):
    """Append recovered initial datasets; approval stays unconfirmed."""
    from ingestion.inputs import source_metadata_bytes
    from ingestion.paths import INPUT_LOCK
    specs = load_recovered()
    for entry in entries:
        if not entry['path'].startswith('initial-detail-recovered/'):
            continue
        prov = json.loads(source_metadata_bytes(INPUT_LOCK, entry))
        key = prov['source_key'].removeprefix('komae-recovered:')
        spec = specs[key]
        if (prov['table_id'] != spec['table_id'] or entry['originEdition'] != spec['expected_sha256']
                or entry['table']['sha256'] != spec['expected_table_sha256']
                or prov['rows'] != spec['expected_rows']):
            raise ValueError('Recovered initial source identity/table bytes/count differ from declaration')
        dataset = f"132195:{spec['fiscal_year']}:{spec['direction']}:budget:{entry['originEdition']}:{spec['table_id']}"
        source = dict(documentKind='budget', documentLabel=spec['document_title'],
            landingPage=spec['landing_page'], url=spec['wayback_url'],
            originalUrl=spec['original_url'], waybackCapture=spec['wayback_capture'],
            sha256=entry['originEdition'], licenseId=spec['license_id'],
            attribution=spec['attribution'], rawForm='extracted',
            tableId=spec['table_id'], pages=prov['pages'],
            observationRole='authoritative-initial-detail-candidate',
            grain=prov['grain'], approvalStatus='unconfirmed',
            approvalBasis='chapter document carries no cover page; approval not printed',
            sourceAmountKind=None,  # unconfirmed initial reference: kind not declared
            phases=[],  # no printed phase boundary in chapter originals
            fundLabel=spec['fund_label'], sourceAmountUnit='千円', unitMultiplier=1000,
            additive=False, nonadditiveReason='candidate pending parent review; not additive to any existing grain',
            provider='ingestion.fiscal.komae_recovered_provider',
            coordinateStatus='x-estimate-only: bbox_json carries x-bounds; y/height are synthetic row bounds, not measured',
            yStatus='unobserved-null',
            unitMultiplierBasis='printed 千円',
            
            
            rawTableSha256=entry['table']['sha256'],
            canonicalInitial=False, canonicalChanges=False, candidateAdoption=True,
            equivalenceNote='fiscal content identical to nothing adopted; new year coverage FY2019-22')
        row = dict(dataset_id=dataset, jurisdiction_code='132195',
                   fiscal_year=spec['fiscal_year'], direction=spec['direction'],
                   document_kind='budget',
                   source_json=json.dumps(source, ensure_ascii=False, sort_keys=True))
        structure = dict(hierarchy=['kan', 'kou', 'moku', 'setsu'], dimensions=[],
            funds=[dict(code='', label=spec['fund_label'])],
            scope=dict(granularity='moku+setsu+context',
                authoritativeInitial=False, approvalStatus='unconfirmed',
                sourceAmountUnit='千円', chapterDocument=True,
                expenditureSetsuStatus='printed-setsu-with-moku-context; project names unprinted-unconfirmed'))
        history.append(dict(**row, origin_sha256=entry['originEdition'],
            effective_at=None, amendment_number=0, fund_label=spec['fund_label'],
            line_count=prov['rows'],
            structure_json=json.dumps(structure, ensure_ascii=False, sort_keys=True)))
        rows.append(row)
    return rows, history
