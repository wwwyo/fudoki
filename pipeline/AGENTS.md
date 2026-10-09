# pipeline

原典から提供用データを作る層。実行手順は [README.md](README.md)、原典調査・取り込み・PDF抽出・dbt構築のハマりどころは `.agents/skills/pipeline/` を参照する。

## Scripts

script はこの package が所有する。実行は `bun run --cwd pipeline <name>`（または `pipeline/` で `bun run <name>`）。root の `pipeline:*` script はここへの forwarder で、入口となるものだけが root に残る。

| group | scripts |
|---|---|
| 固定入力・構築 | `inputs` / `inputs:migrate` / `acquire` / `build` / `fdp` |
| 観測・調査 | `survey:structure` / `eval:extraction` |
| 原典対象の管理 | `sources:plan` / `coverage:fiscal` |
| 取り込み・保存 | `ingestion:schema` / `ingestion:check` / `ingestion:originals` / `ingestion:convert` / `ingestion:restore` / `ingestion:cleanup` / `ingestion:migrate` |
| 旧候補の生成・調査 | `extract:*` / `fetch:*` / `pdf:layer` |
| 検査 | `test`（bun）/ `test:python`（unittest） |

`verify/report`（`@fudoki/report`）と `verify/view`（`@fudoki/pipeline-view`）は別 package。検証報告の生成は `bun run --cwd pipeline/verify/report build`（root の `pipeline:report` と同じ）。

## 生成物・観測・取得の規約

- **commit した生成物には生成手段を残す。** 生成物だけ残して作り方を消すと、作り直せず検証もできない出所不明のデータになる。置き場は調査スクリプト置き場ではなく、生成物と consumer の近く。
- **観測は commit しない。** `ingestion/fiscal/observations/` に書き出し、主張に使うときは実測日を添える。
- **ネットワークを叩く script はサンドボックスを外して回し、CI では回さない。** 開発環境の HTTP プロキシが応答を途中で切り `IncompleteRead` が出る（取得元の問題と取り違えない。実測の詳細は `.agents/skills/pipeline/references/ingestion.md`）。

## 技術スタック

- **汎用層として作る**: 団体ごとの差は原典選定の宣言・書式設定に置き、取得・変換の処理を再利用できる形にする。「他自治体でも動く」をコードで示す。
- **schema・宣言は最小形から始める**: フィールドは原則 nullable にし、必須化・union 型化・汎用 scope 枠のような拡張は実例が出てから足す。最初から過剰な提案を出すとユーザーに削らせる往復になる（2026-10、source_selection schema の scope/inspection を連続して削らせた観測）。
- **取り込み**: Bは選定済みのCSV/PDFと対象情報を受け取り、ローカルParquetへ変換する。管理JSONはschema_version 2で入出力と変換だけを持ち、型は `ingestion/fiscal/manifest.schema.json`、対象間の制約は `manifest.py`。CLIとCIで `ingestion:check` を実行する。配置と保存の手順は [README](README.md)、判断は [保存設計](../docs/prd/ingestion-storage/design-doc.md) を参照する。
- **コード配置**: 共通処理は `ingestion/lib/`、書式別の共通処理は `ingestion/fiscal/layouts/`、団体固有のコードと宣言は `ingestion/fiscal/jurisdictions/<団体>/layouts/`。年度・会計だけでコードを複製しない。既存の原典登録・収録監査は `fiscal/management/`。
- **OCR**: 新しいBは `ingestion/lib/vision_ocr.py` を使う。選定理由は [ADR 0017](../docs/adr/0017-vision-for-coordinate-preserving-ocr.md)、実行と欠落セルの再読は `.agents/skills/pipeline/references/ingestion.md` を参照する。旧GLM等の抽出器は移行済みコードとして残し、今回の配置変更を精度の再検証と解釈しない。
- **変換・検査**: dbt-duckdb。staging は原典の行と1対1、intermediate は構造・単位・科目・分類の統一、marts は提供する列と粒度を確定する。
- **検証**: Bun/TypeScript の `verify/report/` とループバック専用の view。系統・検査結果・原典との対応を確認する。
- **保存**: Git はコード・宣言・判断・入力一覧、非公開 R2 は原典・取り込み表。`.cache/` と `.build/` は再生成可能なローカル作業領域。

  | 内容 | 保存先 | Git |
  |---|---|---|
  | 原典 CSV/PDF | 非公開R2の `fiscal/source-selection/` | 選定・保存参照だけ |
  | 取り込みParquet | 非公開R2の `fiscal/ingestion/<対象>/<方向>/` の固定key | 対象別JSONだけ |
  | 変換設定・現在の表・ハッシュ・保存先 | `ingestion/fiscal/jurisdictions/<団体>/<年度>/<資料区分>/<方向>.json` | 管理する |
  | 旧検査・監査の固定入力 | `ingestion/fiscal/sources.lock.json`（schemaVersion 3、読み取り互換用） | 新しいBでは更新しない |
  | 取得元・階層・金額段階の宣言、分類・名称の判断 | `ingestion/` と dbt seeds | 管理する |
  | 復元済み入力・PDF/OCR キャッシュ | `pipeline/.cache/` | 管理しない |
  | DuckDB・dbt manifest・検査結果・ローカル報告 | `pipeline/.build/` | 管理しない |

  再構築に必要な原典・取り込み表・コード・宣言を保持する。独立したprovenanceファイルは生成・保存しない。新しいR2構造への移行状況は [移行記録](../docs/prd/ingestion-storage/migration.md) を参照する。新しいBから旧原典領域へのアップロードと旧入力一覧への採用は拒否する。
- **一時検証の保存**: `.agent/` へ runtime・依存物・原典群・キャッシュ・全量 warehouse を検証ごとに複製しない。ハッシュ固定した既存原典を読み取り参照し、変更コードのスナップショット・ハッシュ一覧・対象範囲の再抽出と検査結果を保存する。全件走査・全ファイルのハッシュ計算は対象を絞る。採用後の再生成可能な一時DB・重複CSVは整理するが、未採用の原典・取り込み表・支持コード・証跡は保持する。

**Python の版は 3.13 に固定してある。** dbt-duckdb 1.11.0 が classifiers で 3.14 を宣言していないため（`requires-python` は `>=3.10` なので入りはするが、テストされていない組み合わせになる）。

`inputs` は対象別JSONから保存済みParquetを復元する。`build --declarations <DIR>` はParquetと確定済み `sources.json`・`history.json` を固定してdbt・martsのCSVを生成し、同じ構築IDの再実行ではCSVのハッシュを照合する。Cの再実行は行わない。実装は `build_inputs.py` と `build.ts`。dbt用の配置は `dbt/inputs/` に分離し、`dbt_inputs.py` と `dbt:inputs:check` で検査する。後工程の宣言を取り込みfingerprintへ混ぜない。

**系統（lineage）は dbt の `manifest.json` から取る。** 手で書かない。
段とノードを手作りすると、パイプラインを変えても図が変わらない状態を作る（実際に作った）。

## 参照

- 団体固有の実測・原典の癖 → `ingestion/fiscal/jurisdictions/<団体コード>/README.md`
- パイプライン（取得・PDF抽出・dbt）のハマりどころ → `.agents/skills/pipeline/`
