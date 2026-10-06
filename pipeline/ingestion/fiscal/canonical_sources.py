"""Select one publisher source per fiscal scope without downloading or hashing originals."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import json
from pathlib import Path
import sys
import unicodedata

HERE = Path(__file__).resolve().parent
KINDS = {'initial': 'budget', 'supplementary': 'supplementary', 'settlement': 'settlement'}
READABILITY = {'structured': 3, 'text_pdf': 2, 'image_pdf': 1, 'unknown': 0}
SELECTION_PRIORITY = ['latest_publisher_revision', 'machine_readability', 'official_fiscal_page']
DETAIL_LEVELS = {'moku', 'project', 'jikou', 'saimoku', 'jigyo', 'daijigyo', 'chujigyo', 'shojigyo'}


def account_label(value: str, code: str, *, csv: bool = False) -> str:
    value = ''.join(unicodedata.normalize('NFKC', value).split())
    # Only Mitaka's declared prefix2 CSV layout separates the first two digits.
    if csv and code == '132047' and len(value) > 2 and value[:2].isascii() and value[:2].isdigit():
        value = value[2:]
    return value


def readability(source: dict, declaration: dict) -> str:
    if declaration.get('readability'):
        return declaration['readability']
    if source['format'] == 'csv':
        return 'structured'
    status = source['content_inspection']['status']
    return {'text_probed': 'text_pdf', 'image_only': 'image_pdf'}.get(status, 'unknown')


def load_policy(path: Path, source_ids: set[str]) -> dict:
    policy = json.loads(path.read_text())
    if policy['schema_version'] != 1:
        raise ValueError('Unsupported source selection policy version')
    if policy['selection']['priority'] != SELECTION_PRIORITY:
        raise ValueError('Unsupported canonical selection priority')
    if policy['selection']['machine_readability'] != list(READABILITY):
        raise ValueError('Unsupported machine readability order')
    for source_id, declaration in policy['sources'].items():
        if source_id not in source_ids:
            raise ValueError(f'Unknown declared source: {source_id}')
        if declaration.get('readability') not in (None, *READABILITY):
            raise ValueError(f'Unknown readability: {source_id}')
        if declaration.get('role') not in (None, 'reference'):
            raise ValueError(f'Unknown source role: {source_id}')
        if declaration.get('revision_at'):
            date.fromisoformat(declaration['revision_at'])
        if (declaration.get('revision_at') or declaration.get('revision_id') or declaration.get('role')) and not (
            declaration.get('basis') and declaration.get('evidence_urls')
        ):
            raise ValueError(f'Source declaration needs publisher evidence: {source_id}')
    return policy


def choose(candidates: list[dict]) -> tuple[dict, str]:
    dates = [c['revision_at'] for c in candidates]
    revisions = {c['revision_id'] for c in candidates}
    if all(dates):
        newest = max(dates)
        eligible = [c for c in candidates if c['revision_at'] == newest]
        status = 'selected_latest_declared'
    elif len(revisions) == 1 and None not in revisions:
        eligible = candidates
        status = 'selected_same_declared_revision'
    elif len(candidates) == 1:
        eligible = candidates
        status = 'selected_only_candidate'
    else:
        # A preferred candidate is useful for planning; unknown revision order
        # must not become a claim that the newest edition has been selected.
        eligible = candidates
        status = 'revision_order_unconfirmed'
    preferred = min(eligible, key=lambda c: (
        -READABILITY[c['readability']], -c['publisher_priority'], c['source_id']
    ))
    return preferred, status


def report(inventory: dict, lock: dict, policy: dict) -> dict:
    by_url: dict[str, list[dict]] = defaultdict(list)
    for entry in lock['entries']:
        source = entry['source']
        for url in {source.get(k) for k in ('request_url', 'final_url', 'original_url', 'source_url')} - {None}:
            by_url[url].append(entry)
    groups: dict[tuple, dict[str, dict]] = defaultdict(dict)
    unclassified = []
    excluded = []
    references = []
    for source in inventory['sources']:
        sid = source['id']
        declaration = policy['sources'].get(sid, {})
        title = ''.join(unicodedata.normalize('NFKC', source['document_title']).split())
        cover_only = title.startswith('表紙・目次(') or title == '表紙・目次'
        if source['role'] != 'statement' or declaration.get('role') == 'reference' or cover_only:
            references.append(sid)
            continue
        if source['in_scope']['status'] == 'excluded':
            excluded.append(sid)
            continue
        directions = source.get('directions', [])
        has_adopted_expenditure = any(
            e['direction'] == 'expenditure' and e['jurisdiction'] == source['jurisdiction']
            and e['fiscalYear'] == source['fiscal_year']
            for e in by_url.get(source['download_url'], [])
        )
        if directions == ['revenue'] and not has_adopted_expenditure:
            references.append(sid)
            continue
        scopes = source['editions'] or [dict(
            fiscal_year=source['fiscal_year'], account_label=label,
            document_phase=source['document_phase'], amendment_number=None,
        ) for label in source['account_labels']]
        unresolved = set()
        for scope in scopes:
            year, phase = scope['fiscal_year'], scope['document_phase']
            account = account_label(scope['account_label'], source['jurisdiction'], csv=source['format'] == 'csv')
            number = scope['amendment_number']
            reasons = []
            edition_direction = scope.get('content_confirmation', {}).get('direction')
            if edition_direction == 'revenue':
                continue
            if edition_direction != 'expenditure' and 'expenditure' not in directions and not has_adopted_expenditure:
                reasons.append('expenditure_direction_unconfirmed')
            grain = scope.get('content_grain', source.get('content_grain', {}))
            if not DETAIL_LEVELS.intersection(grain.get('observed_levels', [])):
                reasons.append('moku_or_project_detail_not_observed')
            headers = [e['text'] for e in source['content_inspection'].get('evidence', [])
                       if e.get('kind') == 'hierarchy_table_header']
            if headers and all('目次' in ''.join(h.split()) for h in headers):
                reasons.append('detail_observation_only_in_contents')
            if not year or phase not in KINDS:
                reasons.append('year_or_document_kind_unconfirmed')
            if not account or '未確認' in account or '各会計' in account:
                reasons.append('account_unconfirmed')
            if phase == 'supplementary' and number is None:
                reasons.append('amendment_number_unconfirmed')
            if scope.get('in_scope', {}).get('status') == 'excluded':
                continue
            if reasons:
                unresolved.update(reasons)
                continue
            key = (source['jurisdiction'], year, account, phase, number)
            entries = []
            document_entries = []
            for entry in by_url.get(source['download_url'], []):
                if (entry['jurisdiction'], entry['fiscalYear'], entry['documentKind'], entry['direction']) != (
                    key[0], year, KINDS[phase], 'expenditure'
                ):
                    continue
                es = entry['source']
                observed_edition = source['content_inspection'].get('sha256')
                # Reuse existing seals for adoption, never for canonical selection.
                if observed_edition and entry['originEdition'] != observed_edition:
                    continue
                if phase == 'supplementary' and str(es.get('amendment_number')) != str(number):
                    continue
                fund = es.get('fund_label') or es.get('account')
                if fund and account_label(str(fund), key[0], csv=source['format'] == 'csv') != account:
                    continue
                whole_csv = (source['format'] == 'csv' and source['account_scope_status'] == 'content_inspected'
                             and es.get('raw_form') == 'verbatim'
                             and not any(es.get(k) for k in ('table_id', 'pages', 'source_page_range', 'configured_attachment_pages')))
                if not fund and not whole_csv:
                    document_entries.append(entry['path'])
                    continue
                entries.append(entry['path'])
            heading = source['listing_evidence'].get('heading', '')
            publisher_priority = declaration.get('publisher_priority', 0)
            if not publisher_priority:
                publisher_priority = 2 if '財政情報' in heading else 1
            groups[key][sid] = dict(
                source_id=sid, title=source['document_title'], url=source['download_url'],
                landing_url=source['landing_url'], format=source['format'],
                readability=readability(source, declaration),
                revision_at=declaration.get('revision_at'), revision_id=declaration.get('revision_id'),
                revision_basis=declaration.get('basis'), publisher_priority=publisher_priority,
                adopted_input_paths=sorted(set(entries)),
                document_level_adopted_input_paths=sorted(set(document_entries)),
                inspection_status=source['content_inspection']['status'],
                scope_confirmation=source['account_scope_status'],
            )
        if unresolved or not scopes:
            unclassified.append(dict(source_id=sid, jurisdiction=source['jurisdiction'],
                fiscal_year=source['fiscal_year'], document_phase=source['document_phase'],
                title=source['document_title'], url=source['download_url'],
                reasons=sorted(unresolved) or ['account_unconfirmed']))
    result = []
    entries_by_scope: dict[tuple, list[str]] = defaultdict(list)
    for entry in lock['entries']:
        es = entry['source']
        fund = es.get('fund_label') or es.get('account')
        phase = next((phase for phase, kind in KINDS.items() if kind == entry['documentKind']), None)
        if not fund or not phase or entry['direction'] != 'expenditure':
            continue
        number = es.get('amendment_number') if phase == 'supplementary' else None
        if phase == 'supplementary' and number is None:
            continue
        if number is not None:
            number = int(number)
        account = account_label(str(fund), entry['jurisdiction'])
        entries_by_scope[(entry['jurisdiction'], entry['fiscalYear'], account, phase, number)].append(entry['path'])
    for key, sources in sorted(groups.items(), key=lambda item: str(item[0])):
        candidates = sorted(sources.values(), key=lambda c: c['source_id'])
        preferred, status = choose(candidates)
        any_adopted = any(c['adopted_input_paths'] for c in candidates)
        if preferred['adopted_input_paths']:
            adoption = 'preferred_has_adopted_inputs'
        elif any_adopted:
            adoption = 'only_alternative_has_adopted_inputs'
        else:
            if entries_by_scope.get(key):
                adoption = 'scope_has_other_adopted_inputs'
            elif any(c['document_level_adopted_input_paths'] for c in candidates):
                adoption = 'account_adoption_unconfirmed'
            else:
                adoption = 'no_candidate_has_adopted_inputs'
        result.append(dict(
            source_key=':'.join(str(v) for v in key), jurisdiction=key[0], fiscal_year=key[1],
            account_label=key[2], document_phase=key[3], amendment_number=key[4], direction='expenditure',
            canonical_source_id=preferred['source_id'] if status != 'revision_order_unconfirmed' else None,
            preferred_source_id=preferred['source_id'], selection_status=status,
            adoption_status=adoption, candidates=candidates,
            other_scope_adopted_input_paths=sorted(set(entries_by_scope.get(key, []))),
        ))
    counts = Counter(g['adoption_status'] for g in result)
    return dict(
        schema_version=1, inventory_inspected_at=inventory['inspected_at'],
        policy=policy['selection'], network_requests=0, original_hashes_computed=0,
        whole_public_scope_complete=False, provided_data_verified=False,
        inventory_source_records=len(inventory['sources']), adopted_input_count=len(lock['entries']),
        counts=dict(logical_scopes=len(result), **counts,
            revision_order_unconfirmed=sum(g['selection_status'] == 'revision_order_unconfirmed' for g in result),
            unclassified_source_records=len(unclassified), reference_source_records=len(references),
            excluded_source_records=len(excluded)),
        jurisdictions=[dict(code=j['code'], name=j['name']) for j in inventory['jurisdictions']],
        groups=result, unclassified_sources=unclassified,
        search_gaps=[dict(jurisdiction=j['code'], **gap) for j in inventory['jurisdictions'] for gap in j['gaps']],
    )


def markdown(output: dict) -> str:
    names = {j['code']: j['name'] for j in output['jurisdictions']}
    phases = {'initial': '当初', 'supplementary': '補正', 'settlement': '決算'}
    missing = [g for g in output['groups'] if g['adoption_status'] == 'no_candidate_has_adopted_inputs']
    lines = ['# 原典対象ごとの採用対応がない範囲', '',
        '2026-10-06。既存の原典一覧と現在の固定入力の宣言を、取得・OCRなしで照合した結果。', '',
        f"対象は掲載 {output['inventory_source_records']} レコード、採用 {output['adopted_input_count']} 入力。全公開資料の探索完了ではない。", '',
        '## 選択ルール', '',
        '自治体・年度・会計・当初／補正号／決算ごとに、正式な最新版の中からCSV、文字PDF、画像PDFの順に選ぶ。同じ版・形式なら公式財政ページを優先する。', '',
        '版の順序が不明な場合は優先候補だけを示し、canonicalは未確定。確認日・ページ更新日・ファイル名の日付を改訂日にしない。新しい原典ハッシュの計算は0。', '',
        '## 集計', '', '| 自治体 | 採用対応なしの対象 | 他の掲載候補・原典に採用入力あり | 会計・号などの未確定資料 |',
        '|---|---:|---:|---:|']
    for code, name in names.items():
        groups = [g for g in output['groups'] if g['jurisdiction'] == code]
        no_adoption = sum(g['adoption_status'] == 'no_candidate_has_adopted_inputs' for g in groups)
        alternative = sum(g['adoption_status'] in ('only_alternative_has_adopted_inputs', 'scope_has_other_adopted_inputs') for g in groups)
        unclassified = sum(s['jurisdiction'] == code for s in output['unclassified_sources'])
        lines.append(f'| {name} | {no_adoption} | {alternative} | {unclassified} |')
    lines += ['', '件数は自治体×年度×会計×段階／補正号の対象数。一つのPDFに複数対象がある。旧451資料レコードとは分母が異なり、差分を処理済み件数にしない。', '',
        f"資料の採用入力はあるが会計への対応が不明な対象は {output['counts'].get('account_adoption_unconfirmed', 0)} 件。上の未採用へ加算せず、詳細はJSONの `account_adoption_unconfirmed` を参照する。CSVの全原文取り込みと観測済み会計集合が対応する場合だけ、会計ごとの入力存在へ反映する。", '',
        '採用入力ありは、一部の表・観測・別版の宣言が存在することまでであり、全明細・最新版・提供データの確認完了ではない。表紙・目次だけの資料を採用済み明細へ数えず、目次だけに基づく粒度の観測も未確認へ分ける。', '',
        f"同じ対象の版順未確認は {output['counts']['revision_order_unconfirmed']} 対象。以下の未採用数と重複するため加算しない。", '',
        '再生成: `bun run sources:canonical --markdown > docs/prd/fiscal-coverage/unadopted-sources-2026-10-06.md`。機械可読の全候補・採用path・未確定理由は `bun run sources:canonical --json`。', '',
        '## 採用対応がない対象の全一覧', '',
        '既存候補に紐づく入力も、同じ対象の会計名・年度・資料種別・補正号を明示する入力も見つからない対象。実未収録の確定には、未確定資料や一覧未登録の入力との対応確認が必要。', '',
        '| 自治体 | 年度 | 会計 | 段階／号 | 優先候補 | 版の順序 |', '|---|---:|---|---|---|---|']
    for group in missing:
        preferred = next(c for c in group['candidates'] if c['source_id'] == group['preferred_source_id'])
        phase = phases[group['document_phase']]
        if group['amendment_number'] is not None:
            phase += f"第{group['amendment_number']}号"
        state = {
            'revision_order_unconfirmed': '未確認',
            'selected_only_candidate': '候補1件（最新版の網羅確認なし）',
            'selected_same_declared_revision': '同じ版の宣言あり',
            'selected_latest_declared': '改訂日の根拠あり',
        }[group['selection_status']]
        title = preferred['title'].replace('|', '\\|').replace('\n', ' ')
        lines.append(f"| {names[group['jurisdiction']]} | {group['fiscal_year']} | {group['account_label']} | {phase} | [{title}]({preferred['url']}) | {state} |")
    lines += ['', '## 会計・補正号などが未確定の資料', '',
        'これらは対象に分類できず、上の未採用対象には加算していない。同じ資料が分類済み対象にも含まれる場合がある。', '',
        '| 自治体 | 掲載年度 | 掲載資料 | 未確定項目 |', '|---|---|---|---|']
    for source in output['unclassified_sources']:
        title = source['title'].replace('|', '\\|').replace('\n', ' ')
        lines.append(f"| {names[source['jurisdiction']]} | {source['fiscal_year'] or '不明'} | [{title}]({source['url']}) | {', '.join(source['reasons'])} |")
    return '\n'.join(lines) + '\n'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, default=HERE / 'coverage.json')
    parser.add_argument('--lock', type=Path, default=HERE / 'sources.lock.json')
    parser.add_argument('--policy', type=Path, default=HERE / 'source-selection.json')
    formats = parser.add_mutually_exclusive_group()
    formats.add_argument('--json', action='store_true')
    formats.add_argument('--markdown', action='store_true', help='Render a complete unadopted-scope list for review')
    parser.add_argument('--describe', action='store_true', help='Describe rules and output states without reading inputs')
    parser.add_argument('--missing-only', action='store_true', help='Show scopes with no adopted candidate; retain unresolved sources')
    args = parser.parse_args()
    if args.describe:
        print(json.dumps(dict(schema_version=1, scope=['jurisdiction', 'fiscal_year', 'account_label',
            'document_phase', 'amendment_number', 'direction'],
            priority=SELECTION_PRIORITY,
            readability=list(READABILITY), canonical_null_when='revision_order_unconfirmed',
            adoption_is='input_declaration_presence_only_not_full_scope_or_marts_verification',
            missing_filter='no_candidate_has_adopted_inputs', network_requests=0,
            original_hashes_computed=0), ensure_ascii=False, indent=2))
        return
    try:
        inventory = json.loads(args.inventory.read_text())
        lock = json.loads(args.lock.read_text())
        policy = load_policy(args.policy, {s['id'] for s in inventory['sources']})
        output = report(inventory, lock, policy)
        if args.missing_only:
            output['groups'] = [g for g in output['groups'] if g['adoption_status'] == 'no_candidate_has_adopted_inputs']
            output['filter'] = 'no_candidate_has_adopted_inputs'
        if args.markdown:
            if args.missing_only:
                raise ValueError('--markdown already includes the missing list; do not combine with --missing-only')
            print(markdown(output), end='')
        elif args.json:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(output['counts'], ensure_ascii=False))
            for group in output['groups']:
                preferred = next(c for c in group['candidates'] if c['source_id'] == group['preferred_source_id'])
                print(f"{group['source_key']}\t{group['adoption_status']}\t{group['selection_status']}\t{preferred['url']}")
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f'canonical sources: {error}', file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == '__main__':
    main()
