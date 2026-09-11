# AI が予算を集計して引けるようにする API

> ⚠️ **この文書は復元版であり、かつ main の取り込み前に書かれたものである。**
> 原本は `.agent/` が gitignore されていた時期に worktree の入れ替えで失われた。
> 内容は作成時の会話・PR #27 の本文・commit ログから起こしたもので、原本と字句までは一致しない。
>
> ⚠️ **本文の前提のうち2つは、main を取り込んだ時点で古い。**
> ①「収録は3団体」は5団体になった（`131016` / `132047` / `132071` / `132195` / `132241`）。
> ②「集計は build 時に前計算する（本書の中心の判断）」は、main が同じ集計を
> `report/budget/cofog.ts` に置いて画面と API の両方から読む構造を先に採っていたため、
> COFOG については main の構造へ寄せる（`decision.log` の 12 と 29 を参照）。

## Objectives

- **Goal**: 団体と年度を指定した予算を COFOG 別と科目階層別に集計でき、同一団体の年度を並べられ、名称で事業を引けるようにする。
- **Not goal**: MCP サーバ本体は設計しない。本書は API が何を返すかだけを決める。
- **Not goal**: 任意の軸を組み合わせた集計には応えない。allowlist に載せた組み合わせだけを引ける。
- **Not goal**: 事業階層（大事業、中事業、小事業）を v1 の集計の軸にしない。完全な構造は明細で、名称からの発見は検索で提供する。

## Background

前提となる PRD は [prd.md](./prd/mcp-server/prd.md) にある。

### 現状の API は集計する口を持たない（本書を書いた時点）

明細を返すだけなので、三鷹市の歳出を問えば 5,613 行が返る。
言語モデルはその量を読み込むところで止まり、集計に到達しない。

AGENTS.md は「集計は `report/budget/build.ts` の1箇所だけ」と定めており、同じ数字が2通りに計算されることを避けている。

### API には実行時のデータベースが無い

`apps/api/build.ts` が配布物からパーティション JSON を生成し、Workers は静的アセットとして読むだけである。
build は配布物との多重集合一致などを検査し、合わなければ止まる。

### 主な利用者は言語モデルである

人が手で叩くのではなく、MCP サーバの tool として言語モデルが呼ぶ。
このことが、条件を自由文字列に埋めない、制約を機械可読にする、といった判断の根拠になる。

### 対応する MCP の仕様版は SDK に縛られる

`@modelcontextprotocol/sdk` 1.30.0 が知っている版は 2025-11-25 までで、現行版（2026-07-28）は入っていない。
仕様の公開日が SDK の公開日の翌日なので、対応した SDK がまだ存在しない。

### 設計に効く実測（2026-08-30〜31、当時の3団体）

- **COFOG は group と class まで降りている行がある。** 歳出の割当済み行のうち group まで 42.2%（三鷹市）、44.2%（狛江市）、46.1%（多摩市）、class まで 4.2%、2.6%、2.7%
- **予算段階は direction で違う。** 狛江市の歳出は3段階、歳入は2段階
- **会計のコードは団体で揃わない。** 同じ「一般会計」が三鷹市では `01`、狛江市では `1`、多摩市では空文字
- **款のコードは会計の中でしか意味を持たない。** 三鷹市の `01` は一般会計で議会費、国民健康保険事業特別会計で総務費
- 連結状態は会計の中で混ざる。三鷹市の一般会計は `retained` 5,281 行、`eliminated` 28 行
- **事業名の資料は団体で違う。** `project_names.csv` があるのは狛江市だけで、三鷹市の事業名は原典の事項の名称にある
- 狛江市で事業名が付くのは、金額のある大事業の 57.1%（金額で 43.1%）

## System Overview

### リソースの形を name 中心に揃える

**BudgetLine の親は常に Budget である。**
明細識別子の先頭2セグメントが Budget の id と一致するので、親は前方のパースだけで決まる。

```
GET /budgets/{budget}/budgetLines
GET /budgets/-/budgetLines
GET /budgets/-/budgetLines:search
GET /budgets:aggregate?filter=...&groupBy=...
```

**集計は Budget コレクションのカスタムメソッドにする。**
Budget は既に root のコレクションなので、範囲はすべて `filter` で表せる。

⚠️ 当初は `{budget}` に `132195:-` のような部分ワイルドカードを置く案だった。
これは実在しない識別子を作る設計で、AIP-159 のワイルドカードでもない。

## Detailed Design

### 引ける集計の一覧

**契約と前計算を一対一にする。** 許した組み合わせに対応するアセットが必ず存在する。
**上限値ではなく allowlist を公開する**（`supportedGroupings`）。将来3軸を足すときは allowlist への追加だけで済む。

| `filter` が絞る範囲 | `groupBy` |
|---|---|
| 団体 + 年度 | `cofog.division` / `cofog.group` / `cofog.class` |
| 団体 + 年度 | `hierarchy`（`hierarchyParent` の直下1段） |
| 団体 + 年度 | `hierarchy,cofog.division` |
| 団体 | `fiscalYear` / `fiscalYear,cofog.division` |
| 年度 | `jurisdiction,cofog.division` / `.group` / `.class` |

**複数の団体にまたがるときは `jurisdiction` を軸に含めることを必須にする。**
これが「団体をまたいで足さない」を構造で守る仕組みである。

**階層の軸は `fund` を1つに絞る。** 款と項のコードは会計の中でしか意味を持たない。
`hierarchyParent` に指定できるのは根と款と項で、目を指定すると事業階層が返るので 400。

### 条件は typed field で受け、filter は範囲の絞り込みだけに使う

- `filter`（AIP-160 の部分集合）：`jurisdiction`、`fiscalYear`
- typed field：`direction`、`phase`、`fund`、`groupBy`、`hierarchyParent`、`view`

`phase` は行の絞り込みではなく、どの金額を測るかの選択である。
主な利用者が言語モデルなので、enum と必須性が OpenAPI に出て tool の schema に写る形が要る。

### 集計の応答

`cells`（軸ごとの値を `dimensions` の配列で持つ）、`residual`（`unclassifiable` / `outOfScope` / `notDescended`）、
`total`（範囲が1団体に閉じているときだけ）、`currency` / `amountUnit`、`query`（入力のエコー）、
`warnings` と `omitted`（enum のコード）、`supportedGroupings`、`judgment`、`provenance`、`revision`。

- `total` は範囲が1団体のときだけ返す。足せないものの合計を 0 であれ置かない
- 年度を軸にしたときはセルごとに `fundScope` を持たせる（会計の範囲が年度で変わる団体があるため）
- 帰属は `sources` に実体を1回だけ置き、`byBudget` が id で指す

### 明細の一覧

`view=BASIC`（既定）と `view=FULL`。`FULL` は実在する予算を親にしたときだけ許す。
判別可能な union をやめた理由は、これが別のリソースではなく**同じ BudgetLine のフィールドの充足度の違い**だから。

### 名称の検索

検索対象を2種類に分ける。片方だけでは「いじめで三鷹市と狛江市の該当が引ける」を満たせない。

- `accountLabel`：原典の階層の名称。`nameSource` は `canonical`
- `projectName`：`project_names.csv` による fudoki の対応づけ。`nameSource` は `judgment`

⚠️ 名称の有無は (団体, 年度, 階層) で判定する。団体単位で決め打ちすると、名称がある年度まで拒否する。

索引は**名称を単位**にする。明細を1行ずつ並べる形では索引が 82 MB になり、6件の該当を得るのに 60 回以上の呼び出しが必要だった。

### 検査

**build はセル単位で突き合わせる。** 合計だけの一致では、教育費の金額を福祉費のセルに入れる誤りが通る。
期待値は生成結果を再利用せず、CSV から別経路で作る。
`supportedGroupings` を母集団にして、宣言されたすべての組み合わせのアセットの存在を検査する。

**実行時は revision の混在を止める。** 読んだアセットの revision が meta と違えば数値を返さずに 500。

**ページトークンには問い合わせ全体の指紋を入れる。** filter だけでは別の問い合わせのトークンを流用できる。

## Alternatives Considered

| 観点 | build 時に前計算 | 実行時に集計 | SQL 相当の口 |
|---|---|---|---|
| 集計の置き場所 | 1箇所 | 2箇所 | 利用者側 |
| 配布物との検算 | build に書ける | 書けない | 不可 |
| 軸の自由度 | allowlist のみ | 任意 | 任意 |
| 誤りの現れ方 | build が止まる | 応答が静かに間違う | 利用者のクエリ誤り |

⚠️ この表は「API の中でどこに置くか」しか比べていない。
main は第4の選択肢（`report/` の共有関数に置き、画面と API の両方が読む）を先に採っており、そちらが正しい。

## Caveats

1. 引ける集計は allowlist で決まり、v1 では最大2軸である
2. 階層の集計は目までとする。理由は、目より下は名称の欠損が多く、言語モデルがどのセルを選べばよいか判断できないこと
3. 団体を絞らないと `fund` を指定できない（会計コードが団体で揃っていない）
4. `fiscalYear` と `jurisdiction` を同時に軸にする組み合わせは v1 の allowlist に入れない
5. 前計算の規模を全団体へ外挿していない
6. `cofogDepth` を出すと判断の粗さが見える（割当済みのうち group まで降りているのは4割強）
7. 狛江市の事業名のライセンスは照会中である
