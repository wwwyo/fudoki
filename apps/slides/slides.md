---
theme: default
title: 風土記
info: 都知事杯オープンデータ・ハッカソン2026 First Stage（2分）
class: text-left
aspectRatio: 16/9
fonts:
  sans: Geist,Noto Sans JP
  serif: Shippori Mincho B1
  mono: Menlo
css: unocss
---

<!-- 1. タイトル。口上: チーム名と作品名、一言で何か -->

<div class="pt-16">
  <h1 class="logo-type !text-5xl">風土記</h1>
  <p class="!mt-4 text-xl">公開されているのに読めない、を読める形にする。</p>
  <p class="f-caption !mt-16">風土記編纂室 ／ 都知事杯オープンデータ・ハッカソン2026</p>
</div>

<style>
h1 { letter-spacing: 0.06em; }
</style>

---

<!-- 2. 課題。昨年の経験 → 今年の壁。ここは数字を出さず一息で -->

## 公開されている。しかし読めない

<div class="mt-6 space-y-4">

- 自治体の予算は全部公開されている。ただし **PDF か、自治体ごとに違う形の CSV**
- 「この市はこの事業にいくら使っているか」を機械で引けない
- デジタル庁のダッシュボードも款・項レベルで止まり、**内訳が読み取れない**

</div>

<p class="f-caption mt-10">昨年の都知事杯に参加して感じたこと: 使えるオープンデータが圧倒的に足りない。</p>

---

<!-- 3. 欠けているのは2つ。粒度と横断性 -->

## 欠けているのは粒度と横断性

<div class="grid grid-cols-2 gap-4 mt-8">
  <div class="f-card">
    <div class="f-label">粒度</div>
    <p class="!mt-2 text-sm">既存の統計は款・項で止まる。<br>事業単位（目）に届かない</p>
  </div>
  <div class="f-card">
    <div class="f-label">横断性</div>
    <p class="!mt-2 text-sm">事業単位の資料は自治体ごとに個別形式。<br>同じ軸で並べられない</p>
  </div>
</div>

<p class="f-caption mt-8">個別自治体 × 事業単位 × 国際分類のデータは、OECD にも Eurostat にも無い。世界共通の空白。</p>

---

<!-- 4. 解決。パイプライン + 標準配布。図をここに（パイプライン画面スクショ or 簡略図） -->

## 解決: 集めて、同じ様式に編んで、標準形式で配る

<div class="mt-6">
  <!-- TODO: fudoki.dev パイプライン画面のスクリーンショット -->
  <img src="/pipeline-placeholder.png" class="border rounded-lg max-h-64 mx-auto" />
</div>

<div class="grid grid-cols-2 gap-4 mt-6">
  <div class="f-nojudgment text-sm">自治体が公表した事実（原典・正本）</div>
  <div class="f-judgment text-sm">風土記の判断（COFOG 割当）は層で分離</div>
</div>

---

<!-- 5. 実績。数字はすべて実測値 -->

## いま配布しているもの

<div class="grid grid-cols-3 gap-4 mt-8">
  <div class="f-card">
    <div class="f-label">団体</div>
    <div class="f-stat">2</div>
    <div class="f-caption">三鷹市・狛江市</div>
  </div>
  <div class="f-card">
    <div class="f-label">配布行数</div>
    <div class="f-stat">55,255</div>
    <div class="f-caption">歳出・歳入・事業名</div>
  </div>
  <div class="f-card">
    <div class="f-label">年度</div>
    <div class="f-stat">7</div>
    <div class="f-caption">予算1 + 決算6</div>
  </div>
</div>

<div class="mt-8 text-sm">

「いじめ問題対策協議会関係費 に **311,000円**」— 事業単位の使途が機械で引ける

</div>

<p class="f-caption mt-6">Fiscal Data Package 1.0.0 + COFOG（国連の政府機能別分類）。団体を足す作業は「宣言を1つ書く」に閉じている。</p>

---

<!-- 6. AI から使える。MCP の話 -->

## AI が自治体財政を直接引ける

<div class="mt-6 space-y-4 text-sm">

- 「この市の教育費の内訳は?」— 現状の AI は原典の PDF を読み解けず答えられない
- 構造化したデータを **API と MCP サーバ**で提供。AI エージェントが直接引ける
- 国際標準の語彙（COFOG）だから、AI が学習済みの分類で答えられる

</div>

<div class="mt-8">
  <!-- TODO: MCP でクエリするデモのスクショ or 1行例 -->
  <div class="f-mono f-card">"狛江市の2023年度、教育費の事業別内訳を出して" → 風土記 MCP → 表</div>
</div>

---

<!-- 7. ロードマップ。自治体版 Open States → その上のプロダクト -->

## まずはデータから

<div class="mt-6 text-sm space-y-3">

1. **いま**: 東京都内の自治体から。パイプラインと配布は OSS（MIT）
2. **次**: 団体を増やす。米国 Open States の自治体財政版になる
3. **その先**: 風土記をデータベースとした個別の課題解決プロダクト

</div>

<div class="mt-8 f-caption">

運営者が消えても止まらない設計: 正本はリポジトリ、CI で更新、fork 可能。API は派生物。

</div>

<div class="mt-8">
  <span class="f-mono">https://fudoki.dev ／ github.com/wwwyo/fudoki</span>
</div>
