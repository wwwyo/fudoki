# pipeline

原典から提供用データを作る層。実行手順は [README.md](README.md)、原典調査・取り込み・PDF抽出・dbt構築のハマりどころは `.agents/skills/pipeline/` を参照する。

## Scripts

script はこの package が所有する。実行は `bun run --cwd pipeline <name>`（または `pipeline/` で `bun run <name>`）。root の `pipeline:*` script はここへの forwarder で、入口となるものだけが root に残る。

| group | scripts |
|---|---|
| 固定入力・構築 | `inputs` / `inputs:migrate` / `acquire` / `build` / `fdp` |
| 観測・調査 | `survey:structure` / `eval:extraction` |
| 原典対象の管理 | `sources:plan` / `coverage:fiscal` |
| 取り込み・生成 | `extract:*` / `fetch:*` / `pdf:layer` |
| 検査 | `test`（bun）/ `test:python`（unittest） |

`verify/report`（`@fudoki/report`）と `verify/view`（`@fudoki/pipeline-view`）は別 package。検証報告の生成は `bun run --cwd pipeline/verify/report build`（root の `pipeline:report` と同じ）。

## 生成物・観測・取得の規約

- **commit した生成物には生成手段を残す。** 生成物だけ残して作り方を消すと、作り直せず検証もできない出所不明のデータになる。置き場は調査スクリプト置き場ではなく、生成物と consumer の近く。
- **観測は commit しない。** `ingestion/fiscal/observations/` に書き出し、主張に使うときは実測日を添える。
- **ネットワークを叩く script はサンドボックスを外して回し、CI では回さない。** 開発環境の HTTP プロキシが応答を途中で切り `IncompleteRead` が出る（取得元の問題と取り違えない。実測の詳細は `.agents/skills/pipeline/references/budget-extraction.md`）。

## 技術スタック

- **汎用層として作る**: 団体ごとの差は宣言（`ingestion/fiscal/sources.toml`・レイアウト定義）に置き、取得・変換・配布の処理を再利用できる形にする。「他自治体でも動く」をコードで示す
- **取得**: Python。原典 CSV/PDF のバイト列と取り込み Parquet を非公開 R2 に保存する。入力一覧 `sources.lock.json`（schemaVersion 3）で原典・表のハッシュとsource宣言をGit管理する。独立したprovenanceは出力しない。
- **OCR**: 共通実装は `ingestion/lib/ocr.py` の llama.cpp + GLM-OCR を使い、重みは `ocr-model.toml` の URL・SHA-256 で固定する。Apple Vision など別エンジンを選ぶ場合は、共通実装を使わない理由・比較評価の有無・エンジンの版と設定を原典別の宣言・コードに記録する。比較未実施なら精度の優位性を主張しない。文字層の抽出・文字対応表の復元を先に検討し、OCR は必要な頁・領域に限定してメモリ使用量を見ながら実行する。詳細は `.agents/skills/pipeline/references/budget-extraction.md` を参照する。
- **変換・検査**: dbt-duckdb。staging は原典の行と1対1、intermediate は構造・単位・科目・分類の統一、marts は提供する列と粒度を確定する。
- **検証**: Bun/TypeScript の `verify/report/` とループバック専用の view。系統・検査結果・原典との対応を確認する。
- **保存**: Git はコード・宣言・判断・入力一覧、非公開 R2 は原典・取り込み表。`.cache/` と `.build/` は再生成可能なローカル作業領域。

  | 内容 | 保存先 | Git |
  |---|---|---|
  | 原典 CSV/PDF、取り込み Parquet | 非公開 R2、個別の内容ハッシュ | 入力一覧だけ |
  | 原典・表の識別子、ハッシュ・保存先、source宣言 | `ingestion/fiscal/sources.lock.json`（schemaVersion 3） | 管理する |
  | 取得元・階層・金額段階の宣言、分類・名称の判断 | `ingestion/` と dbt seeds | 管理する |
  | 復元済み入力・PDF/OCR キャッシュ | `pipeline/.cache/` | 管理しない |
  | DuckDB・dbt manifest・検査結果・ローカル報告 | `pipeline/.build/` | 管理しない |

  再構築に必要な原典・取り込み表・コード・宣言を保持する。独立したprovenanceファイルは生成・保存しない。原典・取り込み表の遠隔保管と復元は確認済みで、repo 内の `data/` は廃止した。
- **一時検証の保存**: `.agent/` へ runtime・依存物・原典群・キャッシュ・全量 warehouse を検証ごとに複製しない。ハッシュ固定した既存原典を読み取り参照し、変更コードのスナップショット・ハッシュ一覧・対象範囲の再抽出と検査結果を保存する。全件走査・全ファイルのハッシュ計算は対象を絞る。採用後の再生成可能な一時DB・重複CSVは整理するが、未採用の原典・取り込み表・支持コード・証跡は保持する。

**Python の版は 3.13 に固定してある。** dbt-duckdb 1.11.0 が classifiers で 3.14 を宣言していないため（`requires-python` は `>=3.10` なので入りはするが、テストされていない組み合わせになる）。

`build` は固定入力から dbt・marts の CSV を生成し、同じ構築 ID の再実行では CSV のハッシュを照合する。

**系統（lineage）は dbt の `manifest.json` から取る。** 手で書かない。
段とノードを手作りすると、パイプラインを変えても図が変わらない状態を作る（実際に作った）。

## 参照

- 団体固有の実測・原典の癖 → `ingestion/fiscal/jurisdictions/<団体コード>.md`
- パイプライン（取得・PDF抽出・dbt）のハマりどころ → `.agents/skills/pipeline/`
