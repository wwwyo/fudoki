# 風土記

日本の地方自治体の**支出を事業単位（目）まで**構造化し、外部データと join 可能な形で配布する。

名前は『風土記』から。713年の官命により、諸国へ地名の由来や産物を**同じ様式で報告させて集めた**地誌で、各自治体から同じ形式でデータを集めるという本 PJ の構造がそのまま重なる。

## Story

支出データで何かを判断する人が、自治体の支出を事業の単位で、他の街や他の年と同じ物差しで比べられる。

Core actions:
- ある団体・年度の支出を事業の単位で見る — 月次
- 団体をまたいで、または年をまたいで比べる — 月次
- 数字が怪しいと思ったときに、原典と合っているか・注意点が無いかを確かめる — 年数回

## Glossary

**風土記**:
このプロジェクトの名称。画面・説明文・ドキュメントでは「風土記」と表記する。
リポジトリ名・パッケージ名・URL・コード上の識別子の `fudoki` は変更しない。
_Avoid_: fudoki、fudoki（風土記）（利用者向けの表記として）

**原典（origin）**:
自治体が公開した予算・決算の資料そのもの（CSV または PDF）。
_Avoid_: ソース、元データ、生データ

**取り込み（ingestion / raw）**:
原典をそのまま表に読み込んだもの。値や単位は原典のまま。PDF の場合は組版からの抽出（抽出は復元検査が成り立たず、原典の内部で重複して印字された数字どうしの一致で確かめる）。
_Avoid_: パース、OCR（OCR は抽出の手段の1つ）

**原典別の整形（staging）**:
原典ごとに列名・型を整えたもの。風土記では原典の行と1対1の対応を保ち、金額の単位も原典のままにする。

**中間処理（intermediate）**:
利用者向けのデータを作るための準備。風土記では団体間の構造・金額単位の統一、共通科目への対応、COFOG 分類を行う。

**提供用データ（marts）**:
利用者が使う列・粒度を確定した最終データモデル。風土記では団体別の CSV として書き出し、原典由来の金額と分類などの判断は別リソースにする。

**正規化**:
列・型・単位・表記などを共通の形に揃える処理。特定の dbt 層の別名ではない。

**判断**:
原典にない対応・分類・推定を風土記が定めること。層名ではなく処理やデータの性質であり、dbt の標準用語ではない。

**配布物（package）**:
団体ごとに風土記が配る Fiscal Data Package。原典と Git の宣言・判断から生成し、版を固定して R2 から配る。
_Avoid_: 成果物、出力

**証跡（provenance）**:
原典をいつ・どこから・どの版の手順で取り込み、どう確かめたかの記録。
_Avoid_: ログ

**自治体データ版（jurisdiction version）**:
一団体の収録範囲・提供用データ・説明・配布参照を固定した内容の版。配布ファイルだけの版とは区別する。

**公開一覧（publication）**:
公開対象の団体と、それぞれの自治体データ版の組合せを固定した一覧。
_Avoid_: 全体のデータ版、構築版

## ディレクトリ構造

```
.
├── pipeline/         # ingestion/fiscal、dbt、fdp、publish、verify/report と verify/view
├── packages/         # fiscal の純粋な型・名称、data-contracts、jurisdictions
├── apps/             # 公開 web、D1 を読む api、R2 を配信する download、docs
├── slides/           # 発表資料
├── docs/             # 設計・調査文書
└── .agent/           # 個人メモ・試作（gitignore）
```

## セットアップ

ツールは mise で管理している。

```bash
mise install
bun install
uv sync

bun run pipeline:inputs  # sources.lock.json の固定入力を R2 から復元
bun run pipeline:build   # オフラインで dbt・FDP・manifest を生成
bun run dev              # ローカル専用の検証画面（5174）
```

**Python の版は 3.13 に固定してある。** dbt-duckdb 1.11.0 が classifiers で 3.14 を宣言していないため（`requires-python` は `>=3.10` なので入りはするが、テストされていない組み合わせになる）。

依存は exact ピン留めで、更新するときは cooldown を明示する。

```bash
uv add --exclude-newer $(date -v-7d +%Y-%m-%d) <package>
```

## 技術スタック

- **取得**: Python。原典 CSV/PDF のバイト列と取り込み Parquet を非公開 R2 に保存する。採用した入力の証跡は ingestion 配下の `provenance/`、入力一覧は `sources.lock.json` として Git 管理し、個別ハッシュを照合する。
- **変換・検査**: dbt-duckdb。marts が配布 CSV と D1 用の表を生成し、相互の行・金額・分類を検査する。
- **説明ファイル**: Python/TypeScript の `pipeline/fdp/`。FDP descriptor と収録範囲・出典・配布先をまとめた Git manifest を生成する。
- **検索・配布**: API は D1 の SQL を実行し、API は公開中の Git manifest URL を返し、download は R2 の団体別配布物を配信する。API に R2 やデータ ASSETS を bind しない。
- **検証**: Bun/TypeScript の `pipeline/verify/report/` とループバック専用の view。公開 web と UI は共有しない。
- **保存**: Git はコード・宣言・判断・入力一覧・採用した入力の証跡・最新 manifest、R2 は原典・取り込み・配布物、D1 は検索用の派生表。`.cache/` と `build/` は再生成可能なローカル作業領域。

**系統（lineage）は dbt の `manifest.json` から取る。** 手で書かない。
段とノードを手作りすると、パイプラインを変えても図が変わらない状態を作る（実際に作った）。

## Skills / 参照

構造・判断・手順の詳細は各文書へ逃がしてある。この文書には書かない。

- 設計方針・対象・パイプライン・パーサ原則 → `docs/design-principles.md`。①予算の実装と手順 → `docs/fiscal-pipeline.md`。決定の記録 → `docs/adr/`
- スクリプト一覧と観測の置き場 → `docs/scripts.md`
- 団体固有の実測・原典の癖 → `pipeline/ingestion/fiscal/jurisdictions/<団体コード>.md`
- パイプライン（取得・PDF抽出・dbt）のハマりどころ → `.agents/skills/pipeline/`
- ③会議録の制約（著作権法40条1項）・manifest・driver → `pipeline/ingestion/transcripts/README.md`
- 存在価値・先行事例・将来展望 → `docs/product-context.md`
- データ源の実測 → `docs/budget-availability.md` / `docs/kkj-api-notes.md` / `docs/fdp-spec-notes.md` / `docs/tokyo-survey.md`
- 設計の記録 → `docs/prd/<topic>/`（PRD）・`docs/design-doc-<topic>.md`（単体の設計書）・`docs/adr/`（決定）。判断の記録はコードと同じ寿命を持ち、git 管理する

全体設計 → `docs/design-doc-monorepo.md`。自治体別のデータ版・公開切替・保持条件の再設計 → `docs/design-doc-jurisdiction-versions.md`（実装未完了）。現行の実行手順 → `pipeline/README.md`。移行の検証記録と未完了項目 → `docs/monorepo-migration.md`。
