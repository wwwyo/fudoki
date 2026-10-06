# E2E

E2E はローカル専用。`@e2e-dev/web` と e2e runner に実行と証跡を統一し、CI では実行しない。
既定の `bun run test` は unit / fixture 検査であり、E2E は含めない。

初回は repo の依存と固定入力を準備する。PDF レイヤには Poppler の
`pdftotext` / `pdftocairo` が必要。

```sh
bun install --frozen-lockfile
uv sync --frozen
bun run pipeline:inputs
bun run pipeline:build
bun run pdf:layer --jurisdiction 132195
bun run test:e2e
```

`test:e2e` は E2E の型を確認し、report を生成して検証画面を 127.0.0.1:5174 に
起動する。実行前に同じポートの dev server を止める。固定入力や PDF レイヤが
未準備でもテストは省略せず失敗する。原典・財政レコードは読み取り専用で、各テストの
ブラウザ context とサーバーの終了は runner が管理する。

結果は `.e2e/report.json`、画像と trace は `.e2e/artifacts/`、サーバーと
fixture 検査の出力は `.e2e/logs/` に保存する。すべて gitignore 対象。

```sh
bun run test:e2e --tag fiscal-history
```

現在のテストは固定 assertion で実行し、モデルを呼ばない。今後 `agent.*` を使う場合は
mise + age の `OPENCODE_API_KEY` と共通設定の `OPENCODE_E2E_MODEL` を runner に渡す。
推論先は OpenCode Go。telemetry は実行コマンドで無効にする。

| テスト / PRD criterion | 確認する内容 |
| --- | --- |
| `pipeline-overview.e2e.ts` | トップから概要への遷移、見出し、目次 |
| 財政予算履歴 AC1 | 当初2明細、符号つき補正3件、決算との対応10件、原典行・頁 |
| 財政予算履歴 AC3 | 2目の年度末差額と、節・収録範囲の未確認表示 |
| 検証画面 AC2 | 当初の取り込み行と staging 行の対応 |
| 検証画面 AC2 | 同じ対象の補正第3号と第6号の分離 |
| 検証画面 AC2/AC3 | 回転した原典 PDF の頁寸法、金額の位置、対応行、単位と補正範囲 |
| 財政予算履歴 AC2/AC4、警告範囲 | 既存の時点・欠測・重複・M:N・文書識別・警告 fixture 検査 |

財政の検査は狛江市2023年度の2目を対象とする。予算全体の復元、事業×節の完全な対応、
公開サービスを確認したものではない。最後の項目は fixture の検査で、実画面の警告を
確認したものとは区別する。データの全量検査は既存の dbt 検査で行う。

系統図の線・PDF の語の選択は旧検査と同じ DOM イベントで行い、選択後の表と紙面の
対応を確認する。密集した SVG の線をマウスで選べるかの検査は含めない。
