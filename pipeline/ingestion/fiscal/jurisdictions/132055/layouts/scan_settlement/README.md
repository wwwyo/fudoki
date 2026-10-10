# 青梅市の scan 決算見開き

`convert(inputs, destination, options)` は選定済みPDFのSHAとscope、凍結したnative OCR、書式設定を照合し、未使用dirへParquetと検算用観測を生成する。年度・会計ごとにconverterを複製せず、原典ごとの頁・セル枠・説明階層はlayoutで宣言する。共通の `pdf_table`・`conversion.write_conversion` を使い、実行中のOCR・ネットワーク・正式manifest更新は行わない。

現在のlayoutは132055 FY2025の `settlement-2.pdf`（SHA `1cbe6a08f3f3dd4dee36e61f6964d64107e81e9fe3dcc5c64def39e2743c7526`）、一般会計の議会費、物理1–4頁・印字92–95だけに対応する。一般会計全14PDF/274頁や他会計の収録完了を表さない。

- `details.parquet`: 備考の最細項目44行50列。款・項・目の独立印字金額と事業・費目・子の所属を通常列へ展開する。金額は原典のcomma・符号・0を保持したVARCHAR、物理頁2列のみBIGINT。NULLは子や人数注記の非適用であり、0や未読を意味しない。
- `candidate-observations.json`: 法定節14行、款項目の独立統制行3行、備考ノード、目に属する末尾計、括弧付き目継続、原画確認空欄、単位・頁脚など。検算観測はrawへ入れない。
- `bindings.json`: 全region観測のnative SHA・実観測ID・原文字・原位置・分類、原典cellからraw列/行への対応。word/numberを含む全下位観測と検出/認識結果は元nativeに不変保持する。
- `headers.json`: 原見出し・多段階層・結合範囲・本文列への対応とnative参照。
- `metadata.json` / `receipt.json`: 金額の役割、元cellの非加算参照とgrain、単位、実schema、SHA、局所訂正と共通辞書照合の結果。

`備考_末端金額` が唯一の末端加算列。反復した親の額は元cellへの非加算参照で、合計へ重ねて加えない。法定節と説明の同じ高さや同名から意味上の所属を作らない。説明内で確認済みの節見出しが無いため節との対応は未確認で、source-only名称を共通名称へ昇格しない。

当初予算額、補正増減、継続/前年度繰越成分、予備費/流用増減、予算現額計を分離する。支出済額・備考説明はexecutedで、翌年度繰越の3欄と不用額を別に保持する。一般職給11人と再任用1人は一つの金額に付く一組の人数注記。継続頁を新しい目として数えず、末尾計は事業3に属させない。

`corrections.json` の6金額観測は、原画確認によるOCR挿入空白だけの局所訂正。comma/digits/符号/0を変えず、原典SHA・頁・bbox・native SHA・実ID・beforeでfail closedにする。`source-confirmations.json` は複数行見出しと括弧の原画確認による復元条件。原nativeを上書きせず、全自動OCRによる復元とは扱わない。共有名称辞書の全名称照合も記録し、この原典では適用0件。

再生例（repo root。出力dirは未使用であること）：

```sh
mise exec -- uv run --frozen python pipeline/ingestion/fiscal/jurisdictions/132055/layouts/scan_settlement/convert.py \
  --inputs pipeline/ingestion/fiscal/observations/scan-2025-codex-2026-10-09/132055/general/settlement-2/inputs-001.json \
  --options pipeline/ingestion/fiscal/observations/scan-2025-codex-2026-10-09/132055/general/settlement-2/options-002.json \
  --output pipeline/ingestion/fiscal/observations/scan-2025-codex-2026-10-09/132055/general/settlement-2/replay-new
```

この例は凍結nativeからの再構築で、PDFからOCRを再実行するものではない。通常CLIの正式配置を回避せず、正式manifest・R2・dbtへの採用は別の管理作業へ残す。候補の原典照合と受容は独立operatorが行い、構築側の合計一致・再生一致はその代わりにならない。
