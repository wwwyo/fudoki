# 風土記（fudoki）

<img src="apps/web/public/hero.webp" alt="713年の官命により諸国から集められた、地名の由来や産物を記した巻物を役人が受け取る場面を描いた墨絵" width="100%">

**あなたの街の家計簿をオープンに。**

公開されているのに読めない。
自治体の予算は PDF か、自治体ごとに違う形の CSV で出ている。
だから「この市はこの事業にいくら使っているか」を機械で引けないし、市をまたぐ比較も年をまたぐ比較も事実上できない。

風土記は日本の地方自治体の**歳出の予算・決算額を事業単位まで**構造化し、AI ready なデータとして配布する。
デジタル庁のダッシュボードが目的別と性質別まで出している以上、欠けているのは**粒度**と**横断性**の2つだけで、そこだけを埋める。

## 現在の優先範囲

東京都の全区市町村（62団体）を最初の網羅範囲とし、収録できた団体から原典の取り込みと変換を進める。まず **ingestion → staging → intermediate → marts** を完成させる。

原典の値・単位・階層を保ち、団体間で列・金額単位・分類を揃え、提供用データの金額・粒度・出典を検査する。配布・検索の保存先や公開方式は、パイプライン完成後に検討する。

取得元の宣言は [`sources.toml`](pipeline/ingestion/fiscal/sources.toml)、入力一覧は `pipeline/ingestion/fiscal/sources.lock.json`（正規 lock の採用は未完了）、団体別の実測は [`jurisdictions/`](pipeline/ingestion/fiscal/jurisdictions/) にある。証跡は独立ファイルにせず、出典・意味は入力一覧と原典宣言が持つ。原典と取り込み済み Parquet の保管用 R2 は、固定入力の復元に使う。

## 開発

前提: [mise](https://mise.jdx.dev/) と、全量入力を復元する場合は非公開 R2 の読取権限。

```bash
mise install
bun install --frozen-lockfile
uv sync --frozen

bun run pipeline:inputs       # Git の入力一覧から R2 の固定入力を復元・照合
bun run pipeline:build        # 現行 build を実行（dbt に加え後段処理も含む）
bun run dev                   # 報告を生成し、ローカル検証画面を 127.0.0.1:5174 で起動
```

`pipeline:build` は dbt の変換・検査と marts の CSV 生成までを実行する。結果は `pipeline/.build/builds/b-<内部構築ID>/` に入り、同じ構築 ID の再実行では CSV のハッシュを照合する。公開 web・API・MCP・docs は一時的に HTTP 500 を返す。

固定入力の復元・検証画面・現在の実装上の制約は [pipeline/README.md](pipeline/README.md) を参照。

## 用語

原典は自治体が公開した CSV・PDF そのもの、取り込みは原典の値と単位を保った表である。dbt の staging で列名・型を整え、intermediate で共通単位・科目・分類を揃え、marts で提供する列と粒度を確定する。詳細は [用語](AGENTS.md#glossary) と [設計](docs/prd/monorepo/design-doc.md) を参照。

COFOG は歳出明細と同じ CSV に含め、原典由来の金額と分類などの判断を列の説明で区別する。名称の対応は `account_names.csv`・`project_names.csv` で配る。判断の根拠は Git にある規則表に残す。DuckDB は、その入力と宣言から生成する実行用の表である。

歳出の款・項・目は目的・科目の階層で、款が最も粗い。節は目の内訳を経済的な性質で分ける法定区分である。
「事業単位まで」というのは目とその下の事業階層に届くという意味で、既存のダッシュボードは款と項で止まっている。
事業階層の名前は団体ごとに違う（三鷹市は「事項」、狛江市は「大事業・中事業・小事業」）。
**COFOG への対応は風土記の判断**であり、原典の階層経路を保った歳出明細に分類列として加える。

科目の名称が原典に無い団体（狛江市）は、市が公開している決算書 PDF の見出しから名称を解決している。これも判断なので、出所は規則の根拠に書いてある。

**COFOG**（Classification of the Functions of Government）は政府支出の機能別分類で、教育や保健といった10のディビジョンに分ける国際標準である。
自治体をまたぐ比較にも将来の国際比較にも同じ写像が効くので、粒度と対にして作っている。

## 将来展望

予算・決算と調達を、それぞれ既存の標準に載せて繋ぐ。

| レイヤ | 標準 | 状態 |
|---|---|---|
| ① 何にいくら（予算） | [Fiscal Data Package](https://fiscal.datapackage.org/) | ingestion〜marts を優先して整備中 |
| ② いつ何が公告されたか（調達） | [OCDS](https://standard.open-contracting.org/) | 未着手 |

- コードは MIT。データは原典のライセンスに従う（下記）
- MCP サーバとしても配布し、AI エージェントが直接読める形にする

## もっと読む

- [AGENTS.md](AGENTS.md): 設計方針、実測にもとづく判断、パーサ設計の原則
- [pipeline/README.md](pipeline/README.md): 固定入力からの構築と検査
- [apps/web/README.md](apps/web/README.md): ダッシュボードの構成
- [pipeline/dbt/models/](pipeline/dbt/models/): staging（原典別の整形）→ intermediate（統合・分類）→ marts（提供用データ）。配布処理は `pipeline/fdp/` に分け、原典の保存と判断の整合性はテストで縛っている
- [pipeline/ingestion/fiscal/sources.toml](pipeline/ingestion/fiscal/sources.toml): 取得元の定義。団体を足すときはここから

名前は『風土記』から。
713年の官命により、諸国へ地名の由来や産物を**同じ様式で報告させて集めた**地誌で、各自治体から同じ形式でデータを集めるという本 PJ の構造がそのまま重なる。

## License

**1つのライセンスでは表せない**ので、層ごとに分けてある。

| 層 | 誰のものか | ライセンス |
|---|---|---|
| コード（`pipeline/` `packages/` `apps/`） | fudoki | [MIT](LICENSE) |
| 風土記の判断（COFOG 分類列・科目や事業名の対応） | 風土記 | descriptor の列・リソースごとの宣言（現在は CC BY 4.0） |
| 原典・取り込み表・配布明細の原典由来の列 | **各自治体** | 各原典の利用条件 |

⚠️ **原典のライセンスは fudoki が選んだものではない。**
著作権を持たないものにライセンスは与えられないので、正本の表示は原典に付いてくる条件を
そのまま素通ししている。fudoki は原典を改変しているので、その旨も表示している（CC BY 4.0 §3(a)(1)(B)）。

方針は [ライセンスの層別宣言](docs/adr/0006-license-per-layer.md)、正確な表示は各 `datapackage.json`（`licenses` / `sources` / `contributors` / `description`）。
