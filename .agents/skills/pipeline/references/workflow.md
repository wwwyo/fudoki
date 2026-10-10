# 原典選定から取り込み・提供用データまで

## フローを原典の形式で分ける

取り込みのフローは、原典選定・保存 → 形式別の取り込みと検査 → 取り込み表・管理情報の保存まで。dbt側は保存済みParquetと管理情報を読み、入力準備・モデル構築を行う。提供用データの構築後に収録範囲を監査する。

| 原典の形式 | 取り込み完了の条件 | 実装の状態 |
| --- | --- | --- |
| ヘッダー付きCSV | 原典を読み直した全セル・列・行順・重複・空欄・物理行範囲がParquetと一致する | 共通CSV変換で自動検査。不一致は保存前に停止する |
| text PDF | 文字保持・原典との対応を確認し、階層ごとの合計検査→不一致の修正→再検査を行う | 共通実装・書式別の停止条件は未完了 |
| scan PDF | OCRの観測と表への対応を確認し、階層ごとの合計検査→不一致の修正→再検査を行う | OCR・再読の手順はある。合計検査の共通実装は未完了 |

形式別の検査は [candidate-validation](candidate-validation.md)、取り込みの手順は [ingestion](ingestion.md) を読む。

## 保存と採用の境界

- 変換と保存の入口は `ingestion:convert`。ローカル実行は候補Parquet・候補manifest・形式別の検査結果を返し、`--remote` は全表の保存成功後に対象別JSONを更新する。手順は [ingestion](ingestion.md#管理jsonを確認して変換する)。
- `ingestion:check` は管理情報・選定・scope・fingerprintの検査で、財政値の正しさを認定しない。
- 原典はsource_selection、表は対象・方向別のingestion領域に保存し、保存先と原典参照は対象別JSONに置く。独立したprovenanceファイルは作らない。
- F（dbt）は対象別JSONと保存済みParquetを読む。検証報告・通常監査Gには旧 `sources.lock.json` を使う経路が残る（[input-storage](input-storage.md)、[移行記録](../../../../docs/prd/ingestion-storage/migration.md)）。

## 後段で確認すること

年度・会計・単位・金額段階の解釈、staging、単位換算・分類・集約は [dbt](dbt.md) で確認する。取り込みの保存成功と後段の構築成功、採用分の構築成功と全公開資料の収録完了（[通常監査](coverage-audit.md)）を分ける。抽出器の変更時の再現性は [reconstruction](reconstruction.md) を参照する。
