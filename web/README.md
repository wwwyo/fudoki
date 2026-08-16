# web — ビューア

いずれも `_*.js` にデータを埋め込んだ単一 HTML。**データは生成物なので gitignore**（正本は `data/` 配下にある）。

```bash
bun run dev   # データを生成して http://localhost:4317 で配信
```

| ファイル | 見るもの | データ源 |
|---|---|---|
| `survey.html` | ③ 会議録レイヤの権利判定（62団体） | `src/extract/sources/manifest.json` → `_data.js` |
| `pipeline.html` | ① 予算レイヤのパイプラインと明細 | `data/reports/*.json` と `data/packages/**` → `_pipeline.js` |

`pipeline.html` を開く前に `bun run build:budget` が必要（成果物が無いとデータを生成できない）。

## pipeline.html が見せるもの

- **段のフロー** — 原典 → Extract → Load（正本）→ Transform（派生）。
  Load と Transform の間に「ここから判断」の境界を引いてある。この境界が設計の中心で、
  正本は原文と突き合わせて検証でき、COFOG の割り当てだけが fudoki の判断になる
- 各段の入力・出力・差分、1行がどう変わったかの実例、検査30件の結果
- COFOG のディビジョン別金額、款ごとの割当先と根拠、どの単位で決まったか、連結の消去
- **明細を辿る** — 会計から細々節まで階層を降りる。事項名で絞り込める。
  末端では `budget_line_id`・原典の行番号・割当の根拠・適用した規則まで出る

報告 Markdown（`data/reports/*.md`）と同じ数字を見ている。
集計は `buildReportData` の1箇所だけで行い、Markdown と JSON はその結果を整形しているため。

## なぜ DuckDB-Wasm を使っていないか

62行の表や 5,613 行の明細に WASM ランタイムを積むのは重すぎ、CDN 依存も増える。
データを埋め込んだ単一 HTML なら即開けてオフラインでも動く。
**発言データ（数十万行）を扱う段になったら DuckDB-Wasm を入れる**。

## なぜ正本の CSV を直接 fetch していないか

そうするとリポジトリのルートを配信するサーバが要り、成果物以外まで露出する。
`_pipeline.js` は画面が使う列だけを列指向に詰め直した派生物で、`bun run build:pipeline-view` で再生成できる。
