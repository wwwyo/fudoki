# pipeline

原典から提供用データを作る層。実行手順と、原典調査・取り込み・PDF抽出・dbt構築のハマりどころは `.agents/skills/pipeline/` を参照する。

## Scripts

script はこの package が所有する。実行は `bun run --cwd pipeline <name>`（または `pipeline/` で `bun run <name>`）。

| group | scripts |
|---|---|
| 取り込み・保存 | `ingestion:schema` / `ingestion:check` / `ingestion:originals` / `ingestion:convert` / `ingestion:restore` / `ingestion:cleanup` |
| 検査 | `test`（bun）/ `test:python`（unittest） |

原典選定は `bun pipeline/source_selection/check.ts` と `archive.ts`。dbt はマスタ（`dbt/seeds/`）と共通の正規化macroだけを持ち、モデルは新しい取り込み表から作り直す。

## 生成物・観測・取得の規約

- **commit した生成物には生成手段を残す。** 生成物だけ残して作り方を消すと、作り直せず検証もできない出所不明のデータになる。置き場は調査スクリプト置き場ではなく、生成物と consumer の近く。
- **観測は commit しない。** `ingestion/fiscal/observations/` に書き出し、主張に使うときは実測日を添える。
- **ネットワークを叩く script はサンドボックスを外して回し、CI では回さない。** 開発環境の HTTP プロキシが応答を途中で切り `IncompleteRead` が出る（取得元の問題と取り違えない。実測の詳細は `.agents/skills/pipeline/references/ingestion.md`）。

## 技術スタック

- **汎用層として作る**: 団体ごとの差は原典選定の宣言・書式設定に置き、取得・変換の処理を再利用できる形にする。「他自治体でも動く」をコードで示す。
- **schema・宣言は最小形から始める**: フィールドは原則 nullable にし、必須化・union 型化・汎用 scope 枠のような拡張は実例が出てから足す。最初から過剰な提案を出すとユーザーに削らせる往復になる（2026-10、source_selection schema の scope/inspection を連続して削らせた観測）。
- **取り込み**: Bは選定済みのCSV/PDFと対象情報を受け取り、ローカルParquetへ変換する。管理JSONはschema_version 1で入出力と変換だけを持ち、型は `ingestion/fiscal/manifest.schema.json`、対象間の制約は `manifest.py`。CLIとCIで `ingestion:check` を実行する。配置と保存の手順は [ingestion手順](../.agents/skills/pipeline/references/ingestion.md)、判断は [保存設計](../docs/prd/ingestion-storage/design-doc.md) を参照する。
- **コード配置**: 共通処理は `ingestion/lib/`、書式別の共通処理は `ingestion/fiscal/layouts/`、団体固有のコードと宣言は `ingestion/fiscal/jurisdictions/<団体>/layouts/`。年度・会計だけでコードを複製しない。
- **OCR**: 新しいBの共通入口は `ingestion/lib/scan_ocr.py`。既定はPaddleOCR smallの縮小検出・原解像度認識で、再読領域は書式設定から渡す。Apple Visionも `backend="vision"` と既存の `vision_ocr.py` で使える。設定と検証範囲は [OCRの説明](ingestion/lib/scan_ocr.md)、実行と欠落セルの再読は `.agents/skills/pipeline/references/ingestion.md` を参照する。
- **変換**: dbt-duckdb。モデルは新しい取り込み表から作り直す（現在はマスタseedsと正規化macroのみ）。
- **保存**: Git はコード・宣言・判断・入力一覧、非公開 R2 は原典・取り込み表。`.cache/` と `.build/` は再生成可能なローカル作業領域。

  | 内容 | 保存先 | Git |
  |---|---|---|
  | 原典 CSV/PDF | 非公開R2の `fiscal/source-selection/` | 選定・保存参照だけ |
  | 取り込みParquet | 非公開R2の `fiscal/ingestion/<対象>/<方向>/` の固定key | 対象別JSONだけ |
  | 変換設定・現在の表・ハッシュ・保存先 | `ingestion/fiscal/jurisdictions/<団体>/<年度>/<資料区分>/<方向>.json` | 管理する |
  | 分類・名称のマスタ | dbt seeds | 管理する |
  | 復元済み入力・PDF/OCR キャッシュ | `pipeline/.cache/` | 管理しない |
  | DuckDB・dbt manifest・検査結果・ローカル報告 | `pipeline/.build/` | 管理しない |

  再構築に必要な原典・取り込み表・コード・宣言を保持する。独立したprovenanceファイルは生成・保存しない。
- **一時検証の保存**: `.agent/` へ runtime・依存物・原典群・キャッシュ・全量 warehouse を検証ごとに複製しない。ハッシュ固定した既存原典を読み取り参照し、変更コードのスナップショット・ハッシュ一覧・対象範囲の再抽出と検査結果を保存する。全件走査・全ファイルのハッシュ計算は対象を絞る。採用後の再生成可能な一時DB・重複CSVは整理するが、未採用の原典・取り込み表・支持コード・証跡は保持する。

**Python の版は 3.13 に固定してある。** dbt-duckdb 1.11.0 が classifiers で 3.14 を宣言していないため（`requires-python` は `>=3.10` なので入りはするが、テストされていない組み合わせになる）。

## 参照

- 団体固有の実測・原典の癖 → `ingestion/fiscal/jurisdictions/<団体コード>/README.md`
- パイプライン（選定・取り込み・PDF抽出・dbt）の手順 → `.agents/skills/pipeline/`
