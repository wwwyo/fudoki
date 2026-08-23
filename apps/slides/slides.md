---
theme: default
title: 風土記
info: 都知事杯オープンデータ・ハッカソン2026 First Stage（2分・YC pitch 形式）
class: text-left
aspectRatio: 16/9
fonts:
  sans: Geist,Noto Sans JP
  serif: Shippori Mincho B1
  mono: Menlo
css: unocss
---

<!-- 1. 表紙: ロゴ + 一言。YC 流に会社(作品)が何かを1文で言い切る -->

<div class="h-full flex flex-col items-center justify-center text-center">
  <img src="/logo.svg" class="h-16" alt="風土記" />
  <p class="!mt-8 text-xl">公開されているのに読めない、を読める形にする。</p>
  <p class="f-caption !mt-12">風土記編纂室 ／ 都知事杯オープンデータ・ハッカソン2026</p>
</div>

---

<!-- 2. Problem: 1枚1メッセージ。数字も装飾もなし -->

<div class="h-full flex flex-col justify-center">
  <p class="f-label mb-4">Problem</p>
  <h1>自治体の予算は全部公開されている。<br>しかし機械で読めない。</h1>
  <div class="mt-8 space-y-3 text-sm">

  - PDF か、自治体ごとに違う形の CSV
  - 「この市はこの事業にいくら使っているか」を引けない
  - デジタル庁のダッシュボードも款・項で止まり、内訳が読めない

  </div>
  <p class="f-caption mt-8">昨年の都知事杯に出て痛感した: 使えるオープンデータが圧倒的に足りない。</p>
</div>

---

<!-- 3. Solution: 何をするかを1文 + パイプライン図 -->

<div class="h-full flex flex-col justify-center">
  <p class="f-label mb-4">Solution</p>
  <h1>集めて、同じ様式に編んで、標準形式で配る。</h1>
  <div class="mt-6 f-card h-52 flex items-center justify-center">
    <!-- TODO: fudoki.dev パイプライン画面のスクリーンショットに差し替え -->
    <span class="f-caption">（パイプライン画面のスクリーンショット）</span>
  </div>
  <div class="grid grid-cols-2 gap-4 mt-4 text-sm">
    <div class="f-nojudgment">自治体が公表した事実（原典・正本）</div>
    <div class="f-judgment">風土記の判断（COFOG 割当）は層で分離</div>
  </div>
</div>

---

<!-- 4. Demo: 実物。URL と、事業単位で引ける実例 -->

<div class="h-full flex flex-col justify-center">
  <p class="f-label mb-4">Demo</p>
  <h1>事業単位の使途が、機械で引ける。</h1>
  <div class="mt-6 f-card">
    <div class="f-mono">「いじめ問題対策協議会関係費」はいくら?</div>
    <div class="f-stat mt-2">311,000 <span class="text-sm">円</span></div>
    <div class="f-caption">三鷹市 令和6年度 ／ 教育費 > 教育総務費 > 教育指導費</div>
  </div>
  <p class="mt-6 f-mono">https://fudoki.dev</p>
</div>

---

<!-- 5. Traction: 実測値だけ。stat カード3枚 -->

<div class="h-full flex flex-col justify-center">
  <p class="f-label mb-4">Traction</p>
  <h1>2団体、55,255行を配布中。</h1>
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
  <p class="f-caption mt-8">Fiscal Data Package 1.0.0 + COFOG。団体を足す作業は「宣言を1つ書く」に閉じた。</p>
</div>

---

<!-- 6. Why now: AI。MCP で直接引ける -->

<div class="h-full flex flex-col justify-center">
  <p class="f-label mb-4">Why now</p>
  <h1>AI は PDF の予算書に答えられない。<br>構造化データなら答えられる。</h1>
  <div class="mt-8 f-card">
    <div class="f-mono">"狛江市の2023年度、教育費の事業別内訳は?" → 風土記 MCP → 表</div>
  </div>
  <p class="f-caption mt-6">API と MCP サーバで提供。国際標準の語彙（COFOG）だから、AI が学習済みの分類で答えられる。</p>
</div>

---

<!-- 7. Vision: 市場と行き先。自治体版 Open States -->

<div class="h-full flex flex-col justify-center">
  <p class="f-label mb-4">Vision</p>
  <h1>自治体財政の Open States になる。</h1>
  <div class="mt-8 space-y-3 text-sm">

  1. **いま**: 東京都内の自治体から。パイプラインと配布は OSS（MIT）
  2. **次**: 団体を増やす。個別自治体 × 事業単位 × 国際分類は世界にまだ無い
  3. **その先**: 風土記をデータベースとした個別の課題解決プロダクト

  </div>
  <div class="mt-8 f-caption">運営者が消えても止まらない: 正本はリポジトリ、CI で更新、fork 可能。</div>
  <p class="mt-4 f-mono">https://fudoki.dev ／ github.com/wwwyo/fudoki</p>
</div>
