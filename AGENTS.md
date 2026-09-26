# fudoki（風土記）

日本の地方自治体の**支出を事業単位（目）まで**構造化し、外部データと join 可能な形で配布する。

名前は『風土記』から。713年の官命により、諸国へ地名の由来や産物を**同じ様式で報告させて集めた**地誌で、各自治体から同じ形式でデータを集めるという本 PJ の構造がそのまま重なる。

## Story

支出データで何かを判断する人が、自治体の支出を事業の単位で、他の街や他の年と同じ物差しで比べられる。

Core actions:
- ある団体・年度の支出を事業の単位で見る — 月次
- 団体をまたいで、または年をまたいで比べる — 月次
- 数字が怪しいと思ったときに、原典と合っているか・誤読の罠が無いかを確かめる — 年数回

## Glossary

**原典（origin）**:
自治体が公開した予算・決算の資料そのもの（CSV または PDF）。
_Avoid_: ソース、元データ、生データ

**取り込み（ingestion / raw）**:
原典をそのまま表に読み込んだもの。値や単位は原典のまま。PDF の場合は組版からの抽出（抽出は復元検査が成り立たず、原典の内部で重複して印字された数字どうしの一致で確かめる）。
_Avoid_: パース、OCR（OCR は抽出の手段の1つ）

**正規化（staging）**:
列名や金額の単位（千円→円など）を共通の形に整えたもの。判断を含まない。

**判断（core）**:
自治体ごとの科目を共通の体系に写し、COFOG を割り当てる層。

**配布物（package）**:
団体ごとに fudoki が配る Fiscal Data Package。原典から生成した派生物であり、正本はリポジトリにある。
_Avoid_: 成果物、出力

**証跡（provenance）**:
原典をいつ・どこから・どの版の手順で取り込み、どう確かめたかの記録。
_Avoid_: ログ

**誤読の罠（caveat）**:
配布データの数字が、見た目どおりに読むと誤った結論になる箇所（予算段階の違い、会計間の二重計上、款の体系が法定と違う、など）。団体ごとに記録する。
_Avoid_: 注意点

## ディレクトリ構造

```
.
├── ingestion/        # 原典の取得と取得元の宣言（sources.toml）。団体固有の実測は budget/jurisdictions/
├── dbt/              # staging → core → package の変換と検査
├── fdp/              # Fiscal Data Package の生成
├── report/           # 報告データ（pipeline.json）の生成
├── apps/             # web（fudoki.dev。派生物）、api、slides
├── data/             # 原典・証跡・配布物（正本。commit する）
├── docs/             # プロジェクトの設計・調査文書（共有・tracked）
└── .agent/           # 個人メモ・試作（gitignore）
```

## セットアップ

ツールは mise で管理している。

```bash
mise install
bun install
uv sync

bun run pipeline    # 取得（CSV と PDF）→ dbt → 配布物 → 報告
bun run dev         # 報告を作り直してダッシュボードを上げる
```

**Python の版は 3.13 に固定してある。** dbt-duckdb 1.11.0 が classifiers で 3.14 を宣言していないため（`requires-python` は `>=3.10` なので入りはするが、テストされていない組み合わせになる）。

依存は exact ピン留めで、更新するときは cooldown を明示する。

```bash
uv add --exclude-newer $(date -v-7d +%Y-%m-%d) <package>
```

## 技術スタック

- **取得（ingestion）**: Python。原典を Parquet で `data/raw/` へ落とす。「無加工」は主張ではなく検査（復号の可逆性・原文の復元）
- **変換**: dbt（dbt-core + dbt-duckdb）。DuckDB は実行時に組む一時ファイルで、正は Parquet 側
- **配布パッケージの生成**: Python（`fdp/`）
- **報告の生成と画面**: Bun + TypeScript。報告の出力を `ReportData` 型に固定し、**生成側と画面側の食い違いをコンパイラに捕まえさせる**
- 配布: 原典・正本・判断をリポジトリに commit。①は Fiscal Data Package、②は OCDS、③は Popolo

**系統（lineage）は dbt の `manifest.json` から取る。** 手で書かない。
段とノードを手作りすると、パイプラインを変えても図が変わらない状態を作る（実際に作った）。

## Skills / 参照

構造・判断・手順の詳細は各文書へ逃がしてある。この文書には書かない。

- 設計方針・対象・パイプライン・パーサ原則 → `docs/design-principles.md`。①予算の実装と手順 → `docs/budget-pipeline.md`。決定の記録 → `docs/adr/`
- スクリプト一覧と観測の置き場 → `docs/scripts.md`
- 団体固有の実測・原典の癖 → `ingestion/budget/jurisdictions/<団体コード>.md`
- パイプライン（取得・PDF抽出・dbt）のハマりどころ → `.agents/skills/pipeline/`
- ③会議録の制約（著作権法40条1項）・manifest・driver → `ingestion/transcripts/README.md`
- 存在価値・先行事例・将来展望 → `docs/product-context.md`
- データ源の実測 → `docs/budget-availability.md` / `docs/kkj-api-notes.md` / `docs/fdp-spec-notes.md` / `docs/tokyo-survey.md`
- PRD → `docs/prd/<prd name>/`（`prd` skill の手順に従う）
