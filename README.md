# 風土記（fudoki）

<img src="apps/web/public/hero.webp" alt="713年の官命により諸国から集められた、地名の由来や産物を記した巻物を役人が受け取る場面を描いた墨絵" width="100%">

**あなたの街の家計簿をオープンに。**

公開されているのに読めない。
自治体の予算は PDF か、自治体ごとに違う形の CSV で出ている。
だから「この市はこの事業にいくら使っているか」を機械で引けないし、市をまたぐ比較も年をまたぐ比較も事実上できない。

fudoki は日本の地方自治体の**支出を事業単位まで**構造化し、標準形式で配布する。
デジタル庁のダッシュボードが目的別と性質別まで出している以上、欠けているのは**粒度**と**横断性**の2つだけで、そこだけを埋める。

## 配布しているもの

東京都の全区市町村（62団体）を最初の網羅範囲とし、**収録できた団体から順に** [Fiscal Data Package](https://fiscal.datapackage.org/) 1.0.0 として配布している。

| 内容 | 保存先・入口 |
|---|---|
| 原典の CSV・PDF、取り込み済み Parquet | 非公開 R2。採用する個別ハッシュとキーは `pipeline/ingestion/fiscal/sources.lock.json` |
| 採用した入力の証跡 | Git 管理する `pipeline/ingestion/fiscal/provenance/`。lock が相対パス・ハッシュ・サイズを固定 |
| 団体別の CSV・Fiscal Data Package | release ごとの R2。現行は download Worker、[直接配信への変更](docs/adr/0011-public-r2-distribution.md)は未反映 |
| 検索・集計用の表、公開メタデータ | D1。公開 API と MCP が同じ問い合わせを使う |
| 系統・検査結果・原典との行対応 | ローカル専用 `pipeline/verify/view/` |

取得元の宣言は [`sources.toml`](pipeline/ingestion/fiscal/sources.toml)、団体別の実測は [`jurisdictions/`](pipeline/ingestion/fiscal/jurisdictions/) にある。公開 API の `listFiscalDatasets` が収録した文書・年度・原典版・金額段階を返し、`listFiles` が版を固定した配布 URL を返す。

**移行中**: 新構造のローカル build と検証を実装している。R2 の有効化・全量転送と候補環境での確認が完了するまで、既存の `data/` は保管する。新しい download/API の公開済み状態をこの文書から推定しない。進捗と採用条件は [移行記録](docs/monorepo-migration.md) に記載する。

## 開発

前提: [mise](https://mise.jdx.dev/) と、全量入力を復元する場合は非公開 R2 の読取権限。

```bash
mise install
bun install --frozen-lockfile
uv sync --frozen

bun run pipeline:inputs       # Git の入力一覧から R2 の固定入力を復元・照合
bun run pipeline:build        # ネットワークを使わず dbt・FDP・manifest を生成
bun run dev                   # 報告を生成し、ローカル検証画面を 127.0.0.1:5174 で起動
```

`pipeline:build` の結果は `pipeline/build/releases/<release_id>/` に入り、公開中のデータは変わらない。`pipeline:publish publish --release-id <release_id>` が完成済みの候補を転送・照合し、D1 の公開参照を切り替える。publish は build を再実行しない。API や web の deploy はコードだけを扱う。

```bash
bun run dev:api               # 公開 API のローカル Worker
bun run dev:download          # 配布 Worker。公開 manifest があるファイルだけを配信
bun run dev:web               # 公開 UI、5173。検証画面とは別のアプリ
bun run test
bun run typecheck:all
```

全量入力へアクセスできない環境では、Git にある架空団体の fixture で保存形式・問い合わせ・公開切り替えを検査する。fixture の成功は自治体データの全量 build 成功を意味しない。セットアップ・取得・移行・保持・バックアップの手順は [pipeline/README.md](pipeline/README.md) にある。

## 用語

原典は自治体が公開した CSV・PDF そのもの、取り込みは原典の値と単位を保った表である。dbt の staging で列名・型を整え、intermediate で共通単位・科目・分類を揃え、marts で提供する列と粒度を確定する。詳細は [用語](AGENTS.md#glossary) と [設計](docs/design-doc-monorepo.md) を参照。

原典由来の金額と、風土記が定めた COFOG・名称などの判断は、同じパッケージの別リソースとして配る。判断の根拠は Git にある規則表に残す。DuckDB と D1 は、その入力と宣言から生成する実行用の表である。

予算の科目は **款 > 項 > 目 > 節** の階層で、款が最も粗い（地方自治法にもとづく区分）。
「事業単位まで」というのは目とその下の事業階層に届くという意味で、既存のダッシュボードは款と項で止まっている。
事業階層の名前は団体ごとに違う（三鷹市は「事項」、狛江市は「大事業・中事業・小事業」）。
**揃えることは fudoki の判断**なので、正本は団体ごとの形のままにしてあり、揃えた側（COFOG）を別リソースに置いている。

科目の名称が原典に無い団体（狛江市）は、市が公開している決算書 PDF の見出しから名称を解決している。これも判断なので、出所は規則の根拠に書いてある。

**COFOG**（Classification of the Functions of Government）は政府支出の機能別分類で、教育や保健といった10のディビジョンに分ける国際標準である。
自治体をまたぐ比較にも将来の国際比較にも同じ写像が効くので、粒度と対にして作っている。

## 将来展望

3つのレイヤを、それぞれ既存の標準に載せて繋ぐ。

| レイヤ | 標準 | 状態 |
|---|---|---|
| ① 何にいくら（予算） | [Fiscal Data Package](https://fiscal.datapackage.org/) | 収録できた団体から配布中 |
| ② いつ何が公告されたか（調達） | [OCDS](https://standard.open-contracting.org/) | 未着手 |
| ③ どう決まったか（会議録） | [Popolo](https://www.popoloproject.com/) | 権利判定のみ（再配布可の団体は0） |

- 配布データは原典の利用条件に従って download Worker から公開
- コードは MIT。データは原典のライセンスに従う（下記）
- MCP サーバとしても配布し、AI エージェントが直接読める形にする

## もっと読む

- [AGENTS.md](./AGENTS.md): 設計方針、実測にもとづく判断、パーサ設計の原則
- [pipeline/README.md](pipeline/README.md): 配布物の読み方
- [apps/web/README.md](./apps/web/README.md): ダッシュボードの構成
- [pipeline/dbt/models/](pipeline/dbt/models/): staging（原典別の整形）→ intermediate（統合・分類）→ marts（提供用データ）。配布処理は `pipeline/fdp/` に分け、原典の保存と判断の整合性はテストで縛っている
- [pipeline/ingestion/fiscal/sources.toml](./pipeline/ingestion/fiscal/sources.toml): 取得元の定義。団体を足すときはここから

名前は『風土記』から。
713年の官命により、諸国へ地名の由来や産物を**同じ様式で報告させて集めた**地誌で、各自治体から同じ形式でデータを集めるという本 PJ の構造がそのまま重なる。

## License

**1つのライセンスでは表せない**ので、層ごとに分けてある。

| 層 | 誰のものか | ライセンス |
|---|---|---|
| コード（`pipeline/` `packages/` `apps/`） | fudoki | [MIT](./LICENSE) |
| fudoki の判断（`datapackages/<団体コード>/cofog*.csv` `project_names.csv`） | fudoki | CC BY 4.0 |
| 原典と正本（非公開 R2 の取り込み `datapackages/<団体コード>/expenditure.csv` `revenue.csv`） | **各自治体** | 各原典の利用条件 |

⚠️ **原典のライセンスは fudoki が選んだものではない。**
著作権を持たないものにライセンスは与えられないので、正本の表示は原典に付いてくる条件を
そのまま素通ししている。fudoki は原典を改変しているので、その旨も表示している（CC BY 4.0 §3(a)(1)(B)）。

詳細は [データの利用条件](docs/data-license.md)、正確な表示は各 `datapackage.json`（`licenses` / `sources` / `contributors` / `description`）。
