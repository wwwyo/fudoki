# 正本と派生

fudoki が配布するデータ。**リポジトリに置いてあるこれが正本**で、API やダッシュボードを作る場合もここから生成する派生物として扱う。

## 中身

```
132047/2024/
  datapackage.json      Fiscal Data Package 1.0.0 の descriptor
  expenditure.csv       歳出（正本）
  revenue.csv           歳入（正本）
  expenditure-cofog.csv 歳出 + COFOG（派生）
  checksums.json        再生成の一致判定に使うハッシュと、その判定規則
```

パスは `<全国地方公共団体コード>/<会計年度（西暦）>/`。

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

`data/reports/<団体コード>-<年度>.md` に、各段の入力・出力・差分・実例・検査結果がある。
検査が1つでも落ちると成果物は書き出されない。

## 再生成

```bash
bun run build:budget
```

一致の判定規則は `checksums.json` の `rule` にある（生成日時を除いたハッシュの一致）。

⚠️ **原典は保全していない。** 残しているのは URL・取得日時・SHA-256 だけ（`data/provenance/`）。
自治体が原典を差し替えた後は同じ入力から再生成できないので、その時点の正本をそのまま正として残す。

## ライセンスと帰属

原典は CC BY 4.0。各パッケージの `datapackage.json` の `licenses` と `attribution` を見ること。
