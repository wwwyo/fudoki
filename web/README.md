# web — ELT ダッシュボード

Vite + React + TypeScript + shadcn/ui（Base UI）。

```bash
bun run dev      # リポジトリのルートから。データを生成して Vite を上げる
bun run build:web
```

先に `bun run pipeline` が要る（成果物が無いと報告を作れない）。

## 何を見る道具か

**ELT の全体像を把握する**。段の流れ、各段の入出力、どの検査がどこを守っているか、
COFOG の判断がどこで入りどう割れたか、そして明細。

## パイプラインの形はデータから来る

流れ図は `report.topology` を描くだけで、**段の名前も並びもこの画面に持たない**。

旧ビューアは段を文字列で直書きしていたため、パイプラインを変えても図が変わらなかった。
実装と表示が食い違っても誰も気づかない状態で、ELT の全体像を見る道具としては致命的だった。
段・ノード・辺は dbt の `manifest.json` から来る（`report/build.py`）。画面はそれを描くだけ。

帯の太さの単位は**行数ひとつ**に固定してある。行数と金額を同じ図に混ぜると、
太さが何を表しているのか読めなくなる。金額は別の図が持つ。

## 型はパイプライン本体から取る

```ts
import type { ReportData } from '@/lib/report'   // 型の正本は画面側が持つ
```

`web/` 側で形を写さない。`ReportData` のフィールド名を変えると **`web` の typecheck が落ちる**
（検証済み: `decidedAtLevel` を改名すると `cofog-panel.tsx` がエラーになる）。

旧ビューアは素の JS で 26 箇所を読んでいて、この検査が一切効いていなかった。

⚠️ `typecheck` は `tsc -b` である必要がある。`tsconfig.json` は `files: []` の
solution file なので、`tsc --noEmit` だと**参照先を辿らず何も検査しない**。
scaffold の既定がそれだったため、しばらく無意味な「通過」を見ていた。

## 色は意味を持たせる

`--chart-1..5` は使わない（base-nova の chart 系はゼロ彩度のグレーで、
判断の有無も分類の状態も区別できない）。`src/index.css` に概念名で定義する。

| トークン | 意味 |
|---|---|
| `--stage-nojudgment` | 原典・正本。fudoki の判断が入っていない側 |
| `--stage-judgment` | 派生。判断が入った側 |
| `--judgment-boundary` | Load と Transform のあいだの境界 |
| `--status-assigned` / `--status-unclassifiable` / `--status-out-of-scope` | 分類の軸 |

COFOG のディビジョンは色で区別するが、**コードは必ず文字でも出す**
（色だけだと色覚特性のある読者と読み上げに届かない）。

## 集計しない

数字はすべて `data/reports/*.json`（`report/build.py` の出力）をそのまま出す。
画面側でも集計すると、同じ数字が2通りに計算されて、いずれ食い違ったまま気づかなくなる。

## データの受け渡し

`scripts/build-pipeline-view.ts` が `web/public/pipeline.json` を生成する（gitignore）。
報告（90KB）と明細（列指向に詰め直した 5,613 + 821 行）を1ファイルに入れ、**入口を1つに保つ**。
バンドルへ入れないのは、明細が数 MB あって初回表示までの待ちがそのぶん伸びるため。
