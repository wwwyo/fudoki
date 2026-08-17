# src/budget — ① 予算のパイプライン

エントリポイントは [`scripts/build-budget.ts`](../../scripts/build-budget.ts)（`bun run build:budget`）。
このディレクトリは10ファイルあるが、**読む順序は依存の順序**で決まる。

## 読む順序

```
source.ts     取得元の定義。どの団体のどの年度をどこから取るか
  ↓
columns.ts    原典の階層と FDP の ColumnType の対応。団体ごとの宣言はここ
  ↓
extract.ts    CKAN からリソースを解決して無加工で取得。証跡を残す
  ↓
load.ts       原典1行を正本1行へ。ここまで判断は入らない
  ↓
cofog.ts      COFOG の割り当て規則。ここから判断が入る
transform.ts  規則を適用して派生を作る
  ↓
fdp.ts        datapackage.json と CSV を書く
verify.ts     検査30件
topology.ts   段・ノード・辺を実行結果から導く（画面が描く形）
report.ts     報告データを組み立てる。集計はここ1箇所だけ
```

段の切れ目は **「fudoki の判断が入るかどうか」** で引いている。
ELT という語の一般的な意味とはずれる（詳細は [AGENTS.md のパイプライン節](../../AGENTS.md)）。

## 2団体目を足す手順

団体ごとに宣言が要る箇所は、すべて**未宣言なら例外で止まる**か、**型で必須**にしてある。
推測で埋める箇所は残していない。

### 1. `source.ts` に `BudgetSource` を足し、`SOURCES` に登録する

```ts
export const KOMAE_FY2024: BudgetSource = { jurisdictionCode: '132195', ... }

export const SOURCES = {
  '132047:2024': MITAKA_FY2024,
  '132195:2024': KOMAE_FY2024,   // ← 足す
}
```

`bun run build:budget --source=132195:2024` で選ぶ。
スクリプト本体は編集しない。

⚠️ **`CKAN_ENDPOINT` は東京都カタログ専用。**
団体の解決に `organization.name === 't' + 団体コード` というこのカタログの命名規則を使う（`extract.ts`）。
都外の団体を足すときは、エンドポイントと解決方式の両方を取得元ごとの設定へ出す必要がある。

### 2. `columns.ts` に階層を宣言する

`LEVELS_BY_JURISDICTION` へ歳出と歳入の `LevelSpec[]` を足す。
未宣言の団体コードは `levelsFor` が例外で止める。

**実測で埋める項目が2つある。推測しない。**

- `codeUniqueAmongSiblings`: 同じ親の下でコードが一意か。
  検査が宣言と実測を**両方向で**突き合わせるので、間違えると止まる
- `codeDigits`: セル先頭のコードの桁数。三鷹市は2。
  間違えるとコードと名称の分離が黙って失敗し、`irregularCells` に積まれるだけで止まらない

`ABSENT_LEVEL_MARKERS` に「その階層が無い」を表すセルを宣言する（三鷹市は `'0'`）。

### 3. `published/` に公表値を置く

`published/<団体>-<年度>.ts` を作り、`PublishedReference` 型で公表資料の款別の値を書き写す。
`BudgetSource.publishedReference` から参照させる。

外部資料で裏づけない場合は `null` にできるが、**そのときは `notYetReconciled` に何が裏づけられていないかを書く**。
型で必須にしてあるので、黙って検査を1本減らすことはできない。

### 4. `cofog.ts` の規則を見直す

規則には `appliesTo`（団体コード）がある。
**省略できるのは法定語彙にだけ当たる規則に限る。**

三鷹市の実測では 35本中、共通で使えるのは 11本（款と節にマッチするもの）で、**24本が三鷹市固有**（項・目・会計名にマッチするもの）だった。
2団体目でも項以下は書き直しになると見込んでおく。

その団体に効く規則の内訳は報告の `transform.ruleScope` に出る。

### 5. 回す

```bash
bun run build:budget --source=<key> --check   # 書き出さず検査だけ
bun run build:budget --source=<key>
```

**検査が1つでも落ちたら成果物を書かずに落ちる。**
欠落したまま合計が下がった正本を配らないため。

## 読み間違えると壊すもの

- **識別子はコードのパスでは作れない。** 三鷹市の細々節は同じ節の下でコードを再利用する（実測 710 箇所・1,615 行）。
  パスの構成要素は**セル全文**（コード + 名称）に取ってある（`load.ts` の `budgetLineId`）
- **集計は `report.ts` の `buildReportData` 1箇所だけ。**
  画面側でも集計すると、同じ数字が2通りに計算されて、いずれ食い違ったまま気づかなくなる
- **段の名前と並びは `topology.ts` が出す。**
  画面に直書きすると、パイプラインを変えても図が変わらない状態になる
- **`verify.ts` の検査は落ちたら止まる。** 新しい団体で落ちたときは、原因が「原典側の想定違い」か「宣言の不足」かを切り分ける。
  検査を消して通すのは最後の手段で、消すなら何が保証されなくなるかを `notYetReconciled` に書く

## コメントの言語について

コメントは日本語、識別子は英語。
型と関数のシグネチャからロジックの形は日本語を読まなくても追えるが、
**「なぜその設計にしたか」の根拠（実測値を含む）はコメントにしかない**。
規則を1本足すときは、`cofog.ts` の `basis` フィールドに理由を書く（これは配布物にも出る）。
