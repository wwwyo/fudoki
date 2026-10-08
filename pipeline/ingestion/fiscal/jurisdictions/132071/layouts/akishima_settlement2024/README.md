# akishima_settlement2024

昭島市 令和6年度（FY2024）各会計歳入歳出決算書の有限復元プロバイダ。原典は全項版 PDF
`r6kessan0.pdf`（SHA256 `20802834f53ef0a92ff9098bf05bd162cc603de55a998529f041008addcaaf71`、
3,869,356 bytes、651 物理頁）一冊。分割公開 PDF は頁観測証跡であり、財務入力として採用しない。

- 入力は 6 つの不変オブジェクトのみ（原典 PDF・ネイティブ bbox・有限設定・認定 HTML・
  国民健康保険会計概要の原典直接セル台帳とラスタ）。候補表・診断・旧出力は入力にしない。
- 出力は会計別の型付き表 18 本（financial/controls/projects × 6 会計）と物理頁棚卸 1 本。
- `financial` は 目×印刷された法定節 の粒度で `executed`（支出済額）。予算系列は非加算の参照。
- `statutory_setsu_id` は全行 NULL。法定節への対応は印刷コード＋正確な名称＋適用年度の
  判断列（1,006 confirmed / 14 名称不一致 / 6 空白予備費）として分離する。
- 事業備考の 3 桁番号は印刷された備考序数であり、法定節でも安定した事業コードでもない。
  左頁コードの事業への転記・名寄せ・按分・残余計算は行わない。

```sh
PYTHONPATH=code/pipeline PYTHONDONTWRITEBYTECODE=1 python -m ingestion.fiscal.jurisdictions.132071.layouts.akishima_settlement2024 schema
PYTHONPATH=code/pipeline PYTHONDONTWRITEBYTECODE=1 python -m ingestion.fiscal.jurisdictions.132071.layouts.akishima_settlement2024 build --params '{"cache":"immutable","manifest":"immutable/manifest.json","output":"warehouse"}'
PYTHONPATH=code/pipeline PYTHONDONTWRITEBYTECODE=1 python -m ingestion.fiscal.jurisdictions.132071.layouts.akishima_settlement2024 restore-evidence --params '{"cache":"immutable","manifest":"immutable/manifest.json","output":"restored-immutable"}'
```

CLI は JSON エンベロープのみを出力し、未知のパラメータ・既定のキャッシュ/出力経路・
ネットワーク・OCR を一切持たない。`dry_run` は不変オブジェクトと認定行だけを検査する。
