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
  <h1>集めて、同じ様式に編んで、標準形式で配る。</h1>
  <div class="mt-6 f-card !p-2 overflow-hidden">
    <img src="/pipeline.png" class="w-full" alt="ELT パイプライン: 取得元 → ingestion → staging → core → package" />
  </div>
  <div class="grid grid-cols-2 gap-4 mt-4 text-sm">
    <div class="f-nojudgment">自治体が公表した事実（原典・正本）</div>
    <div class="f-judgment">風土記の判断（COFOG 割当）は層で分離</div>
  </div>
</div>

---

<!-- 4. Demo: 実物。URL と、事業単位で引ける実例 -->

<div class="h-full flex flex-col justify-center">
  <h1>事業単位の使途が、機械で引ける。</h1>
  <div class="mt-6 f-card">
    <div class="f-mono">「いじめ問題対策協議会関係費」はいくら?</div>
    <div class="f-stat mt-2">311,000 <span class="text-sm">円</span></div>
    <div class="f-caption">三鷹市 令和6年度 ／ 教育費 > 教育総務費 > 教育指導費</div>
  </div>
  <p class="mt-6 f-mono">https://fudoki.dev</p>
</div>

---

<!-- 5. Technology: 技術軸。宣言・層・検査 -->

<div class="h-full flex flex-col justify-center">
  <h1>自治体を足す作業は、宣言を1つ書くだけ。</h1>
  <div class="grid grid-cols-3 gap-4 mt-8 text-sm">
    <div class="f-card">
      <div class="f-label">自治体差は宣言で吸収</div>
      <p class="!mt-2">金額の単位、文字コード、科目の書式。自治体ごとの癖はコードに埋めず <span class="f-mono">sources.toml</span> に宣言する</p>
    </div>
    <div class="f-card">
      <div class="f-label">事実と判断を層で分離</div>
      <p class="!mt-2">自治体が公表した事実（正本）と風土記の判断（COFOG 割当）を分け、境界は dbt のテストで守る</p>
    </div>
    <div class="f-card">
      <div class="f-label">検査が落ちたら配らない</div>
      <p class="!mt-2">原文の復元・行数の一致など42検査。1つでも落ちると下流の配布物を作らない</p>
    </div>
  </div>
  <p class="f-caption mt-8">ingestion(Python) → Parquet / DuckDB → dbt → Fiscal Data Package 1.0.0（国際標準）。</p>
</div>

---

<!-- 6. Why now: AI。MCP で直接引ける -->

<div class="h-full flex flex-col justify-center">
  <h1>AI は PDF の予算書に答えられない。<br>構造化データなら答えられる。</h1>
  <div class="mt-4 f-card !p-3 overflow-hidden">
    <img src="/mcp-demo.png" class="w-full max-h-64 object-contain" alt="Claude が fudoki MCP で三鷹市のいじめ対策費を引いて答える" />
  </div>
  <p class="f-caption mt-3">API と MCP サーバで提供。国際標準の語彙（COFOG）だから、AI が学習済みの分類で答えられる。</p>
</div>

---

<!-- 7. 将来の展望（最終スライド） -->

<div class="h-full flex flex-col justify-center">
  <h1>自治体財政の Open States になる。</h1>
  <div class="grid grid-cols-3 gap-4 mt-8 text-sm">
    <div class="f-card">
      <div class="f-label">① 何にいくら</div>
      <p class="!mt-2">予算・決算<br><span class="f-mono">Fiscal Data Package</span></p>
    </div>
    <div class="f-card">
      <div class="f-label">② いつ何が公告されたか</div>
      <p class="!mt-2">調達<br><span class="f-mono">OCDS</span></p>
    </div>
    <div class="f-card">
      <div class="f-label">③ どう決まったか</div>
      <p class="!mt-2">議会の会議録<br><span class="f-mono">Popolo</span></p>
    </div>
  </div>
  <div class="mt-8 space-y-2 text-sm">

  - 3つのレイヤを既存の国際標準に載せ、同じキーで繋ぐ。東京都内から全国へ
  - 個別の課題解決プロダクトは、このデータベースの上に作っていく

  </div>
  <p class="mt-8 f-mono">https://fudoki.dev ／ github.com/wwwyo/fudoki</p>
</div>
