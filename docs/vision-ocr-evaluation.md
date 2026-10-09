# Vision OCRの欠落セル・前処理の検証記録

2026-10-07の実スキャン1頁では、列ごとのOCRで欠落したセルだけを再読する方法が最も多くの金額セルに一致した。全セルの切り出しや罫線除去は、一律に改善する処理ではなかった。

本書は比較結果と調査根拠を保存する。実行フローは [pipelineスキルのingestion](../.agents/skills/pipeline/references/ingestion.md)、エンジン選定は [ADR 0017](adr/0017-vision-for-coordinate-preserving-ocr.md)、API・出力形式は [OCRモジュールの説明](../pipeline/ingestion/lib/vision_ocr.md) を参照する。

## 評価した原典と条件

- 原典: 多摩市の[令和2年度決算書第4分冊](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/929/020499.pdf)、物理2頁・印刷75頁。
- 原典SHA-256: `a6d067d5860a4f2a7ba71386522ec1227fd97b2020fb0c1e6c9bbf4be0c45e4e`。
- 表は600dpi・1bitの画像。本文の文字層は利用できず、文字層から取れたのは頁番号だけだった。
- 環境: macOS 27.0 build 26A428、arm64、Apple Vision `VNRecognizeTextRequest`、accurate、revision 3、日本語・英語。
- 本書の主要比較: CoreGraphicsで300dpi・2480×3509pxに描画。言語補正on、別管理の名称語彙18語、`minimumTextHeight=0`。各条件を2回実行した。
- 金額109セルは原典画像から目視転記した。セルの境界は罫線から独立に宣言し、観測枠の位置で対応付けた。正解の値を使って読み取り領域を選ばず、比較時だけ空白・桁区切りのカンマを除いた。

初期のPoppler描画の実験はADRに記録している。本書のCoreGraphics描画と分けて扱い、名称の誤読や欠落位置の変化を同一の実行結果にまとめない。

## 列ごとのOCRと欠落セルの再読

| 方法 | 金額の一致 | 未検出 | 観測ありの不一致 |
| --- | --- | --- | --- |
| 300dpi・全頁 | 91/109 | 18 | 0 |
| 300dpi・金額4列 | 107/109 | 2 | 0 |
| 金額4列と欠落2セルの再読 | 109/109 | 0 | 0 |

欠落セルは表の25行目の支出済額と翌年度繰越額だった。初回に観測がないことだけで対象を選び、セルの内側を5px狭めて再読すると、それぞれ実際の文字列 `0` が取得できた。空欄の0補完や合計からの推測はしていない。上表の件数は2回とも同じだった。

再読2セルの追加推論は0.242秒と0.205秒、描画・Swift実行を含む追加時間は1.341秒と1.232秒だった。少数回・同一環境の値であり、一般的な処理時間を保証しない。

全109セルを初回から切り出す別試行は104/109だった。このため「すべてをセル単位で読めば改善する」とは言えない。

## minimumTextHeightを下げても欠落は改善しなかった

未指定時の実測値は0だった。0.003、0.001、0.0001、0を指定しても、全頁91/109・列ごと107/109のままだった。0.01では全頁88/109、0.03125では19/109となり、観測された文字にも不一致が生じた。列ごとは両条件とも107/109だった。

この環境では既に値が0だったため、閾値をさらに下げる対処は成立しなかった。指定値だけでなく実際のリクエストの値を記録する必要がある。

## 罫線除去は部分的な改善と悪化の両方があった

CoreGraphics描画と同じ画素の画像を対照にし、画像サイズ・回転・座標は変えずに比較した。灰度200未満の画素から、横120×1・縦1×120のmorphological openingで罫線を検出した。「細い除去」はそのマスクだけを白くし、「周囲も除去」は3×3の膨張で周囲1pxも白くした。

| 画像 | 全頁の一致 | 列ごとの一致 | 列ごとの未検出 | 列ごとの観測ありの不一致 |
| --- | --- | --- | --- | --- |
| 対照画像 | 91/109 | 107/109 | 2 | 0 |
| 細い罫線除去 | 90/109 | 108/109 | 1 | 0 |
| 罫線と周囲1pxの除去 | 83/109 | 102/109 | 7 | 0 |

件数は2回とも同じだった。細い除去では支出済額の0を取得できたが、翌年度繰越額の0は欠落したままだった。周囲も消す方法は悪化した。セル内側10pxの範囲で黒画素の除去は観測されなかったが、文字を厳密に無傷で保ったことの証明にはならない。

## 孤立した文字・数字についての公開報告

- [単独数字とROIの実験報告](https://stackoverflow.com/questions/48127045/apple-vision-cant-recognize-a-single-number-as-region): 単独の9や22を検出できない事例と、文字に対して読み取り領域を狭める改善例がある。一部の文字では幅・高さが文字の約3倍のROIで改善した。全体OCR後に空白領域だけ再読する方法も提案されている。内部の検出処理についての説明は投稿者の仮説である。
- [Apple Developer Forums、2026年8月](https://developer.apple.com/forums/thread/842742): 手書きの単独文字が空結果になり、線を太くすると改善した報告。Apple DTSはaccurateと別revisionの比較を勧めている。印字された0の原因や公式修正を確認した回答ではない。
- [白い余白を付ける実験報告](https://stackoverflow.com/questions/79146582/vnrecognizetextrequest-fails-but-can-select-text-in-preview-app): 中国語画像で空結果だったOCRが白い余白の追加で成功した。対象画像では40pxが有効だったが、一般的な最適値ではない。孤立した0の直接の検証でもない。

今回の結果から、領域の大きさや周辺配置が関係する可能性はある。ただしAPIの空結果だけでは、文字領域の検出と認識後の候補破棄を区別できない。原因は未確定として扱う。

## 評価範囲と実験ファイル

本評価は1頁・既知のセル座標に限る。一般的なセル検出器は未実装で、別自治体・別書式・全頁での精度、事業階層の復元、長時間処理は検証していない。観測があるセルの数値一致と全セルの検出を分け、再読の成功を原典全体の正しさへ広げない。

以下はGit管理外のローカル実験ファイルである。本書には主要条件と集計値を保存した。

- [手動の照合基準](../.agent/pdf-samples/vision-real-scan/visual-reference.json)
- [欠落セル再読の実験コード](../.agent/pdf-samples/vision-real-scan/test_missing_cell_retry.py)・[評価結果](../.agent/pdf-samples/vision-real-scan/missing-cell-retry-evaluation.json)
- [閾値比較の実験コード](../.agent/pdf-samples/vision-real-scan/test_minimum_height.py)・[評価結果](../.agent/pdf-samples/vision-real-scan/minimum-height-evaluation.json)
- [別の切り出し方法の実験コード](../.agent/pdf-samples/vision-real-scan/test_zero_alternatives.py)・[評価結果](../.agent/pdf-samples/vision-real-scan/zero-alternatives-evaluation.json)
- [罫線除去の実験コード](../.agent/pdf-samples/vision-real-scan/test_line_removal.py)・[評価結果](../.agent/pdf-samples/vision-real-scan/line-removal-evaluation.json)・[比較レポート](../.agent/pdf-samples/vision-real-scan/line-removal-report.html)
