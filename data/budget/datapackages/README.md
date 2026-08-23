# 正本と派生

fudoki が配布するデータ。**リポジトリに置いてあるこれが正本**で、API やダッシュボードを作る場合もここから生成する派生物として扱う。

## 中身

```
132047/                   ← 正本。団体ごと・全年度
  datapackage.json        Fiscal Data Package 1.0.0 の descriptor
  expenditure.csv         歳出
  revenue.csv             歳入

derived/                  ← 派生。団体をまたいで1つ
  datapackage.json
  cofog.csv               識別子 + COFOG の判断
  cofog_rules.csv         判断の規則そのもの（35行）
```

**パスが言うのは正本か派生かだけ。** 中身が何かは `datapackage.json` の `title` と
`description` が言う。パスに中身（cofog）を書くと ②調達・③会議録の派生が増えたときに嘘になり、
カバレッジ（tokyo）を書くと対象を広げたときに地域で切ることになって横断できなくなる。
年度で切ってはいけないのと同じ理由である。

正本のパスは `<全国地方公共団体コード>/`。**年度でディレクトリを切らない** —
年度を分けると「年をまたぐ比較ができない」という PJ の出発点を成果物の形で再現してしまう。
年度は `fiscal_year` 列で区別する。

原典そのものは `data/raw/` に Parquet で置いてある（取得の単位ごとに partition）。
正本と join すれば、正規化の前の原文を突き合わせられる。

## 正本と派生を分けてある

- **正本**（`expenditure.csv` / `revenue.csv`）は原典を正規化しただけで、**fudoki の判断を含まない**。原典1行が1行に対応し、原文と突き合わせて検証できる
- **派生**（`expenditure-cofog.csv`）は正本へ COFOG を割り当てたもの。**ここからが fudoki の判断**

混ぜると、市が公表した事実と fudoki の判断を利用者が区別できなくなる。
FDP は全要素が任意なので、COFOG 列を持たない正本も適合した FDP になる。

## 金額

`value` は**円**。原典（三鷹市は千円単位）の値と単位は `source_amount` / `source_amount_unit` に残してある。
FDP には倍率を表す ColumnType が無く、千円のまま `value` に入れて `JPY` を付けると利用者が円と読むため。

## 行の識別子

`budget_line_id` は `<団体コード>:<年度>:<direction>:<予算段階>:<16桁>` の形。
末尾は階層のセル全文から導いた要約で、**出現順の連番ではない**。パーサを直しても同じ行を指し続ける。

⚠️ `hierarchy_path`（コードの連結）は可読性のための列であって識別子ではない。
三鷹市の歳出では細々節のコードが同じ節の下で再利用されるため（実測 710 箇所）、コードのパスは細々節まで一意にならない。

## 検証

`data/reports/<団体コード>.json` に、各段のノード・検査結果・COFOG の判断がある（画面は `bun run dev`）。
検査が1つでも落ちると `dbt build` が止まり、下流のモデルも配布物も作られない。

## 再生成

```bash
bun run pipeline
```

**原典は `data/raw/` に Parquet で保全してある。** 取得の単位（団体・年度・direction）ごとに partition してあり、
URL・取得日時・SHA-256 は原典の隣（`data/budget/raw/**/provenance.json`）にある。
自治体が原典を差し替えても、**手元の原典から成果物を再生成できる**。

出力は決定的にしてある（並びを固定し、`created` には実行時刻ではなく原典の取得時刻を入れる）。
中身が同じなら回しても差分が出ないので、git 履歴の差分は必ず実際の変化を意味する。

## ライセンスと帰属

各パッケージの `datapackage.json` の `licenses` / `sources` / `contributors` と、
出典表示の文言と改変の明示が入っている `description` を見ること。
⚠️ **正本のライセンスは原典のものを素通ししている**（fudoki が選んだものではない）。
詳しくは [data/LICENSE](../../LICENSE)。
