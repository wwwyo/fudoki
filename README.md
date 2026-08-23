# fudoki（風土記）

**公開されているのに読めない、を読める形にする。**

自治体の予算は全部公開されている。
ただし PDF か、自治体ごとに違う形の CSV である。
だから「この市はこの事業にいくら使っているか」を機械で引けないし、市をまたぐ比較も年をまたぐ比較も事実上できない。

fudoki は日本の地方自治体の**支出を事業単位まで**構造化し、標準形式で配布する。
デジタル庁のダッシュボードが目的別と性質別まで出している以上、欠けているのは**粒度**と**横断性**の2つだけで、そこだけを埋める。

## いま手に入るもの

東京都三鷹市の令和6年度当初予算（歳出 5,613行、歳入 821行）を [Fiscal Data Package](https://fiscal.datapackage.org/) 1.0.0 として配布している。

- 原典: [`data/budget/raw/`](./data/budget/raw/)（Parquet。取得の単位ごとに partition）
- 正本: [`data/budget/datapackages/132047/`](./data/budget/datapackages/132047/)（判断を含まない）
- 派生: [`data/budget/datapackages/derived/`](./data/budget/datapackages/derived/)（COFOG の割当と、その規則35行）
- 取得の証跡: 原典の隣の `provenance.json`（URL・status・SHA-256・取得時刻）
- パイプライン報告: `bun run dev` で生成してダッシュボードで見る

たとえば「いじめ問題対策協議会関係費」は 311,000円で、教育費 > 教育総務費 > 教育指導費 の下にある。
これを機械で引けるようにするのが目的である。

## 5分で動かす

前提: [mise](https://mise.jdx.dev/)

```bash
mise install
bun install

bun run pipeline       # 取得 → dbt → 配布物 → 報告（検査が落ちたら下流を作らない）
bun run dev            # ダッシュボードを開く（http://localhost:5173）
```

`pipeline` はネットワークを叩くので CI では回さない。原典が既にあれば取得は skip する。
生成済みの成果物はリポジトリに commit してあるので、動かさずに中身だけ見ることもできる。

## 用語

このプロジェクトはデータを3段階に分ける。
**段の切れ目は「fudoki の判断が入るかどうか」で引いている。**

| 日本語 | コード上の識別子 | 意味 |
|---|---|---|
| **原典** | `source` | 自治体が公開したファイルそのまま。`data/budget/raw/` に Parquet で置く |
| **正本** | `canonical` | 原典を取り込んで検証しただけのもの。**fudoki の判断を含まない**ので、原文と突き合わせて検証できる |
| **派生** | `derived` | 正本に COFOG を割り当てたもの。**ここから fudoki の判断が入る** |

正本と派生を混ぜると、市が公表した事実と fudoki の判断を利用者が区別できなくなる。
だから別のファイルとして配る。

予算の科目は **款 > 項 > 目 > 節** の階層で、款が最も粗い（地方自治法にもとづく区分）。
「事業単位まで」というのは目とその下の事業階層に届くという意味で、既存のダッシュボードは款と項で止まっている。

**COFOG**（Classification of the Functions of Government）は政府支出の機能別分類で、教育や保健といった10のディビジョンに分ける国際標準である。
自治体をまたぐ比較にも将来の国際比較にも同じ写像が効くので、粒度と対にして作っている。

## 将来展望

3つのレイヤを、それぞれ既存の標準に載せて繋ぐ。

| レイヤ | 標準 | 状態 |
|---|---|---|
| ① 何にいくら（予算） | [Fiscal Data Package](https://fiscal.datapackage.org/) | 1団体目を配布済み |
| ② いつ何が公告されたか（調達） | [OCDS](https://standard.open-contracting.org/) | 未着手 |
| ③ どう決まったか（会議録） | [Popolo](https://www.popoloproject.com/) | 権利判定のみ（再配布可の団体は0） |

- 生成データはオープンデータとして本リポジトリで公開
- コードは MIT。データは原典のライセンスに従う（下記）
- MCP サーバとしても配布し、AI エージェントが直接読める形にする

## もっと読む

- [AGENTS.md](./AGENTS.md): 設計方針、実測にもとづく判断、パーサ設計の原則
- [data/budget/datapackages/README.md](./data/budget/datapackages/README.md): 正本と派生の読み方
- [web/README.md](./web/README.md): ダッシュボードの構成
- [dbt/models/](./dbt/models/): staging（判断なし）と core（判断あり）。層の境界はテストで縛っている
- [ingestion/budget/sources.toml](./ingestion/budget/sources.toml): 取得元の定義。2団体目はここに足す

名前は『風土記』から。
713年の官命により、諸国へ地名の由来や産物を**同じ様式で報告させて集めた**地誌で、各自治体から同じ形式でデータを集めるという本 PJ の構造がそのまま重なる。

## License

**1つのライセンスでは表せない**ので、層ごとに分けてある。

| 層 | 誰のものか | ライセンス |
|---|---|---|
| コード（`ingestion/` `dbt/` `fdp/` `report/` `web/`） | fudoki | [MIT](./LICENSE) |
| fudoki の判断（`data/budget/datapackages/derived/`） | fudoki | CC BY 4.0 |
| 原典と正本（`data/budget/raw/` `datapackages/<団体コード>/`） | **各自治体** | 原典のライセンス（現在はすべて CC BY 4.0） |

⚠️ **原典のライセンスは fudoki が選んだものではない。**
著作権を持たないものにライセンスは与えられないので、正本の表示は原典に付いてくる条件を
そのまま素通ししている。fudoki は原典を改変しているので、その旨も表示している（CC BY 4.0 §3(a)(1)(B)）。

詳細は [data/LICENSE](./data/LICENSE)、正確な表示は各 `datapackage.json` の `licenses` と `attribution`。
