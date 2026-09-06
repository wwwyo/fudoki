---
version: "alpha"
name: 風土記（fudoki）
description: 自治体の予算を事業単位まで構造化して配布する風土記の画面。彩度ゼロを既定とし、色が付くものには必ず意味を持たせる。
colors:
  # 基調。無彩色（彩度ゼロ）で通す。色は意味を持つところにだけ置く
  background: "oklch(1 0 0)"
  foreground: "oklch(0.145 0 0)"
  card: "oklch(1 0 0)"
  card-foreground: "oklch(0.145 0 0)"
  # ブランド。青丹（あをに）。shadcn の primary は仕様上 "brand surfaces" の置き場
  primary: "#2f5d43"
  primary-foreground: "#f4f1e6"
  secondary: "oklch(0.97 0 0)"
  secondary-foreground: "oklch(0.205 0 0)"
  muted: "oklch(0.97 0 0)"
  muted-foreground: "oklch(0.556 0 0)"
  accent: "oklch(96.5% 0.012 157)"
  accent-foreground: "oklch(32% 0.04 157)"
  border: "oklch(0.922 0 0)"
  ring: "oklch(58% 0.075 157)"
  destructive: "oklch(0.577 0.245 27.325)"
  # ロゴが持つ塗り。UI トークンではない
  mark-rule: "#c1553a"
  og-paper: "#f4f1e6"
typography:
  heading:
    fontFamily: "\"Geist Variable\", \"Noto Sans JP Variable\", \"Hiragino Sans\", sans-serif"
    fontSize: 20px
    fontWeight: 600
    lineHeight: "28px"
  stat:
    fontFamily: "\"Geist Variable\", \"Noto Sans JP Variable\", \"Hiragino Sans\", sans-serif"
    fontSize: 20px
    fontWeight: 500
    lineHeight: "28px"
  body:
    fontFamily: "\"Geist Variable\", \"Noto Sans JP Variable\", \"Hiragino Sans\", sans-serif"
    fontSize: 14px
    fontWeight: 400
    lineHeight: "20px"
  label:
    fontFamily: "\"Geist Variable\", \"Noto Sans JP Variable\", \"Hiragino Sans\", sans-serif"
    fontSize: 12px
    fontWeight: 500
    lineHeight: "16px"
  caption:
    fontFamily: "\"Geist Variable\", \"Noto Sans JP Variable\", \"Hiragino Sans\", sans-serif"
    fontSize: 12px
    fontWeight: 400
    lineHeight: "19.5px"
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"
    fontSize: 12px
    fontWeight: 400
    lineHeight: "19.5px"
rounded:
  sm: 6px
  md: 8px
  lg: 10px
  xl: 14px
  pill: 26px
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  section: 32px
components:
  card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.card-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.xl}"
    padding: "{spacing.lg}"
  card-label:
    textColor: "{colors.muted-foreground}"
    typography: "{typography.label}"
  card-value:
    textColor: "{colors.foreground}"
    typography: "{typography.stat}"
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.primary-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    height: 32px
    padding: "10px"
  button-outline:
    backgroundColor: "{colors.background}"
    textColor: "{colors.foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    height: 32px
    padding: "10px"
  badge:
    backgroundColor: "{colors.secondary}"
    textColor: "{colors.secondary-foreground}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    height: 20px
    padding: "2px 8px"
  input:
    backgroundColor: "{colors.background}"
    textColor: "{colors.foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    height: 32px
    padding: "{spacing.md}"
  tab-trigger:
    textColor: "{colors.muted-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "2px 6px"
  tab-trigger-active:
    backgroundColor: "{colors.background}"
    textColor: "{colors.foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "2px 6px"
  table-header-cell:
    textColor: "{colors.foreground}"
    typography: "{typography.label}"
    height: 32px
  table-cell:
    textColor: "{colors.foreground}"
    typography: "{typography.body}"
    height: 32px
  flow-node:
    backgroundColor: "{colors.card}"
    textColor: "{colors.card-foreground}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    height: 46px
    width: 210px
  path-code:
    textColor: "{colors.muted-foreground}"
    typography: "{typography.mono}"
  focus-ring:
    backgroundColor: "{colors.ring}"
    rounded: "{rounded.md}"
    size: 3px
  button-hover-surface:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    height: 32px
  button-outline-hover:
    backgroundColor: "{colors.muted}"
    textColor: "{colors.foreground}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    height: 32px
  rule:
    backgroundColor: "{colors.border}"
    height: 1px
  card-value-failed:
    textColor: "{colors.destructive}"
    typography: "{typography.stat}"
  # 流れ図のノードに付く検査の印。落ちているときだけ色が付く
  check-marker-failed:
    backgroundColor: "{colors.destructive}"
    size: 16px
  check-marker:
    backgroundColor: "{colors.muted-foreground}"
    size: 16px
  # ロゴ。短冊（青）が基準線（丹）の上に並ぶ
  logo-bar:
    backgroundColor: "{colors.primary}"
    width: 4px
    height: 26px
    rounded: "{rounded.sm}"
  logo-rule:
    backgroundColor: "{colors.mark-rule}"
    height: 2px
  og-canvas:
    backgroundColor: "{colors.og-paper}"
    textColor: "{colors.foreground}"
    width: 1200px
    height: 630px
---

## Overview

⚠️ **画面は3種類あり、答える問いが違う。** 当初この文書は検査の画面だけを記述していたので、
どの話をしているかを先に分ける。

- **報告** — パイプラインの検査結果。**検査成績書**として組む
- **分析** — 団体の支出を COFOG で見る。**金額を読ませる画面**
- **読み物** — ホームと利用条件。説明が主体で、絵と見出しがその役を担う

### 報告の性格

**検査成績書であって、可視化ではない。** この画面が答える問いは「この配布データは信用できるか」の1つで、
「三鷹市はいくら使ったか」ではない。だから装飾も、印象を作るための色も、演出のための動きも持たない。
紙の検査成績書がそうであるように、余白と罫線と数字だけで構成し、
読み手が値を1つずつ確かめられることを最優先にする。

その結果、全体の質感は **Dense（密）で Utilitarian（実用一辺倒）** になる。
画面は白地（`{colors.background}`）に無彩色の細線で区切られ、影はほぼ無い。
情報の階層は色や影ではなく、**文字サイズと余白**が作る。

**彩度はゼロが既定で、色が付いているものには必ず意味がある。**
このルールを守るために shadcn の `chart-1..5` は使っていない（base-nova のそれはゼロ彩度のグレーで、
判断の有無も分類の状態も区別できないため）。

### 分析の性格

**報告が答えない問いに答える。** 報告は「この配布データは信用できるか」に答えるが、
分析は「**この団体は何にいくら使っているか**」に答える。可視化そのものなので、
報告の「装飾も色も持たない」はここには効かない。

⚠️ **色を持てるのは COFOG の10色だけ。** これは既に
「識別の補助であって情報の担い手ではない」と決めてあり（後述）、明度と彩度を
狭い帯に抑えてある。**ここに新しい色を足さない** — 足した瞬間に
「色が付いていたら意味がある」という既定が崩れる。

⚠️ **割合の分母は合計にする。割り当てられなかった分を落とさない。**
割当済みだけを分母にすると 100% になり、**使途が見えていない分まで
「見えている」ことになる**。未分類は分母に含めたうえで、帯にも一区画として出す。

⚠️ **画面で集計しない。** 数字は API が返したものをそのまま出す。
集計の実装は `report/budget/cofog.ts` の1つだけで、報告も API も同じ関数を通る。
2箇所で計算すると、同じ数字が2通りに出ていずれ食い違う。

### 読み物の性格

**読み手はまだ何も知らない。** 報告に来る人は配布データが正しいかを確かめに来るが、
ホームに来る人は fudoki が何なのかを知らない。だから読み物は説明が主体で、
絵と見出しがその役を担う。

⚠️ **上の彩度の既定・意味色・ブランド色の線引き・Flat・`tabular-nums` は読み物にも効く。**
報告と違うのは、装飾を持たないことと文字サイズが4段しかないことで、
どちらも**検査成績書の密度のための決めごと**である。

## Colors

**この画面が色で言うことは1つだけ — 検査が落ちているか。**

`{colors.destructive}` だけが意味を持つ色で、下流の成果物を書き出さない状態を指す。
それ以外はすべて無彩色に落ちる。

⚠️ **警告に色を与えない。** 一時は失敗（赤）と警告（黄）の対で持っていたが、
**警告は数と一覧が言う** — ノードに付く印は件数を数字で持ち、検査タブに一行ずつ出る。
色を足しても情報は増えず、「色が付いていたら意味がある」の意味が1段薄まるだけだった。

⚠️ **判断の有無（原典・正本 ⇄ 派生）も色で言わない。**
以前は寒色／暖色の対で示していたが、**段の並びと辺の向きが既にそれを言っている** — 流れ図は
左から右へ ingestion → staging → core → package と並び、fudoki の判断が入るのは core からである。
位置で分かることを色でも言うと、色の語彙が2つの意味を持つ。

**この2つを削ったので、意味色は destructive の 1 つだけになった。**
増やすときは、それが何を言うか・位置や数字では言えないのかを先に確かめる。

COFOG の大分類（01〜10）にも 10 色を割り当てているが、
これは**識別の補助であって情報の担い手ではない**。明度を 58〜69% の狭い帯に、彩度を 0.05〜0.10 に
抑えてあり、どれかが目立つことがないようにしている。色はコードの文字と必ず併記する。
⚠️ この 10 色は CSS トークンではなく `apps/web/src/lib/pipeline.ts` の `DIVISION_COLOR` が持つ。
**分類体系に対応する色はデータの一部**で、テーマで変わるものではないため。

**ブランド色は `{colors.primary}`（青丹）。** shadcn の `primary` は仕様上
"High-emphasis actions and **brand surfaces**" の置き場なので、独自の `brand-*` を作らずここに入れる。
青丹（あをに）は「あをによし」＝奈良の都にかかる枕詞が指す、青（岩緑青）と丹（赤土）という
顔料の対そのもので、713年の官命という出自に直結する。

**出る場所はクロムに限る** — ヘッダのロゴ、リンク、主ボタン、フォーカスリング（`{colors.ring}`）、
ホバー面（`{colors.accent}`）。**データを表す面には出さない** — 流れ図のノード、状態のバッジ、明細のセル。
色が情報を担うのは意味色の役目で、そこにブランド色が混ざると、
読み手はブランド色にも意味があると読む。**「使うか使わないか」ではなく、どちらの役をやらせるか**の線引きである。

⚠️ 青丹の緑は COFOG の大分類 05（`oklch(64% 0.08 145)`）と近い。
**この2つが同じ面に出ないのは上の線引きの結果**で、偶然ではない。
ブランド色をデータの面へ持ち出した瞬間に、この近さが実害になる。

`{colors.mark-rule}`（丹）は UI トークンではない。ロゴのマークの基準線＝短冊が並ぶ「地面」にだけ出る塗りで、
対を意匠として持つのはロゴの側の仕事。画面のトークンには置かない。

**ロゴの「風土記」は本文色（`{colors.foreground}`）で組む。** 色を持つのはマークだけ。
両方に色を付けると、どちらがブランドの主張なのかが割れる。
ヘッダに出すのも**マーク単体**で、文字は入れない — 画面はロゴの明朝を読み込んでいないので、
和文を出せば必ずロゴと違う字形になる。

ダークモードは同じ色相を保ったまま明度だけを上げる（`{colors.primary}` は 43.7% → 76.2%）。
**色相を変えると、その色が意味していたものがテーマによって別物に見える。**

## Typography

`Geist Variable` の可変フォントを 1 本だけ持つ。等幅はパス・識別子・コード片のためだけに使い、
`{typography.mono}` としてシステムの等幅スタックに委ねる。

サイズは 4 段しかない。`{typography.heading}` 20px / `{typography.body}` 14px /
`{typography.label}` 12px・500 / `{typography.caption}` 12px・400。
**14px が本文で、12px が説明とラベル。** これ以上刻まない。

読み物では見出しがこの 4 段の上に出る。本文以下は 4 段のままにする。

**数字は必ず `tabular-nums` で組む。** 金額と行数が縦に並ぶ画面なので、
プロポーショナルな数字だと桁が揃わず、比較のために目が横に泳ぐ。実装でも最も多く現れる指定のひとつ。

### 和文の扱い

欧文は `Geist Variable`、和文は **`Noto Sans JP Variable`**。どちらも webfont として同梱し、
システムフォントに委ねない。**Geist に和文グリフが無い**ので、宣言しなければ日本語は
generic の `sans-serif` に落ち、OS ごとに別の字形で出る
（macOS では Hiragino Kaku Gothic ProN が拾うため、mac だけで見ていると破綻に気づけない）。
`Hiragino Sans` は webfont が落ちてこなかったときの保険として残してある。

条件は2つあった。

**1. ウェイトが連続していること。** この画面は `ELT パイプライン` `COFOG 割当（金額比）` のように
**1行の中で和欧が混ざる**箇所が多く、和文側が必要なウェイトを持たないと、
同じ行の欧文と和文で太さがずれる。使うのは 400 / 500 / 600 の3段。
Zen Kaku Gothic New（300/400/500/700）や BIZ UDPGothic（400/700）は 600 を持たないため落ちる。

**2. 癖が無いこと。** 表と数字が主体の画面で、書体が主張すると読む対象と競合する。
M PLUS 2 は条件1を満たすが仮名が幾何的で、字面に個性が出すぎた。
Noto Sans JP は 100〜900 が連続し、かつ4候補（M PLUS 2 / Noto Sans JP /
IBM Plex Sans JP / Murecho）の中で最も無個性で、字幅も最も詰まっている。
**表が主体の画面では、字幅が詰まっていること自体が情報量になる。**

⚠️ **ロゴは別の書体で組む。** 本文で長所になる無個性は、表示用の文字では短所になる。
ロゴの「風土記」は **Shippori Mincho B1 Bold**（活版印刷の再現を狙った明朝、OFL）で、
`apps/web/brand/build.py` が outline を path に焼いて `logo.svg` / `og.png` を作る。
画面には読み込まれない（ロゴ生成時にしか要らないので devDependency）。

⚠️ **行間も欧文基準のまま。** `{typography.body}` は 20/14 ＝ 1.43、`{typography.label}` は 16/12 ＝ 1.33 で、
日本語本文の標準（1.5〜2.0）より狭い。**表のセルとバッジは短い文字列なので実害が無い**が、
段落として日本語を流す箇所（Caveats、検査の説明文）には `{typography.caption}` の 19.5/12 ＝ 1.625 を使う。
新しく段落を足すときも同じ扱いにする。

改行は本文で `line-break: strict` / `word-break: normal` / `overflow-wrap: break-word`。
`word-break: keep-all` は使わない — 日本語の塊に当てると CJK 文字間の自然な折り返しごと止まる。
ノードのラベルのように**幅が固定で折り返させたくない**箇所は、折り返しを禁じるのではなく
表示幅で切り詰めて `…` を付ける（全角を 2、半角を 1 と数える。文字数で切ると全角で箱を突き抜ける）。

## Layout

**1 カラム、中央寄せ。サイドバーを持たない。**
報告は上から「流れ図 → 検証の指標 → タブで4つの証拠」の一直線で、
読み手が上から下へ読み切れば判断が終わる形にしている。

**最大幅は中身が決める。** 表と流れ図が主体の報告は広く、文章が主体の読み物は
1行が長くなりすぎない幅で止める。**数値は決め打ちにせず、その画面で最も広い要素に合わせる。**

節と節の間は `{spacing.section}`（32px）、節の中の要素は `{spacing.lg}`（16px）、
関連する要素どうしは `{spacing.sm}`（8px）。この 3 段しか使わない。

ヘッダーは 56px 固定で `sticky`、背景は 95% 不透明＋ backdrop-blur。
**画面をまたぐ導線と、いまどの画面にいるかが、スクロールしても消えない**ようにするため。

⚠️ **溢れるものはその要素の中でスクロールさせる。** 流れ図は幅が足りなければ横に、
ノードが増えれば縦に、それ自身がスクロールする。ページ本体をスクロールさせない。

## Elevation & Depth

**Flat。影で階層を作らない。**

カードは影を持たず、`{colors.foreground}` の 10% 不透明のヘアラインリング 1px で縁を取る。
影を落とすと「浮いている＝重要」という序列が生まれるが、この画面では
4 つの指標も 15 個のノードも**互いに対等**で、序列を付けたくない。

影が現れるのはタブの選択状態だけ（`0 1px 3px rgba(0,0,0,.1)`）で、
これは「いまどれを開いているか」を言うための最小限。それ以外に `box-shadow` を足さない。

フォーカスリングだけは例外的に太い（`{components.focus-ring}` の 3px、`{colors.ring}` の 50% 不透明）。
キーボードで辿る画面なので、ここは目立つ方が正しい。

## Shapes

角丸は **控えめに丸い**。カードが 14px（`{rounded.xl}`）、ボタンとノードが 10px（`{rounded.lg}`）、
タブと入力が 8px（`{rounded.md}`）で、`--radius` 10px から派生する。

**完全な円は 2 箇所だけ** — バッジ（`{rounded.pill}`）と、COFOG の大分類の色見本
（2.5px 角の小さな四角。丸ではない）。

表には角丸を付けない。**罫線は角を持ったまま直交させる**。検査成績書の見た目に寄せる意図で、
表だけは意図的に硬い。

## Components

* **Cards:** 背景 `{colors.card}`、14px の角丸、影なし・ヘアラインリングのみ。
  内側は 16px。指標カードはラベル（`{components.card-label}`、12px のミュート）と
  値（`{components.card-value}`、20px）の 2 段組で、値が良否を持つときだけ着色する。
* **Buttons:** 高さ 32px、10px の角丸。既定は `{colors.primary}` の塗り。
  境界線つき（outline）は背景色を持たず、ホバーで `{colors.muted}` に沈む。
  押下時に 1px 下がる以外のアニメーションを持たない。
* **Badges:** 高さ 20px の丸型。既定は `{colors.secondary}` の薄いグレー。
  **検査が落ちているときだけ** `{colors.destructive}` の系統に変わる。
* **Tabs:** 選択されていないタブは `{colors.muted-foreground}`、選択中は前景色に戻り、
  背景と 1px の影が付く。タブの並びは**検証の順**（何を保証しているか → どこから来たか →
  fudoki は何を足したか → 1 行ずつ確かめる）で、機能のグルーピングではない。
* **Tables:** 罫線は水平のみ、`{colors.border}`。ヘッダは 12px・500。
  数値列は右寄せ＋ `tabular-nums`。行の高さは 32px。
* **Flow graph:** ノードを段ごとの列に並べ、依存を実線で引く。
  ノードは**名前と行数だけ**を持ち、詳細は選択したときに別の面へ出す。
  判断が入るのは core 以降だが、それは**列の位置が言う**ので色では言わない。
  ノードに付く印は件数を数字で持ち、**落ちているときだけ** `{colors.destructive}` になる。
  それ以外は `{colors.muted-foreground}`。
* **Inputs:** 高さ 32px、8px の角丸、1px の `{colors.border}`。背景は持たない。
* **Tooltips:** 定義や但し書きの置き場。最大 36 文字幅で折り返す。
  **本文に書けることをツールチップに逃がさない** — 隠した時点で読まれない。
* **Map:** 自治体の境界を素の SVG で描き、押すとその団体の報告へ入る。
  既定は `{colors.accent}`、ホバーで `{colors.primary}` に沈む。
  **全団体が同じ色で、収録の有無を色で言わない** — 色が団体ごとの違いを表さないので、
  これは押せる面を示すクロムであって、データを表す面ではない。
  ⚠️ ホバーは**濃くする方向**へ。薄くすると背景へ近づき、どれを指しているか分かりにくい。
  縮尺が本土と揃わない離島は別枠のタイルに切り出す。実面積に比例させると押せなくなる。

## Do's and Don'ts

**Do**

* 色を足すときは、それが**何の意味を担うか**を先に決める。担うものが無いなら無彩色にする
* 数字を並べる場所では必ず `tabular-nums` を指定する
* 状態は色と**文字**の両方で示す（色覚特性と読み上げに届かせる）
* 日本語の段落には `{typography.caption}` の広い行間を使う
* 新しい指標を足すときは「配布データが正しいか」を判別できるものに限る

**Don't**

* ❌ 影で重要度の序列を作らない。カードは対等
* ❌ `chart-1..5` を使わない。ゼロ彩度で意味を区別できない
* ❌ ダークモードで色相を変えない。明度だけを動かす
* ❌ 意味色を増やさない。増やすなら、位置や数字では言えないことを先に確かめる
* ❌ 判断の有無を色で言わない。段の並びが既に言っている
* ❌ ページ本体を横スクロールさせない。溢れるものはその要素の中でスクロールさせる
* ❌ `word-break: keep-all` を本文に当てない
* ❌ 和文フォントを 1 つだけ指定しない。必ず欧文 → generic まで繋ぐ
* ❌ ブランド色をデータを表す面に使わない（流れ図のノード、状態のバッジ、明細のセル）
* ❌ 画面側で集計しない。数字は `pipeline.json` が出したものをそのまま出す
  （同じ数字が 2 通りに計算されて、いずれ食い違う）
