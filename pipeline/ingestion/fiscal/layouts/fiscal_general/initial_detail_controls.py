"""Independent printed first-table controls for supported Komae initial books."""
import re


def first_table_hierarchy(pdf, candidate, detail_controls, first_article):
    from ingestion.fiscal.layouts.fiscal_general.extract_initial_expenditure import chars_of, rows_of, text, norm, location, number
    detail = {(h['level'], h['kan_code'], h.get('kou_code')): h for h in detail_controls}
    active = False
    units = kan = total = None
    seen = set()
    checks = []
    for page, chars in enumerate(chars_of(pdf, candidate['first_page'], candidate['last_page']), candidate['first_page']):
        for row in rows_of(chars):
            whole = norm(text(row))
            if whole == '歳出':
                active = True
                units = kan = None
                continue
            if not active:
                continue
            if '金額(千円)' in whole:
                units = location(row, page, 560, 710)
                continue
            if whole.startswith('歳出合計'):
                total = dict(amount_initial=number(norm(text(row, 560, 710))), location=location(row, page, 0, 710))
                active = False
                continue
            kh = re.fullmatch(r'(\d+)\.(.+)', norm(text(row, 60, 315)))
            qh = re.fullmatch(r'(\d+)\.(.+)', norm(text(row, 315, 560)))
            amount = norm(text(row, 560, 710))
            if kh:
                kan = kh[1]
            if not re.fullmatch(r'[△\-]?\d[\d,]*', amount):
                continue
            if units is None:
                raise ValueError('Missing printed first-table expenditure unit')
            if qh:
                level, code, label = 'kou', qh[1], qh[2]
                key = (level, kan, code)
            elif kh:
                level, code, label = 'kan', kh[1], kh[2]
                key = (level, code, None)
            else:
                raise ValueError('First-table expenditure amount lacks observed kan/kou')
            header = detail.get(key)
            if key in seen or header is None or header['amount_initial'] != number(amount) or header['label'] != label or not header['complete']:
                raise ValueError(f'First-table/detail hierarchy disagreement: {key}')
            seen.add(key)
            checks.append(dict(level=level, kan_code=kan, kou_code=code if level == 'kou' else None,
                printed_label=label, printed_amount_text=text(row, 560, 710), amount_initial=number(amount),
                source_amount_unit='千円', first_table_location=location(row, page, 60, 710),
                unit_evidence=units, detail_header_control=header, complete=True))
    if set(detail) != seen or total is None or total['amount_initial'] != first_article['amount_initial']:
        raise ValueError('First-table/detail hierarchy scope or first-article total differs')
    return checks
