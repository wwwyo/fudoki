"""Read explicitly enabled ingestion declarations from the fiscal origin inventory.

This module only projects declarations and produces plans. It never downloads an
original, extracts a table, or changes the fixed input list.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit, urlunsplit

import jsonschema

HERE = Path(__file__).resolve().parent
INVENTORY = HERE / "sources.json"
SCHEMA = HERE / "sources.schema.json"
PDF_SECTIONS = (
    "statement", "budget_history", "supplementary_detail", "settlement_pdf",
    "project_names", "revenue_accounts",
    "initial_detail", "recovered_initial_detail", "native_initial_detail", "native_supplementary_detail",
    "native_supplementary_amendment",
)
SECTIONS = ("csv", *PDF_SECTIONS)
URL_FIELDS = {"url", "landing_page", "download_url", "landing_url", "approval_url"}


def _without_urls(value: object, location: str) -> None:
    """Options cannot become another editable copy of an origin address."""
    if isinstance(value, dict):
        for name, child in value.items():
            if name in URL_FIELDS:
                raise ValueError(f"{location}.{name}: use an origin reference instead of a URL")
            _without_urls(child, f"{location}.{name}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _without_urls(child, f"{location}[{index}]")


def _validate_supplementary_composition(source: dict, ingestion: dict,
                                       sources: dict[str, dict], where: str) -> None:
    """Bind a partial formal amendment to one original account edition."""
    options = ingestion['options']
    if ingestion['section'] == 'native_supplementary_detail':
        if 'composition' not in options:
            return
        base = source
        base_index = ingestion['profile'].get('edition_index', 0)
        motion = _referenced_source(options['composition']['source_id'], sources, where)
        matches = [i for i in motion.get('ingestions', [])
                   if i['section'] == 'native_supplementary_amendment' and i['enabled']]
        if len(matches) != 1:
            raise ValueError(f'{where}: composition requires one registered formal amendment')
        motion_ingestion = matches[0]
    else:
        motion, motion_ingestion = source, ingestion
        reference = options['replaces']
        base = _referenced_source(reference['source_id'], sources, where)
        base_index = reference['options']['edition_index']
        matches = [i for i in base.get('ingestions', [])
                   if i['section'] == 'native_supplementary_detail' and i['enabled']
                   and i.get('profile', {}).get('edition_index', 0) == base_index]
        if len(matches) != 1 or matches[0]['options'].get('composition') != {'source_id': motion['id']}:
            raise ValueError(f'{where}: formal amendment requires a reciprocal account registration')
    if not 0 <= base_index < len(base['editions']):
        raise ValueError(f'{where}: formal amendment replaces an unknown edition')
    reference = motion_ingestion['options']['replaces']
    if reference != {'source_id': base['id'], 'options': {'edition_index': base_index}}:
        raise ValueError(f'{where}: formal amendment replaces a different edition')
    motion_index = motion_ingestion['profile']['edition_index']
    if not 0 <= motion_index < len(motion['editions']):
        raise ValueError(f'{where}: formal amendment edition is unknown')
    original_edition, motion_edition = base['editions'][base_index], motion['editions'][motion_index]
    scope_fields = ('fiscal_year', 'account_label', 'document_phase', 'amendment_number')
    pages = motion_ingestion['profile']['physical_pages']
    if (motion['jurisdiction'] != base['jurisdiction'] or motion['jurisdiction'] != '132241'
        or motion['fiscal_year'] != base['fiscal_year'] or motion['document_phase'] != 'supplementary'
        or motion['role'] != 'decision' or motion['format'] != 'pdf'
        or 'expenditure' not in motion['directions']
        or any(motion_edition[k] != original_edition[k] for k in scope_fields)
        or original_edition['document_phase'] != 'supplementary'
        or motion_edition['in_scope']['status'] != 'included'
        or pages[1] > motion['content_inspection']['pages']):
        raise ValueError(f'{where}: formal amendment scope or physical pages differ from the original account')


def load_registry(path: Path = INVENTORY) -> dict:
    inventory = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker(),
    ).validate(inventory)
    if inventory.get("schema_version") != 1:
        raise ValueError("Unsupported source inventory version")
    sources = inventory["sources"]
    ids = [source["id"] for source in sources]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate origin identifiers")
    sources_by_id = {source['id']: source for source in sources}
    for source in sources:
        for ingestion in source.get("ingestions", []):
            where = f"{source['id']}.ingestions"
            if ingestion.get("section") not in SECTIONS:
                raise ValueError(f"{where}: unsupported ingestion section")
            if not isinstance(ingestion.get("key"), str) or not ingestion["key"]:
                raise ValueError(f"{where}: ingestion key is required")
            if not isinstance(ingestion.get("enabled"), bool):
                raise ValueError(f"{where}: enabled must be explicitly boolean")
            if ingestion.get("source_id", source["id"]) != source["id"]:
                raise ValueError(f"{where}: source_id must identify the containing origin")
            if not isinstance(ingestion.get("options"), dict):
                raise ValueError(f"{where}: options must be an object")
            _without_urls(ingestion["options"], where + ".options")
            if ingestion['enabled'] and ingestion['section'] in ('native_supplementary_detail', 'native_supplementary_amendment'):
                _validate_supplementary_composition(source, ingestion, sources_by_id, where)
            if ingestion['section'] == 'native_supplementary_detail':
                index = ingestion.get('profile', {}).get('edition_index', 0)
                if type(index) is not int or not 0 <= index < len(source['editions']):
                    raise ValueError(f'{where}: unknown native supplementary edition')
                edition = source['editions'][index]
                if (source['jurisdiction'] not in ('131016', '132047', '132241') or source['fiscal_year'] < 2019
                    or source['document_phase'] != 'supplementary' or source['format'] != 'pdf'
                    or 'expenditure' not in source.get('directions', [])
                    or edition['fiscal_year'] != source['fiscal_year']
                    or edition['document_phase'] != 'supplementary'
                    or edition['in_scope']['status'] != 'included'
                    or edition['account_label'] not in source['account_labels']
                    or edition['amendment_number'] not in source['amendment_numbers']
                    or (len(source['editions']) != 1 and 'edition_index' not in ingestion.get('profile', {}))
                    or ingestion['key'] != (source['id'] if len(source['editions']) == 1 else f'{source["id"]}:{index}')):
                    raise ValueError(f'{where}: native supplementary declaration differs from its inspected parent')
                if source['jurisdiction'] in ('132047', '132241') and 'physical_pages' not in ingestion.get('profile', {}):
                    raise ValueError(f'{where}: native supplementary pages must identify the inspected account')
            if ingestion['section'] == 'native_initial_detail':
                accounts = ingestion['options']['accounts']
                labels = [a['account_label'] for a in accounts]
                included = {e['account_label'] for e in source['editions']
                            if e['in_scope']['status'] == 'included'
                            and e['document_phase'] == 'initial'}
                if (ingestion['key'] != f"{source['jurisdiction']}:{source['fiscal_year']}"
                    or source['jurisdiction'] != '132241' or source['fiscal_year'] != 2026
                    or source['document_phase'] != 'initial' or source['format'] != 'pdf'
                    or 'expenditure' not in source.get('directions', [])
                    or len(labels) != len(set(labels)) or set(labels) != included):
                    raise ValueError(f'{where}: native initial accounts must match the included parent editions')
                ranges = [a['pages'] for a in accounts]
                if any(first > last or (last-first+1) % 2 for first,last in ranges):
                    raise ValueError(f'{where}: native pages must contain complete facing-page pairs')
                ordered = sorted(ranges)
                if any(left[1] >= right[0] for left,right in zip(ordered,ordered[1:])):
                    raise ValueError(f'{where}: native account pages overlap')
            profile = ingestion.get("profile", {})
            if not isinstance(profile, dict):
                raise ValueError(f"{where}: profile must be an object")
            index = profile.get("edition_index")
            if index is not None and (
                not isinstance(index, int) or isinstance(index, bool)
                or index < 0 or index >= len(source.get("editions", []))
            ):
                raise ValueError(f"{where}: unknown edition index")
            direction = profile.get("direction")
            if direction not in (None, "revenue", "expenditure"):
                raise ValueError(f"{where}: unknown direction")
            resource = ingestion["options"].get("resource", {})
            if direction is not None and resource.get("direction", direction) != direction:
                raise ValueError(f"{where}: profile and resource directions disagree")
            if ingestion["section"] in ("initial_detail", "recovered_initial_detail"):
                options = ingestion["options"]
                recovered = ingestion["section"] == "recovered_initial_detail"
                if not recovered:
                    pages = [options.get("first_page"), options.get("last_page")]
                    if (any(type(page) is not int or page < 1 for page in pages)
                        or pages[0] > pages[1]):
                        raise ValueError(f"{where}: initial detail pages must be an ordered inclusive range")
                if (source["jurisdiction"] != ingestion["key"].split(":")[0]
                    or source["fiscal_year"] != options.get("fiscal_year")
                    or source["document_phase"] != "initial"
                    or options.get("fund_label") not in source["account_labels"]
                    or direction not in ("revenue", "expenditure")
                    or (not recovered and direction != "expenditure")
                    or direction not in source.get("directions", [])):
                    raise ValueError(f"{where}: initial detail must match its parent jurisdiction, year, account and direction")
                if recovered:
                    if any(k in options for k in ("original_url", "wayback_url", "wayback_capture")):
                        raise ValueError(f"{where}: the containing origin supplies archive addresses and capture")
                    if (options.get("direction") != direction
                        or source.get("acquisition", {}).get("method") != "wayback"
                        or source["content_inspection"].get("sha256") != options.get("expected_sha256")
                        or source["content_inspection"].get("final_url") != _download(source)):
                        raise ValueError(f"{where}: recovered chapter must match its observed archived edition")
            target = profile.get("target", {})
            if not isinstance(target, dict):
                raise ValueError(f"{where}: target must be an object")
            _without_urls(target, where + ".profile.target")
            publication = profile.get("publication_index")
            if publication is not None and (
                not isinstance(publication, int) or isinstance(publication, bool)
                or publication < 0 or publication >= len(source.get("publication_links", []))
            ):
                raise ValueError(f"{where}: unknown publication index")
            pages = profile.get("physical_pages")
            if pages is not None and (
                not isinstance(pages, list) or len(pages) != 2
                or any(not isinstance(p, int) or isinstance(p, bool) or p < 1 for p in pages)
                or pages[0] > pages[1]
            ):
                raise ValueError(f"{where}: physical_pages must be an ordered inclusive range")
    return inventory


def _scope(source: dict, ingestion: dict) -> dict:
    profile = ingestion.get("profile", {})
    if ingestion['section'] == 'native_initial_detail':
        return dict(jurisdiction=source['jurisdiction'], fiscal_year=source['fiscal_year'],
                    document_phase=source['document_phase'], direction='expenditure',
                    accounts=deepcopy(ingestion['options']['accounts']))
    if ingestion["section"] == "initial_detail":
        return {"jurisdiction": source["jurisdiction"],
                "fiscal_year": ingestion["options"]["fiscal_year"],
                "account_label": ingestion["options"]["fund_label"],
                "document_phase": source["document_phase"],
                "direction": "expenditure",
                "physical_pages": [ingestion["options"]["first_page"],
                                   ingestion["options"]["last_page"]]}
    if ingestion["section"] == "recovered_initial_detail":
        return {"jurisdiction": source["jurisdiction"],
                "fiscal_year": source["fiscal_year"],
                "account_label": ingestion["options"]["fund_label"],
                "document_phase": source["document_phase"],
                "direction": profile["direction"]}
    if "target" in profile:
        return profile["target"]
    if "edition_index" in profile:
        return source["editions"][profile["edition_index"]]
    return {name: source.get(name) for name in (
        "jurisdiction", "fiscal_year", "document_phase", "account_labels", "directions",
    )}


def _landing(source: dict, ingestion: dict) -> str:
    index = ingestion.get("profile", {}).get("publication_index")
    return source["landing_url"] if index is None else source["publication_links"][index]["url"]


def _download(source: dict) -> str:
    acquisition = source.get("acquisition", {"method": "direct"})
    if acquisition["method"] != "wayback":
        return source["download_url"]
    capture = acquisition["capture"]
    datetime.strptime(capture, "%Y%m%d%H%M%S")
    url = urlsplit(source["download_url"])
    original = urlunsplit(url._replace(scheme=acquisition["original_scheme"]))
    return f"https://web.archive.org/web/{capture}id_/{original}"


def _referenced_source(source_id: object, sources: dict[str, dict], where: str) -> dict:
    if not isinstance(source_id, str) or source_id not in sources:
        raise ValueError(f"{where}: unknown origin reference {source_id!r}")
    return sources[source_id]


def _reference(value: object, sources: dict[str, dict], where: str) -> object:
    """Resolve document references used by multi-original history declarations."""
    if isinstance(value, list):
        return [_reference(child, sources, f"{where}[{index}]") for index, child in enumerate(value)]
    if not isinstance(value, dict):
        return value
    if "source_id" in value:
        source = _referenced_source(value["source_id"], sources, where + ".source_id")
        if set(value) - {"source_id", "options", "approval_source_id"}:
            raise ValueError("An origin reference supports source_id, options and approval_source_id only")
        if not isinstance(value.get("options", {}), dict):
            raise ValueError("An origin reference options value must be an object")
        result = _reference(value.get("options", {}), sources, where + ".options")
        result["url"] = source["download_url"]
        if "approval_source_id" in value:
            approval = _referenced_source(value["approval_source_id"], sources, where + ".approval_source_id")
            result["approval_url"] = approval["download_url"]
        return result
    if "approval_source_id" in value:
        raise ValueError(f"{where}: approval_source_id requires a document source_id")
    return {name: _reference(child, sources, f"{where}.{name}") for name, child in value.items()}


def _merge(target: dict, incoming: dict, where: str) -> None:
    for name, value in incoming.items():
        if name in target and target[name] != value:
            raise ValueError(f"{where}: conflicting {name} declarations")
        target[name] = value


def _enabled_ingestions(inventory: dict) -> list[tuple[dict, dict]]:
    registrations = [
        (source, ingestion)
        for source in inventory["sources"]
        for ingestion in source.get("ingestions", [])
        if ingestion["enabled"]
    ]
    ordered = sorted(enumerate(registrations), key=lambda item: item[1][1].get("order", item[0]))
    return [registration for _, registration in ordered]


def _reference_ids(value: object) -> list[str]:
    ids = []
    if isinstance(value, dict):
        for name, child in value.items():
            if name in ("source_id", "approval_source_id"):
                ids.append(child)
            else:
                ids.extend(_reference_ids(child))
    elif isinstance(value, list):
        for child in value:
            ids.extend(_reference_ids(child))
    return list(dict.fromkeys(ids))


def project_sources(inventory: dict) -> dict:
    """Return the root sources.toml dictionary shape for existing validators.

    Only enabled ingestion registrations participate. Candidate selection and
    fixed-input presence never enable an ingestion.
    """
    sources = {source["id"]: source for source in inventory["sources"]}
    projected: dict = {"catalog": deepcopy(inventory.get("acquisition_catalogs", {}))}
    for source, ingestion in _enabled_ingestions(inventory):
        section, key = ingestion["section"], ingestion["key"]
        spec = _reference(ingestion["options"], sources, f"{section}.{key}.options")
        if section == "csv":
            resource = spec.pop("resource")
            spec["landing_page"] = _landing(source, ingestion)
            acquisition = source.get("acquisition", {"method": "direct"})
            if acquisition["method"] in ("direct", "wayback"):
                resource["url"] = _download(source)
            elif acquisition["method"] == "ckan":
                if acquisition["catalog"] not in projected["catalog"]:
                    raise ValueError(f"{source['id']}: unknown acquisition catalog")
                spec["catalog"] = acquisition["catalog"]
            else:
                raise ValueError(f"{source['id']}: unsupported acquisition method")
            block = projected.setdefault(key, {"resources": []})
            _merge(block, spec, key)
            if resource in block["resources"]:
                raise ValueError(f"{key}: duplicate resource registration")
            block["resources"].append(resource)
        else:
            if section == "initial_detail":
                if "coverage_source_id" in spec:
                    raise ValueError(f"{section}.{key}: the containing origin supplies coverage_source_id")
                spec["coverage_source_id"] = source["id"]
            if section == "recovered_initial_detail":
                spec["original_url"] = source["download_url"]
                spec["wayback_url"] = _download(source)
                spec["wayback_capture"] = source["acquisition"]["capture"]
                spec["landing_page"] = _landing(source, ingestion)
            elif section != "budget_history":
                spec["url"] = _download(source)
                if section not in ("project_names", "revenue_accounts"):
                    spec["landing_page"] = _landing(source, ingestion)
            else:
                spec["landing_page"] = _landing(source, ingestion)
            block = projected.setdefault(section, {})
            if key in block:
                raise ValueError(f"{section}.{key}: duplicate processing registration")
            block[key] = spec
    return projected


def acquisition_plan(inventory: dict) -> dict:
    """Describe registered work without invoking an acquisition or extractor."""
    projected = project_sources(inventory)
    tasks = []
    for source, ingestion in _enabled_ingestions(inventory):
        tasks.append(dict(
            source_id=source["id"], section=ingestion["section"], key=ingestion["key"],
            referenced_source_ids=_reference_ids(ingestion["options"]),
            acquisition=deepcopy(source.get("acquisition", {"method": "direct"})),
            download_url=_download(source), landing_url=_landing(source, ingestion),
            profile=deepcopy(ingestion.get("profile", {})),
            scope=deepcopy(_scope(source, ingestion)),
        ))
    return dict(schema_version=1, plan_only=True, network_requests=0,
        extraction_runs=0, fixed_inputs_changed=False, whole_public_scope_complete=False,
        tasks=tasks, projected_sources=projected)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=INVENTORY)
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--describe", action="store_true")
    output.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.describe:
        print(json.dumps(dict(schema_version=1, sections=SECTIONS,
            selection="explicit_ingestion_registration_and_enabled_only",
            output="acquisition_plan_and_legacy_section_projection", network_requests=0,
            extraction_runs=0, fixed_inputs_changed=False), ensure_ascii=False, indent=2))
        return
    try:
        plan = acquisition_plan(load_registry(args.inventory))
        if args.json:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            for task in plan["tasks"]:
                print(f"{task['section']}\t{task['key']}\t{task['source_id']}")
    except jsonschema.ValidationError as error:
        location = '.'.join(map(str, error.absolute_path)) or 'sources'
        print(f"source registry: {location}: {error.message}", file=sys.stderr)
        raise SystemExit(1) from error
    except (OSError, ValueError, KeyError, TypeError, jsonschema.SchemaError) as error:
        print(f"source registry: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
