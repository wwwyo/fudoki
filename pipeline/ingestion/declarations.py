"""取得元の公開項目を dbt が読む宣言の形へ書き出す。"""

import json
from ingestion.fiscal.sources import all_sources


def main():
    rows = []
    for source in all_sources().values():
        for resource in source.resources:
            rows.append({
                'jurisdiction_code': source.jurisdiction_code,
                'fiscal_year': source.fiscal_year,
                'direction': resource.direction,
                'document_kind': source.document_kind,
                'source_json': json.dumps({
                    'documentKind': source.document_kind,
                    'documentLabel': source.document_label,
                    'landingPage': source.landing_page,
                    'licenseId': source.license_id,
                    'attribution': source.attribution,
                    'rawForm': source.raw_form,
                }, ensure_ascii=False, sort_keys=True),
            })
    print(json.dumps(rows, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
