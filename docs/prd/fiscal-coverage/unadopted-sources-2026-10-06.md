# 原典対象ごとの採用対応がない範囲

2026-10-06。既存の原典一覧と現在の固定入力の宣言を、取得・OCRなしで照合した結果。

対象は掲載 1050 レコード、採用 658 入力。全公開資料の探索完了ではない。

## 選択ルール

自治体・年度・会計・当初／補正号／決算ごとに、正式な最新版の中からCSV、文字PDF、画像PDFの順に選ぶ。同じ版・形式なら公式財政ページを優先する。

版の順序が不明な場合は優先候補だけを示し、canonicalは未確定。確認日・ページ更新日・ファイル名の日付を改訂日にしない。新しい原典ハッシュの計算は0。

## 集計

| 自治体 | 採用対応なしの対象 | 他の掲載候補・原典に採用入力あり | 会計・号などの未確定資料 |
|---|---:|---:|---:|
| 千代田区 | 22 | 0 | 49 |
| 三鷹市 | 177 | 5 | 23 |
| 昭島市 | 22 | 4 | 62 |
| 狛江市 | 22 | 48 | 84 |
| 多摩市 | 85 | 8 | 75 |

件数は自治体×年度×会計×段階／補正号の対象数。一つのPDFに複数対象がある。旧451資料レコードとは分母が異なり、差分を処理済み件数にしない。

資料の採用入力はあるが会計への対応が不明な対象は 5 件。上の未採用へ加算せず、詳細はJSONの `account_adoption_unconfirmed` を参照する。CSVの全原文取り込みと観測済み会計集合が対応する場合だけ、会計ごとの入力存在へ反映する。

採用入力ありは、一部の表・観測・別版の宣言が存在することまでであり、全明細・最新版・提供データの確認完了ではない。表紙・目次だけの資料を採用済み明細へ数えず、目次だけに基づく粒度の観測も未確認へ分ける。

同じ対象の版順未確認は 108 対象。以下の未採用数と重複するため加算しない。

再生成: `bun run sources:canonical --markdown > docs/prd/fiscal-coverage/unadopted-sources-2026-10-06.md`。機械可読の全候補・採用path・未確定理由は `bun run sources:canonical --json`。

## 採用対応がない対象の全一覧

既存候補に紐づく入力も、同じ対象の会計名・年度・資料種別・補正号を明示する入力も見つからない対象。実未収録の確定には、未確定資料や一覧未登録の入力との対応確認が必要。

| 自治体 | 年度 | 会計 | 段階／号 | 優先候補 | 版の順序 |
|---|---:|---|---|---|---|
| 千代田区 | 2022 | 一般会計 | 補正第1号 | [令和4年度一般会計補正予算第1号（PDF：577KB）](https://www.city.chiyoda.lg.jp/documents/583/r4yosansho-1.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2022 | 一般会計 | 補正第2号 | [令和4年度一般会計補正予算第2号（PDF：576KB）](https://www.city.chiyoda.lg.jp/documents/583/r4yosansho-2.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2022 | 一般会計 | 補正第3号 | [令和4年度一般会計補正予算第3号（PDF：528KB）](https://www.city.chiyoda.lg.jp/documents/583/r4yosansho-3.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2022 | 一般会計 | 補正第4号 | [令和4年度一般会計補正予算第4号（PDF：558KB）](https://www.city.chiyoda.lg.jp/documents/583/r4yosansho-4.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2023 | 一般会計 | 補正第1号 | [令和5年度一般会計補正予算第1号（PDF：394KB）](https://www.city.chiyoda.lg.jp/documents/583/r5yosansho-1.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2023 | 一般会計 | 補正第2号 | [令和5年度一般会計補正予算第2号（PDF：501KB）](https://www.city.chiyoda.lg.jp/documents/583/r5yosansho-2.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2023 | 一般会計 | 補正第3号 | [令和5年度一般会計補正予算第3号（PDF：410KB）](https://www.city.chiyoda.lg.jp/documents/583/r5yosansho-3.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2023 | 一般会計 | 補正第4号 | [令和5年度一般会計補正予算第4号（PDF：470KB）](https://www.city.chiyoda.lg.jp/documents/583/r5yosansho-4_1.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2023 | 一般会計 | 補正第5号 | [令和5年度一般会計補正予算第5号（PDF：531KB）](https://www.city.chiyoda.lg.jp/documents/583/r5yosansho-5.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2024 | 一般会計 | 補正第1号 | [令和6年度一般会計補正予算第1号（PDF：424KB）](https://www.city.chiyoda.lg.jp/documents/583/r6yosansho-1.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2024 | 一般会計 | 補正第2号 | [令和6年度一般会計補正予算第2号（PDF：535KB）](https://www.city.chiyoda.lg.jp/documents/583/r6yosansho-2.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2024 | 一般会計 | 補正第3号 | [令和6年度一般会計補正予算第3号（PDF：400KB）](https://www.city.chiyoda.lg.jp/documents/583/r6yosansho-3.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2024 | 一般会計 | 補正第4号 | [令和6年度各会計予算（一般会計補正予算第4号・介護保険特別会計補正予算第1号）（PDF：762KB）](https://www.city.chiyoda.lg.jp/documents/583/r6kaikeiyosan-2.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2024 | 介護保険特別会計 | 補正第1号 | [令和6年度各会計予算（一般会計補正予算第4号・介護保険特別会計補正予算第1号）（PDF：762KB）](https://www.city.chiyoda.lg.jp/documents/583/r6kaikeiyosan-2.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2025 | 一般会計 | 補正第1号 | [令和7年度一般会計補正予算第1号（PDF：334KB）](https://www.city.chiyoda.lg.jp/documents/583/r7yosansho-1.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2025 | 一般会計 | 補正第2号 | [令和7年度一般会計補正予算第2号（PDF：337KB）](https://www.city.chiyoda.lg.jp/documents/583/r7yosansho-2.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2025 | 一般会計 | 補正第3号 | [令和7年度一般会計補正予算第3号（PDF：433KB）](https://www.city.chiyoda.lg.jp/documents/583/r7yosansho-3.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2025 | 一般会計 | 補正第4号 | [令和7年度一般会計補正予算第4号（PDF：373KB）](https://www.city.chiyoda.lg.jp/documents/583/r7yosansho-4.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2025 | 一般会計 | 補正第5号 | [令和7年度一般会計補正予算第5号（PDF：578KB）](https://www.city.chiyoda.lg.jp/documents/583/r7hoseiyosan.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2026 | 一般会計 | 補正第1号 | [令和8年度一般会計補正予算第1号（PDF：404KB）](https://www.city.chiyoda.lg.jp/documents/583/r8yosansho-1.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2026 | 一般会計 | 補正第2号 | [令和8年度一般会計補正予算第2号（PDF：342KB）](https://www.city.chiyoda.lg.jp/documents/583/r8yosansho-2.pdf) | 候補1件（最新版の網羅確認なし） |
| 千代田区 | 2026 | 一般会計 | 補正第3号 | [令和8年度一般会計補正予算第3号（PDF：395KB）](https://www.city.chiyoda.lg.jp/documents/583/r8yosansho-3.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2005 | 一般会計 | 補正第2号 | [平成17年度補正予算（PDF 584KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2005 | 一般会計 | 補正第4号 | [平成17年度補正予算（PDF 584KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2005 | 下水道事業特別会計 | 補正第1号 | [平成17年度補正予算（PDF 584KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2005 | 介護保険事業特別会計 | 補正第1号 | [平成17年度補正予算（PDF 584KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2005 | 国民健康保険事業特別会計 | 補正第1号 | [平成17年度補正予算（PDF 584KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2005 | 老人医療特別会計 | 補正第1号 | [平成17年度補正予算（PDF 584KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2005 | 老人医療特別会計 | 補正第2号 | [平成17年度補正予算（PDF 584KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2008 | 一般会計 | 補正第1号 | [平成20年度補正予算（PDF 113KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_9.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2008 | 一般会計 | 補正第3号 | [平成20年度補正予算（PDF 113KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_9.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2008 | 一般会計 | 補正第5号 | [平成20年度補正予算（PDF 113KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_9.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2008 | 一般会計 | 補正第6号 | [平成20年度補正予算（PDF 113KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_9.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2008 | 介護保険事業特別会計 | 補正第1号 | [平成20年度補正予算（PDF 113KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_9.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2008 | 介護保険事業特別会計 | 補正第2号 | [平成20年度補正予算（PDF 113KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_9.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2008 | 老人医療特別会計 | 補正第1号 | [平成20年度補正予算（PDF 113KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_9.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2009 | 一般会計 | 補正第1号 | [平成21年度補正予算（PDF 201KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_8.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2009 | 一般会計 | 補正第3号 | [平成21年度補正予算（PDF 201KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_8.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2009 | 一般会計 | 補正第5号 | [平成21年度補正予算（PDF 201KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_8.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2009 | 一般会計 | 補正第6号 | [平成21年度補正予算（PDF 201KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_8.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2009 | 介護保険事業特別会計 | 補正第1号 | [平成21年度補正予算（PDF 201KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_8.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2009 | 国民健康保険事業特別会計 | 補正第1号 | [平成21年度補正予算（PDF 201KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_8.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2009 | 後期高齢者医療特別会計 | 補正第1号 | [平成21年度補正予算（PDF 201KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_8.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2009 | 老人医療特別会計 | 補正第1号 | [平成21年度補正予算（PDF 201KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_8.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2010 | 一般会計 | 補正第1号 | [平成22年度補正予算（PDF 236KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_7.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2010 | 一般会計 | 補正第2号 | [平成22年度補正予算（PDF 236KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_7.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2010 | 一般会計 | 補正第4号 | [平成22年度補正予算（PDF 236KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_7.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2010 | 介護保険事業特別会計 | 補正第1号 | [平成22年度補正予算（PDF 236KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_7.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2010 | 国民健康保険事業特別会計 | 補正第1号 | [平成22年度補正予算（PDF 236KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_7.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2010 | 老人医療特別会計 | 補正第1号 | [平成22年度補正予算（PDF 236KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_7.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2010 | 老人医療特別会計 | 補正第2号 | [平成22年度補正予算（PDF 236KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_7.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2011 | 一般会計 | 補正第1号 | [平成23年度補正予算（PDF 506KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_6.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2011 | 一般会計 | 補正第2号 | [平成23年度補正予算（PDF 506KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_6.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2011 | 一般会計 | 補正第3号 | [平成23年度補正予算（PDF 506KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_6.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2011 | 一般会計 | 補正第4号 | [平成23年度補正予算（PDF 506KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_6.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2011 | 介護保険事業特別会計 | 補正第1号 | [平成23年度補正予算（PDF 506KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_6.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2011 | 国民健康保険事業特別会計 | 補正第1号 | [平成23年度補正予算（PDF 506KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_6.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2011 | 後期高齢者医療特別会計 | 補正第1号 | [平成23年度補正予算（PDF 506KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_6.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2012 | 一般会計 | 補正第1号 | [平成24年度補正予算（PDF 618KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_5.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2012 | 一般会計 | 補正第2号 | [平成24年度補正予算（PDF 618KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_5.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2012 | 一般会計 | 補正第3号 | [平成24年度補正予算（PDF 618KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_5.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2012 | 一般会計 | 補正第4号 | [平成24年度補正予算（PDF 618KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_5.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2012 | 一般会計 | 補正第5号 | [平成24年度補正予算（PDF 618KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_5.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2012 | 一般会計 | 補正第6号 | [平成24年度補正予算（PDF 618KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_5.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2012 | 介護保険事業特別会計 | 補正第1号 | [平成24年度補正予算（PDF 618KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_5.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2012 | 国民健康保険事業特別会計 | 補正第1号 | [平成24年度補正予算（PDF 618KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_5.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2012 | 後期高齢者医療特別会計 | 補正第1号 | [平成24年度補正予算（PDF 618KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_5.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2014 | 一般会計 | 補正第1号 | [平成26年度補正予算（PDF 566KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_3.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2014 | 一般会計 | 補正第2号 | [平成26年度補正予算（PDF 566KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_3.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2014 | 一般会計 | 補正第3号 | [平成26年度補正予算（PDF 566KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_3.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2014 | 一般会計 | 補正第4号 | [平成26年度補正予算（PDF 566KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_3.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2014 | 介護保険事業特別会計 | 補正第1号 | [平成26年度補正予算（PDF 566KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_3.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2014 | 国民健康保険事業特別会計 | 補正第1号 | [平成26年度補正予算（PDF 566KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_3.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2015 | 一般会計 | 補正第1号 | [平成27年度補正予算（PDF 516KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_2.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2015 | 一般会計 | 補正第2号 | [平成27年度補正予算（PDF 516KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_2.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2015 | 一般会計 | 補正第3号 | [平成27年度補正予算（PDF 516KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_2.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2015 | 一般会計 | 補正第4号 | [平成27年度補正予算（PDF 516KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_2.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2015 | 一般会計 | 補正第5号 | [平成27年度補正予算（PDF 516KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_2.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2015 | 下水道事業特別会計 | 補正第1号 | [平成27年度補正予算（PDF 516KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_2.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2015 | 下水道事業特別会計 | 補正第2号 | [平成27年度補正予算（PDF 516KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_2.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2015 | 介護保険事業特別会計 | 補正第1号 | [平成27年度補正予算（PDF 516KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_2.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2015 | 介護保険事業特別会計 | 補正第2号 | [平成27年度補正予算（PDF 516KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_2.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2015 | 国民健康保険事業特別会計 | 補正第1号 | [平成27年度補正予算（PDF 516KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_2.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2015 | 国民健康保険事業特別会計 | 補正第2号 | [平成27年度補正予算（PDF 516KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_2.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2016 | 一般会計 | 補正第1号 | [平成28年度補正予算（PDF 616KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_1.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2016 | 一般会計 | 補正第2号 | [平成28年度補正予算（PDF 616KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_1.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2016 | 一般会計 | 補正第3号 | [平成28年度補正予算（PDF 616KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_1.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2016 | 一般会計 | 補正第4号 | [平成28年度補正予算（PDF 616KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_1.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2016 | 一般会計 | 補正第5号 | [平成28年度補正予算（PDF 616KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_1.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2016 | 下水道事業特別会計 | 補正第1号 | [平成28年度補正予算（PDF 616KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_1.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2016 | 介護保険事業特別会計 | 補正第1号 | [平成28年度補正予算（PDF 616KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_1.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2016 | 国民健康保険事業特別会計 | 補正第1号 | [平成28年度補正予算（PDF 616KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_1.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2016 | 後期高齢者医療特別会計 | 補正第1号 | [平成28年度補正予算（PDF 616KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_1.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2017 | 一般会計 | 補正第1号 | [平成29年度補正予算（PDF 514KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2017 | 一般会計 | 補正第2号 | [平成29年度補正予算（PDF 514KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2017 | 一般会計 | 補正第3号 | [平成29年度補正予算（PDF 514KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2017 | 一般会計 | 補正第4号 | [平成29年度補正予算（PDF 514KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2017 | 一般会計 | 補正第5号 | [平成29年度補正予算（PDF 514KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2017 | 下水道事業特別会計 | 補正第1号 | [平成29年度補正予算（PDF 514KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2017 | 介護保険事業特別会計 | 補正第1号 | [平成29年度補正予算（PDF 514KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2017 | 国民健康保険事業特別会計 | 補正第1号 | [平成29年度補正予算（PDF 514KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2018 | 一般会計 | 補正第1号 | [平成30年度補正予算（PDF 375KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_11.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2018 | 一般会計 | 補正第2号 | [平成30年度補正予算（PDF 375KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_11.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2018 | 一般会計 | 補正第3号 | [平成30年度補正予算（PDF 375KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_11.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2018 | 介護保険事業特別会計 | 補正第1号 | [平成30年度補正予算（PDF 375KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_11.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2018 | 介護保険事業特別会計 | 補正第2号 | [平成30年度補正予算（PDF 375KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_11.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2018 | 国民健康保険事業特別会計 | 補正第1号 | [平成30年度補正予算（PDF 375KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_11.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2018 | 国民健康保険事業特別会計 | 補正第2号 | [平成30年度補正予算（PDF 375KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_11.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2018 | 後期高齢者医療特別会計 | 補正第1号 | [平成30年度補正予算（PDF 375KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_11.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2019 | 一般会計 | 補正第1号 | [令和元年度三鷹市一般会計補正予算（第1号）及び同説明書（PDF 545KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_9.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2019 | 一般会計 | 補正第2号 | [令和元年度三鷹市一般会計補正予算（第2号）及び同説明書（PDF 275KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_8.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2019 | 一般会計 | 補正第3号 | [令和元年度三鷹市一般会計補正予算（第3号）及び同説明書（PDF 436KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_5.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2019 | 一般会計 | 補正第4号 | [令和元年度三鷹市一般会計補正予算（第4号及び第5号）及び同説明書（PDF 571KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_2.pdf) | 未確認 |
| 三鷹市 | 2019 | 一般会計 | 補正第5号 | [令和元年度三鷹市一般会計補正予算（第4号及び第5号）及び同説明書（PDF 571KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_2.pdf) | 未確認 |
| 三鷹市 | 2019 | 下水道事業特別会計 | 補正第1号 | [令和元年度三鷹市特別会計補正予算（第1号及び第2号）及び同説明書（PDF 461KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_3.pdf) | 未確認 |
| 三鷹市 | 2019 | 介護保険事業特別会計 | 補正第1号 | [令和元年度三鷹市特別会計補正予算（第1号）及び同説明書（PDF 474KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_6.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2019 | 国民健康保険事業特別会計 | 補正第1号 | [令和元年度三鷹市特別会計補正予算（第1号）及び同説明書（PDF 474KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_6.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2019 | 後期高齢者医療特別会計 | 補正第1号 | [令和元年度三鷹市特別会計補正予算（第1号）及び同説明書（PDF 474KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_6.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2019 | 後期高齢者医療特別会計 | 補正第2号 | [令和元年度三鷹市特別会計補正予算（第1号及び第2号）及び同説明書（PDF 461KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_3.pdf) | 未確認 |
| 三鷹市 | 2020 | 一般会計 | 補正第1号 | [令和2年度三鷹市一般会計補正予算（第1号）及び同説明書（PDF 286KB）](https://www.city.mitaka.lg.jp/c_service/087/attached/attach_87484_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2020 | 一般会計 | 補正第10号 | [令和2年度三鷹市一般会計補正予算（第10号）及び同説明書（PDF 213KB）](https://www.city.mitaka.lg.jp/c_service/091/attached/attach_91760_12.pdf) | 未確認 |
| 三鷹市 | 2020 | 一般会計 | 補正第11号 | [令和2年度三鷹市一般会計補正予算（第11号）及び同説明書（PDF 278KB）](https://www.city.mitaka.lg.jp/c_service/091/attached/attach_91760_10.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2020 | 一般会計 | 補正第12号 | [令和2年度三鷹市一般会計補正予算（第12号）及び同説明書（PDF 550KB）](https://www.city.mitaka.lg.jp/c_service/091/attached/attach_91760_7.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2020 | 一般会計 | 補正第13号 | [令和2年度三鷹市一般会計補正予算（第13号）及び同説明書（PDF 249KB）](https://www.city.mitaka.lg.jp/c_service/091/attached/attach_91760_5.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2020 | 一般会計 | 補正第2号 | [令和2年度三鷹市一般会計補正予算（第2号）及び同説明書（PDF 279KB）](https://www.city.mitaka.lg.jp/c_service/087/attached/attach_87484_10.pdf) | 未確認 |
| 三鷹市 | 2020 | 一般会計 | 補正第3号 | [令和2年度三鷹市一般会計補正予算（第3号）及び同説明書（PDF 498KB）](https://www.city.mitaka.lg.jp/c_service/087/attached/attach_87484_6.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2020 | 一般会計 | 補正第4号 | [令和2年度6月補正予算（第4号）（PDF 48KB）](https://www.city.mitaka.lg.jp/c_service/087/attached/attach_87484_3.pdf) | 未確認 |
| 三鷹市 | 2020 | 一般会計 | 補正第5号 | [令和2年度三鷹市一般会計補正予算（第5号）及び同説明書（PDF 277KB）](https://www.city.mitaka.lg.jp/c_service/087/attached/attach_87484_2.pdf) | 未確認 |
| 三鷹市 | 2020 | 一般会計 | 補正第6号 | [令和2年度三鷹市一般会計補正予算（第6号）及び同説明書（PDF 351KB）](https://www.city.mitaka.lg.jp/c_service/089/attached/attach_89550_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2020 | 一般会計 | 補正第7号 | [令和2年度9月補正予算（第7号）（PDF 246KB）](https://www.city.mitaka.lg.jp/c_service/089/attached/attach_89550_9.pdf) | 未確認 |
| 三鷹市 | 2020 | 一般会計 | 補正第8号 | [令和2年度9月補正予算（第8号）（PDF 75KB）](https://www.city.mitaka.lg.jp/c_service/089/attached/attach_89550_7.pdf) | 未確認 |
| 三鷹市 | 2020 | 一般会計 | 補正第9号 | [令和2年度三鷹市一般会計補正予算（第9号）及び同説明書（PDF 454KB）](https://www.city.mitaka.lg.jp/c_service/089/attached/attach_89550_3.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2020 | 介護保険事業特別会計 | 補正第2号 | [令和2年度三鷹市介護保険事業特別会計補正予算（第2号）及び同説明書（PDF 235KB）](https://www.city.mitaka.lg.jp/c_service/089/attached/attach_89550_5.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2020 | 国民健康保険事業特別会計 | 補正第1号 | [令和2年度三鷹市国民健康保険事業特別会計補正予算（第1号）及び同説明書（PDF 233KB）](https://www.city.mitaka.lg.jp/c_service/087/attached/attach_87484_7.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2020 | 国民健康保険事業特別会計 | 補正第2号 | [令和2年度三鷹市国民健康保険事業特別会計補正予算（第2号）及び同説明書（PDF 219KB）](https://www.city.mitaka.lg.jp/c_service/089/attached/attach_89550_4.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2021 | 一般会計 | 補正第1号 | [令和3年度6月補正予算（第2号）（PDF 141KB）](https://www.city.mitaka.lg.jp/c_service/093/attached/attach_93558_11.pdf) | 未確認 |
| 三鷹市 | 2021 | 一般会計 | 補正第10号 | [令和3年度12月補正予算（第10号）（PDF 275KB）](https://www.city.mitaka.lg.jp/c_service/094/attached/attach_94775_3.pdf) | 未確認 |
| 三鷹市 | 2021 | 一般会計 | 補正第11号 | [令和3年度12月補正予算（第11号）（PDF 225KB）](https://www.city.mitaka.lg.jp/c_service/094/attached/attach_94775_1.pdf) | 未確認 |
| 三鷹市 | 2021 | 一般会計 | 補正第12号 | [令和3年度三鷹市一般会計補正予算（第12号）及び同説明書（PDF 318KB）](https://www.city.mitaka.lg.jp/c_service/097/attached/attach_97160_11.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2021 | 一般会計 | 補正第13号 | [令和3年度三鷹市一般会計補正予算（第13号）及び同説明書（PDF 246KB）](https://www.city.mitaka.lg.jp/c_service/097/attached/attach_97160_9.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2021 | 一般会計 | 補正第14号 | [令和3年度三鷹市一般会計補正予算（第14号）及び同説明書（PDF 517KB）](https://www.city.mitaka.lg.jp/c_service/097/attached/attach_97160_6.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2021 | 一般会計 | 補正第15号 | [令和3年度三鷹市一般会計補正予算（第15号）及び同説明書（PDF 246KB）](https://www.city.mitaka.lg.jp/c_service/097/attached/attach_97160_4.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2021 | 一般会計 | 補正第2号 | [令和3年度三鷹市一般会計補正予算（第3号）及び同説明書（PDF 339KB）](https://www.city.mitaka.lg.jp/c_service/093/attached/attach_93558_10.pdf) | 未確認 |
| 三鷹市 | 2021 | 一般会計 | 補正第3号 | [令和3年度三鷹市一般会計補正予算（第3号）及び同説明書（PDF 339KB）](https://www.city.mitaka.lg.jp/c_service/093/attached/attach_93558_10.pdf) | 未確認 |
| 三鷹市 | 2021 | 一般会計 | 補正第4号 | [令和3年度三鷹市一般会計補正予算（第4号）及び同説明書（PDF 283KB）](https://www.city.mitaka.lg.jp/c_service/093/attached/attach_93558_8.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2021 | 一般会計 | 補正第5号 | [令和3年度三鷹市一般会計補正予算（第5号）及び同説明書（PDF 286KB）](https://www.city.mitaka.lg.jp/c_service/093/attached/attach_93558_6.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2021 | 一般会計 | 補正第6号 | [令和3年度三鷹市一般会計補正予算（第6号）及び同説明書（PDF 220KB）](https://www.city.mitaka.lg.jp/c_service/093/attached/attach_93558_4.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2021 | 一般会計 | 補正第7号 | [令和3年度三鷹市一般会計補正予算（第7号）及び同説明書（PDF 365KB）](https://www.city.mitaka.lg.jp/c_service/093/attached/attach_93558_2.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2021 | 一般会計 | 補正第8号 | [令和3年度三鷹市一般会計補正予算（第8号）及び同説明書（PDF 307KB）](https://www.city.mitaka.lg.jp/c_service/094/attached/attach_94775_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2021 | 一般会計 | 補正第9号 | [令和3年度三鷹市一般会計補正予算（第9号）及び同説明書（PDF 323KB）](https://www.city.mitaka.lg.jp/c_service/094/attached/attach_94775_10.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2021 | 介護保険事業特別会計 | 補正第1号 | [令和3年度三鷹市介護保険事業特別会計補正予算（第1号）及び同説明書（PDF 225KB）](https://www.city.mitaka.lg.jp/c_service/094/attached/attach_94775_6.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2021 | 国民健康保険事業特別会計 | 補正第1号 | [令和3年度三鷹市国民健康保険事業特別会計補正予算（第1号）及び同説明書（PDF 215KB）](https://www.city.mitaka.lg.jp/c_service/094/attached/attach_94775_5.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2021 | 国民健康保険事業特別会計 | 補正第2号 | [令和3年度三鷹市国民健康保険事業特別会計補正予算（第2号）及び同説明書（PDF 216KB）](https://www.city.mitaka.lg.jp/c_service/097/attached/attach_97160_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2021 | 後期高齢者医療特別会計 | 補正第1号 | [令和3年度三鷹市後期高齢者医療特別会計補正予算（第1号）及び同説明書（PDF 265KB）](https://www.city.mitaka.lg.jp/c_service/094/attached/attach_94775_7.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2022 | 一般会計 | 補正第1号 | [令和4年度三鷹市一般会計補正予算（第1号）及び同説明書（PDF 531KB）](https://www.city.mitaka.lg.jp/c_service/099/attached/attach_99677_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2022 | 一般会計 | 補正第2号 | [令和4年度三鷹市一般会計補正予算（第2号）及び同説明書（PDF 650KB）](https://www.city.mitaka.lg.jp/c_service/099/attached/attach_99677_10.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2022 | 一般会計 | 補正第3号 | [令和4年度三鷹市一般会計補正予算（第3号）及び同説明書（PDF 427KB）](https://www.city.mitaka.lg.jp/c_service/099/attached/attach_99677_8.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2022 | 一般会計 | 補正第4号 | [令和4年度三鷹市一般会計補正予算（第4号）及び同説明書（PDF 638KB）](https://www.city.mitaka.lg.jp/c_service/099/attached/attach_99677_5.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2022 | 一般会計 | 補正第5号 | [令和4年度三鷹市一般会計補正予算（第5号）及び同説明書（PDF 511KB）](https://www.city.mitaka.lg.jp/c_service/099/attached/attach_99677_3.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2022 | 一般会計 | 補正第6号 | [令和4年度三鷹市一般会計補正予算（第6号）及び同説明書（PDF 439KB）](https://www.city.mitaka.lg.jp/c_service/102/attached/attach_102129_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2022 | 一般会計 | 補正第7号 | [令和4年度三鷹市一般会計補正予算（第7号）及び同説明書（PDF 614KB）](https://www.city.mitaka.lg.jp/c_service/102/attached/attach_102129_7.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2022 | 一般会計 | 補正第8号 | [令和4年度三鷹市一般会計補正予算（第8号）及び同説明書（PDF 482KB）](https://www.city.mitaka.lg.jp/c_service/102/attached/attach_102129_5.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2022 | 一般会計 | 補正第9号 | [令和4年度三鷹市一般会計補正予算（第9号）及び同説明書（PDF 545KB）](https://www.city.mitaka.lg.jp/c_service/104/attached/attach_104580_11.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2022 | 介護保険事業特別会計 | 補正第1号 | [令和4年度三鷹市介護保険事業特別会計補正予算（第1号）及び同説明書（PDF 447KB）](https://www.city.mitaka.lg.jp/c_service/099/attached/attach_99677_6.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2022 | 介護保険事業特別会計 | 補正第2号 | [令和4年度三鷹市介護保険事業特別会計補正予算（第2号）及び同説明書（PDF 421KB）](https://www.city.mitaka.lg.jp/c_service/102/attached/attach_102129_9.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2022 | 国民健康保険事業特別会計 | 補正第1号 | [令和4年度三鷹市国民健康保険事業特別会計補正予算（第1号）及び同説明書（PDF 406KB）](https://www.city.mitaka.lg.jp/c_service/102/attached/attach_102129_8.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2022 | 後期高齢者医療特別会計 | 補正第1号 | [令和4年度三鷹市後期高齢者医療特別会計補正予算（第1号）及び同説明書（PDF 407KB）](https://www.city.mitaka.lg.jp/c_service/104/attached/attach_104580_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2023 | 一般会計 | 補正第1号 | [令和5年度三鷹市一般会計補正予算（第1号）及び同説明書（PDF 557KB）](https://www.city.mitaka.lg.jp/c_service/104/attached/attach_104580_9.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2023 | 一般会計 | 補正第2号 | [令和5年度三鷹市一般会計補正予算（第2号）及び同説明書（PDF 467KB）](https://www.city.mitaka.lg.jp/c_service/104/attached/attach_104585_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2023 | 一般会計 | 補正第3号 | [令和5年度三鷹市一般会計補正予算（第3号）及び同説明書（PDF 459KB）](https://www.city.mitaka.lg.jp/c_service/104/attached/attach_104585_10.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2023 | 一般会計 | 補正第4号 | [令和5年度三鷹市一般会計補正予算（第4号）及び同説明書（PDF 578KB）](https://www.city.mitaka.lg.jp/c_service/104/attached/attach_104585_8.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2023 | 一般会計 | 補正第5号 | [令和5年度三鷹市一般会計補正予算（第5号）及び同説明書（PDF 605KB）](https://www.city.mitaka.lg.jp/c_service/104/attached/attach_104585_6.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2023 | 一般会計 | 補正第6号 | [令和5年度三鷹市一般会計補正予算（第6号）及び同説明書（PDF 488KB）](https://www.city.mitaka.lg.jp/c_service/109/attached/attach_109136_10.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2023 | 一般会計 | 補正第7号 | [令和5年度三鷹市一般会計補正予算（第7号）及び同説明書（PDF 303KB）](https://www.city.mitaka.lg.jp/c_service/109/attached/attach_109136_8.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2023 | 一般会計 | 補正第8号 | [令和5年度三鷹市一般会計補正予算（第8号）及び同説明書（PDF 316KB）](https://www.city.mitaka.lg.jp/c_service/109/attached/attach_109136_6.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2023 | 一般会計 | 補正第9号 | [令和5年度三鷹市一般会計補正予算（第9号）及び同説明書（PDF 277KB）](https://www.city.mitaka.lg.jp/c_service/109/attached/attach_109136_2.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2023 | 介護保険事業特別会計 | 補正第1号 | [令和5年度三鷹市介護保険事業特別会計補正予算（第1号）及び同説明書（PDF 197KB）](https://www.city.mitaka.lg.jp/c_service/109/attached/attach_109136_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2023 | 国民健康保険事業特別会計 | 補正第1号 | [令和5年度三鷹市国民健康保険事業特別会計補正予算（第1号）及び同説明書（PDF 187KB）](https://www.city.mitaka.lg.jp/c_service/109/attached/attach_109136_11.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2024 | 一般会計 | 補正第1号 | [令和6年度三鷹市一般会計補正予算（第1号）及び同説明書（PDF 482KB）](https://www.city.mitaka.lg.jp/c_service/111/attached/attach_111879_8.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2024 | 一般会計 | 補正第2号 | [令和6年度三鷹市一般会計補正予算（第2号）及び同説明書（PDF 534KB）](https://www.city.mitaka.lg.jp/c_service/111/attached/attach_111879_6.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2024 | 一般会計 | 補正第3号 | [令和6年度三鷹市一般会計補正予算（第3号）及び同説明書（PDF 409KB）](https://www.city.mitaka.lg.jp/c_service/111/attached/attach_111879_4.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2024 | 一般会計 | 補正第4号 | [令和6年度三鷹市一般会計補正予算（第4号）及び同説明書（PDF 504KB）](https://www.city.mitaka.lg.jp/c_service/111/attached/attach_111879_2.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2024 | 一般会計 | 補正第5号 | [令和6年度三鷹市一般会計補正予算（第5号）及び同説明書（PDF 704KB）](https://www.city.mitaka.lg.jp/c_service/114/attached/attach_114217_7.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2024 | 一般会計 | 補正第6号 | [令和6年度三鷹市一般会計補正予算（第6号）及び同説明書（PDF 432KB）](https://www.city.mitaka.lg.jp/c_service/114/attached/attach_114217_5.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2024 | 一般会計 | 補正第7号 | [令和6年度三鷹市一般会計補正予算（第7号）及び同説明書（PDF 621KB）](https://www.city.mitaka.lg.jp/c_service/114/attached/attach_114217_2.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2024 | 介護保険事業特別会計 | 補正第1号 | [令和6年度三鷹市介護保険事業特別会計補正予算（第1号）及び同説明書（PDF 361KB）](https://www.city.mitaka.lg.jp/c_service/114/attached/attach_114217_9.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2024 | 国民健康保険事業特別会計 | 補正第1号 | [令和6年度三鷹市国民健康保険事業特別会計補正予算（第1号）及び同説明書（PDF 335KB）](https://www.city.mitaka.lg.jp/c_service/114/attached/attach_114217_8.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2024 | 後期高齢者医療特別会計 | 補正第1号 | [令和6年度三鷹市後期高齢者医療特別会計補正予算（第1号）及び同説明書（PDF 387KB）](https://www.city.mitaka.lg.jp/c_service/114/attached/attach_114217_3.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2025 | 一般会計 | 補正第1号 | [令和7年度三鷹市一般会計補正予算（第1号）及び同説明書（PDF 584KB）](https://www.city.mitaka.lg.jp/c_service/118/attached/attach_118206_12.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2025 | 一般会計 | 補正第2号 | [令和7年度三鷹市一般会計補正予算（第2号）及び同説明書（PDF 511KB）](https://www.city.mitaka.lg.jp/c_service/118/attached/attach_118206_10.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2025 | 一般会計 | 補正第3号 | [令和7年度三鷹市一般会計補正予算（第3号）及び同説明書（PDF 698KB）](https://www.city.mitaka.lg.jp/c_service/118/attached/attach_118206_6.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2025 | 一般会計 | 補正第4号 | [令和7年度三鷹市一般会計補正予算（第4号）及び同説明書（PDF 615KB）](https://www.city.mitaka.lg.jp/c_service/118/attached/attach_118206_4.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2025 | 一般会計 | 補正第5号 | [令和7年度三鷹市一般会計補正予算（第5号）及び同説明書（PDF 490KB）](https://www.city.mitaka.lg.jp/c_service/118/attached/attach_118206_2.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2025 | 一般会計 | 補正第6号 | [令和7年度三鷹市一般会計補正予算（第6号）及び同説明書（PDF 498KB）](https://www.city.mitaka.lg.jp/c_service/119/attached/attach_119565_2.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2025 | 介護保険事業特別会計 | 補正第1号 | [令和7年度三鷹市介護保険事業特別会計補正予算（第1号）及び同説明書（PDF 361KB）](https://www.city.mitaka.lg.jp/c_service/118/attached/attach_118206_8.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2025 | 国民健康保険事業特別会計 | 補正第1号 | [令和7年度三鷹市国民健康保険事業特別会計補正予算（第1号）及び同説明書（PDF 335KB）](https://www.city.mitaka.lg.jp/c_service/118/attached/attach_118206_7.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2025 | 後期高齢者医療特別会計 | 補正第1号 | [令和7年度三鷹市後期高齢者医療特別会計補正予算（第1号）及び同説明書（PDF 436KB）](https://www.city.mitaka.lg.jp/c_service/119/attached/attach_119565_3.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2026 | 一般会計 | 補正第1号 | [令和8年度三鷹市一般会計補正予算（第1号）及び同説明書（PDF 447KB）](https://www.city.mitaka.lg.jp/c_service/003/attached/attach_3871_2.pdf) | 候補1件（最新版の網羅確認なし） |
| 三鷹市 | 2026 | 一般会計 | 補正第2号 | [令和8年度三鷹市一般会計補正予算（第2号）及び同説明書（PDF 860KB）](https://www.city.mitaka.lg.jp/c_service/003/attached/attach_3871_4.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2020 | 一般会計 | 決算 | [令和2年度決算書（一般会計歳出事項別明細書） （PDF 779.7 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/261/r02kessannsyosaisyutu.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2020 | 介護保険特別会計 | 決算 | [令和2年度決算書（介護保険特別会計） （PDF 328.9 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/261/r02kessannsyokaigo.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2020 | 国民健康保険特別会計 | 決算 | [令和2年度決算書（国民健康保険特別会計） （PDF 329.2 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/261/r02kessannsyokokuho.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2020 | 後期高齢者医療特別会計 | 決算 | [令和2年度決算書（後期高齢者医療特別会計） （PDF 272.2 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/261/r02kessannsyokouki.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2021 | 一般会計 | 決算 | [令和3年度決算書（一般会計歳出事項別明細書） （PDF 785.3 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/260/r3kessan3.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2021 | 介護保険特別会計 | 決算 | [令和3年度決算書（介護保険特別会計） （PDF 327.7 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/260/r3kessan5.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2021 | 国民健康保険特別会計 | 決算 | [令和3年度決算書（国民健康保険特別会計） （PDF 336.4 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/260/r3kessan4.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2021 | 後期高齢者医療特別会計 | 決算 | [令和3年度決算書（後期高齢者医療特別会計） （PDF 266.2 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/260/r3kessan6.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2022 | 一般会計 | 決算 | [令和4年度決算書（一般会計歳出事項別明細書） （PDF 771.9 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/259/r4kessan3.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2022 | 介護保険特別会計 | 決算 | [令和4年度決算書（介護保険特別会計） （PDF 327.9 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/259/r4kessan5.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2022 | 国民健康保険特別会計 | 決算 | [令和4年度決算書（国民健康保険特別会計） （PDF 335.4 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/259/r4kessan4.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2022 | 後期高齢者医療特別会計 | 決算 | [令和4年度決算書（後期高齢者医療特別会計） （PDF 264.6 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/259/r4kessan6.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2023 | 一般会計 | 決算 | [令和5年度決算書（一般会計歳出事項別明細書） （PDF 718.1 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/258/r5kessan3.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2023 | 中神土地区画整理事業特別会計 | 決算 | [令和5年度決算書（中神土地区画整理事業特別会計） （PDF 252.6 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/258/r5kessan7.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2023 | 介護保険特別会計 | 決算 | [令和5年度決算書（介護保険特別会計） （PDF 312.3 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/258/r5kessan5.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2023 | 国民健康保険特別会計 | 決算 | [令和5年度決算書（国民健康保険特別会計） （PDF 318.9 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/258/r5kessan4.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2023 | 後期高齢者医療特別会計 | 決算 | [令和5年度決算書（後期高齢者医療特別会計） （PDF 254.0 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/258/r5kessan6.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2024 | 一般会計 | 決算 | [令和6年度決算書（一般会計）（PDF:1,577KB） （PDF 1.6 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/009/130/r6kessan2.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2024 | 中神土地区画整理事業特別会計 | 決算 | [令和6年度決算書（中神土地区画整理事業特別会計） （PDF 316.7 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/009/130/r6kessan6.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2024 | 介護保険特別会計 | 決算 | [令和6年度決算書（介護保険特別会計） （PDF 395.1 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/009/130/r6kessan4.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2024 | 国民健康保険特別会計 | 決算 | [令和6年度決算書（国民健康保険特別会計） （PDF 348.4 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/009/130/r6kessan3.pdf) | 候補1件（最新版の網羅確認なし） |
| 昭島市 | 2024 | 後期高齢者医療特別会計 | 決算 | [令和6年度決算書（後期高齢者医療特別会計）（PDF314KB） （PDF 329.2 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/009/130/r6kessan5.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2020 | 一般会計 | 補正第2号 | [令和２年度補正予算案について.pdf [1076KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,107429,c,html/107429/20200615-174305.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2020 | 一般会計 | 補正第4号 | [令和２年度補正予算案について.pdf [534KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,109056,c,html/109056/20200828-163735.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2020 | 一般会計 | 補正第5号 | [令和２年度補正予算案について.pdf [1289KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,109569,c,html/109569/20200923-190144.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2020 | 一般会計 | 補正第6号 | [令和２年度補正予算案について.pdf [ 782 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,111268,c,html/111268/20201029-144745.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2020 | 一般会計 | 補正第7号 | [令和２年度補正予算案について.pdf [ 1964 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,113391,c,html/113391/20210122-182017.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2020 | 一般会計 | 補正第8号 | [令和２年度補正予算案について.pdf [ 235 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,113397,c,html/113397/20210129-181115.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2020 | 下水道事業会計 | 補正第1号 | [令和２年度補正予算案について.pdf [ 4095 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,113863,c,html/113863/20210218-134132.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2020 | 介護保険特別会計 | 補正第1号 | [令和２年度補正予算案について.pdf [1289KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,109569,c,html/109569/20200923-190144.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2020 | 介護保険特別会計 | 補正第2号 | [令和２年度補正予算案について.pdf [ 1964 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,113391,c,html/113391/20210122-182017.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2020 | 国民健康保険特別会計 | 補正第1号 | [令和２年度補正予算案について.pdf [1076KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,107429,c,html/107429/20200615-174305.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2020 | 国民健康保険特別会計 | 補正第2号 | [令和２年度補正予算案について.pdf [1289KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,109569,c,html/109569/20200923-190144.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2020 | 国民健康保険特別会計 | 補正第3号 | [令和２年度補正予算案について.pdf [ 1964 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,113391,c,html/113391/20210122-182017.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2020 | 国民健康保険特別会計 | 補正第4号 | [令和２年度補正予算案について.pdf [ 4095 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,113863,c,html/113863/20210218-134132.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2020 | 後期高齢者医療特別会計 | 補正第1号 | [令和２年度補正予算案について.pdf [1289KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,109569,c,html/109569/20200923-190144.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2020 | 後期高齢者医療特別会計 | 補正第2号 | [令和２年度補正予算案について.pdf [ 1964 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,113391,c,html/113391/20210122-182017.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2021 | 一般会計 | 補正第1号 | [令和３年度補正予算案について.pdf [ 824 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,114241,c,html/114241/20210310-092334.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2021 | 一般会計 | 補正第3号 | [令和３年度補正予算案について](https://www.city.komae.tokyo.jp/index.cfm/50,115775,c,html/115775/20210512-092954.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2021 | 一般会計 | 補正第5号 | [令和３年度補正予算案について.pdf [ 440 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,116673,c,html/116673/20210701-184106.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2021 | 下水道事業会計 | 補正第1号 | [令和３年度補正予算案について [4959KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,119886,c,html/119886/20211209-105120.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2024 | 後期高齢者医療特別会計 | 補正第2号 | [令和７年狛江市議会第1回定例会提出議案 [ 2624 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,136986,c,html/136986/20250217-094837.pdf) | 候補1件（最新版の網羅確認なし） |
| 狛江市 | 2024 | 駐車場事業特別会計 | 補正第1号 | [令和6年 狛江市議会第3回定例会提出議案 [ 3166 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132125,c,html/132125/20240830-145313.pdf) | 未確認 |
| 狛江市 | 2025 | 介護保険特別会計 | 補正第3号 | [令和８年狛江市議会第１回定例会提出議案 [ 4542 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,142099,c,html/142099/20260218-153404.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2022 | 一般会計 | 補正第12号 | [第20号議案（令和4年度一般会計補正予算第12号） （PDF 447.5 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/010/509/0501teirei_sicyo20.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2022 | 一般会計 | 補正第13号 | [第21号議案（令和4年度一般会計補正予算第13号） （PDF 2.1 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/010/509/0501teirei_sicyo21.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2022 | 一般会計 | 補正第14号 | [第23号議案（令和4年度一般会計補正予算第14号） （PDF 530.4 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/010/509/0501teirei_sicyo23.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2022 | 介護保険特別会計 | 補正第4号 | [第1号議案から第4号議案まで（令和4年度特別会計・下水道事業会計補正予算） （PDF 1.8 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/010/509/0501teirei_sicyo1-4.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2022 | 国民健康保険特別会計 | 補正第3号 | [第1号議案から第4号議案まで（令和4年度特別会計・下水道事業会計補正予算） （PDF 1.8 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/010/509/0501teirei_sicyo1-4.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2022 | 後期高齢者医療特別会計 | 補正第4号 | [第1号議案から第4号議案まで（令和4年度特別会計・下水道事業会計補正予算） （PDF 1.8 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/010/509/0501teirei_sicyo1-4.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 一般会計 | 補正第1号 | [第24号議案（令和5年度一般会計補正予算第1号） （PDF 404.5 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/010/509/0501teirei_sicyo24.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 一般会計 | 補正第10号 | [第3号議案から第7号議案まで（令和5年度一般会計補正予算第10号・各特別会計補正予算・下水道事業会計補正予算） （PDF 1.9 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/014/321/0601teirei_sicyo3-7.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 一般会計 | 補正第11号 | [第39号議案（令和5年度一般会計補正予算第11号） （PDF 111.1 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/014/321/sicyo_39.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 一般会計 | 補正第3号 | [第29号議案（令和5年度一般会計補正予算） （PDF 131.7 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/012/065/0502teirei_sicho29.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 一般会計 | 補正第4号 | [第30号議案から第34号議案まで（令和5年度一般会計・特別会計・下水道事業会計補正予算） （PDF 2.9 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/012/065/0502teirei_sicho30-34.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 一般会計 | 補正第5号 | [第71号議案から第74号議案まで（令和5年度一般会計・各特別会計補正予算） （PDF 547.4 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/012/871/0503teirei_sicho71-74.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 一般会計 | 補正第6号 | [第85号議案（令和5年度一般会計補正予算） （PDF 281.9 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/012/871/0503teirei_sicho85.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 一般会計 | 補正第7号 | [第86号議案から第87号議案まで（令和5年度一般会計・介護保険特別会計補正予算） （PDF 741.3 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/013/663/0504teirei_sicho_86-87.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 一般会計 | 補正第8号 | [第106号議案から第110号議案まで（令和5年度一般会計補正予算・各特別会計補正予算） （PDF 1.3 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/013/663/0504teirei_sicyo106-110.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 一般会計 | 補正第9号 | [第2号議案（令和5年度一般会計予算第9号） （PDF 576.6 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/014/321/0601teirei_sicyo2.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 介護保険特別会計 | 補正第1号 | [第30号議案から第34号議案まで（令和5年度一般会計・特別会計・下水道事業会計補正予算） （PDF 2.9 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/012/065/0502teirei_sicho30-34.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 介護保険特別会計 | 補正第2号 | [第71号議案から第74号議案まで（令和5年度一般会計・各特別会計補正予算） （PDF 547.4 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/012/871/0503teirei_sicho71-74.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 介護保険特別会計 | 補正第3号 | [第86号議案から第87号議案まで（令和5年度一般会計・介護保険特別会計補正予算） （PDF 741.3 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/013/663/0504teirei_sicho_86-87.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 介護保険特別会計 | 補正第4号 | [第106号議案から第110号議案まで（令和5年度一般会計補正予算・各特別会計補正予算） （PDF 1.3 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/013/663/0504teirei_sicyo106-110.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 介護保険特別会計 | 補正第5号 | [第3号議案から第7号議案まで（令和5年度一般会計補正予算第10号・各特別会計補正予算・下水道事業会計補正予算） （PDF 1.9 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/014/321/0601teirei_sicyo3-7.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 国民健康保険特別会計 | 補正第1号 | [第30号議案から第34号議案まで（令和5年度一般会計・特別会計・下水道事業会計補正予算） （PDF 2.9 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/012/065/0502teirei_sicho30-34.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 国民健康保険特別会計 | 補正第2号 | [第71号議案から第74号議案まで（令和5年度一般会計・各特別会計補正予算） （PDF 547.4 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/012/871/0503teirei_sicho71-74.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 国民健康保険特別会計 | 補正第3号 | [第106号議案から第110号議案まで（令和5年度一般会計補正予算・各特別会計補正予算） （PDF 1.3 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/013/663/0504teirei_sicyo106-110.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 国民健康保険特別会計 | 補正第4号 | [第3号議案から第7号議案まで（令和5年度一般会計補正予算第10号・各特別会計補正予算・下水道事業会計補正予算） （PDF 1.9 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/014/321/0601teirei_sicyo3-7.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 後期高齢者医療特別会計 | 補正第1号 | [第30号議案から第34号議案まで（令和5年度一般会計・特別会計・下水道事業会計補正予算） （PDF 2.9 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/012/065/0502teirei_sicho30-34.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 後期高齢者医療特別会計 | 補正第2号 | [第71号議案から第74号議案まで（令和5年度一般会計・各特別会計補正予算） （PDF 547.4 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/012/871/0503teirei_sicho71-74.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 後期高齢者医療特別会計 | 補正第3号 | [第106号議案から第110号議案まで（令和5年度一般会計補正予算・各特別会計補正予算） （PDF 1.3 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/013/663/0504teirei_sicyo106-110.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2023 | 後期高齢者医療特別会計 | 補正第4号 | [第3号議案から第7号議案まで（令和5年度一般会計補正予算第10号・各特別会計補正予算・下水道事業会計補正予算） （PDF 1.9 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/014/321/0601teirei_sicyo3-7.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 一般会計 | 補正第1号 | [第40号議案から第41号議案まで（令和6年度一般会計補正予算第1号・令和6年度下水道事業会計補正予算第1号） （PDF 272.6 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/014/321/sicyo_40-41.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 一般会計 | 補正第10号 | [第2号議案から第5号議案まで（令和6年度一般会計補正予算第10号・各特別会計補正予算・下水道事業会計補正予算） （PDF 5.7 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/016/909/R7teirei_sicyo02-05.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 一般会計 | 補正第11号 | [第33号議案（令和6年度一般会計補正予算） （PDF 611.3 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/016/909/7teirei_sicyo33.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 一般会計 | 補正第2号 | [第45号議案から第47号議案まで（令和6年度一般会計補正予算・介護保険特別会計補正予算・下水道事業会計補正予算） （PDF 1.2 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/014/950/sicyo_45-47.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 一般会計 | 補正第3号 | [第60号議案（令和6年度一般会計補正予算第3号） （PDF 128.0 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/014/950/sysho_60.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 一般会計 | 補正第4号 | [第63号議案（令和6年度一般会計補正予算第4号） （PDF 246.4 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/014/950/sycho_63.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 一般会計 | 補正第5号 | [第69号議案から第72号議案まで（令和6年度一般会計・3特別会計補正予算） （PDF 1.1 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/015/727/0603teirei_sicyo03.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 一般会計 | 補正第7号 | [第90号議案から第91号議案まで（令和6年度一般会計・介護保険特別会計 補正予算） （PDF 1.3 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/016/361/0604teirei_sicyo90-91.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 一般会計 | 補正第8号 | [第109号議案から第113号議案まで（令和6年度一般会計・3特別会計・下水道事業会計 補正予算） （PDF 3.1 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/016/361/sycho_109-113.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 一般会計 | 補正第9号 | [第1号議案（令和6年度一般会計予算第9号） （PDF 438.4 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/016/909/R7teirei_sicyo01.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 介護保険特別会計 | 補正第1号 | [第45号議案から第47号議案まで（令和6年度一般会計補正予算・介護保険特別会計補正予算・下水道事業会計補正予算） （PDF 1.2 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/014/950/sicyo_45-47.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 介護保険特別会計 | 補正第2号 | [第69号議案から第72号議案まで（令和6年度一般会計・3特別会計補正予算） （PDF 1.1 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/015/727/0603teirei_sicyo03.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 介護保険特別会計 | 補正第3号 | [第90号議案から第91号議案まで（令和6年度一般会計・介護保険特別会計 補正予算） （PDF 1.3 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/016/361/0604teirei_sicyo90-91.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 介護保険特別会計 | 補正第4号 | [第109号議案から第113号議案まで（令和6年度一般会計・3特別会計・下水道事業会計 補正予算） （PDF 3.1 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/016/361/sycho_109-113.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 介護保険特別会計 | 補正第5号 | [第2号議案から第5号議案まで（令和6年度一般会計補正予算第10号・各特別会計補正予算・下水道事業会計補正予算） （PDF 5.7 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/016/909/R7teirei_sicyo02-05.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 国民健康保険特別会計 | 補正第1号 | [第69号議案から第72号議案まで（令和6年度一般会計・3特別会計補正予算） （PDF 1.1 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/015/727/0603teirei_sicyo03.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 国民健康保険特別会計 | 補正第2号 | [第109号議案から第113号議案まで（令和6年度一般会計・3特別会計・下水道事業会計 補正予算） （PDF 3.1 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/016/361/sycho_109-113.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 国民健康保険特別会計 | 補正第3号 | [第2号議案から第5号議案まで（令和6年度一般会計補正予算第10号・各特別会計補正予算・下水道事業会計補正予算） （PDF 5.7 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/016/909/R7teirei_sicyo02-05.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 後期高齢者医療特別会計 | 補正第1号 | [第69号議案から第72号議案まで（令和6年度一般会計・3特別会計補正予算） （PDF 1.1 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/015/727/0603teirei_sicyo03.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 後期高齢者医療特別会計 | 補正第2号 | [第109号議案から第113号議案まで（令和6年度一般会計・3特別会計・下水道事業会計 補正予算） （PDF 3.1 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/016/361/sycho_109-113.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2024 | 後期高齢者医療特別会計 | 補正第3号 | [第2号議案から第5号議案まで（令和6年度一般会計補正予算第10号・各特別会計補正予算・下水道事業会計補正予算） （PDF 5.7 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/016/909/R7teirei_sicyo02-05.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 一般会計 | 補正第1号 | [第34号議案(令和7年度一般会計補正予算） （PDF 728.8 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/016/909/7teirei_sicyo34.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 一般会計 | 補正第10号 | [第2号議案（令和7年度一般会計補正予算） （PDF 388.6 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/019/488/R8-1rinji_sicyo2.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 一般会計 | 補正第11号 | [第3号議案から第7号議案まで（令和7年度一般会計補正予算第11号・各特別会計補正予算・下水道事業会計補正予算） （PDF 3.2 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/019/604/R8-1teirei_sicyo3-7.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 一般会計 | 補正第12号 | [第36号議案（令和7年度一般会計補正予算第12号） （PDF 471.9 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/019/604/R8-1teirei_sicyo36.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 一般会計 | 補正第13号 | [第38号議案（令和7年度一般会計補正予算第13号） （PDF 477.0 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/019/604/R8-1teirei_sicyo38.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 一般会計 | 補正第2号 | [第39号議案(令和7年度一般会計補正予算第2号） （PDF 848.8 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/017/506/R7-2teirei_sicyo39.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 一般会計 | 補正第3号 | [第58号議案(令和7年度一般会計補正予算第3号） （PDF 299.9 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/017/506/R7-2teirei_sicyo58.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 一般会計 | 補正第4号 | [第64号議案から第68号議案まで（令和7年度一般会計・3特別会計・下水道事業会計補正予算） （PDF 3.1 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/018/381/R7-3teirei_sicyo64-68.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 一般会計 | 補正第5号 | [第78号議案（令和7年度一般会計補正予算第5号） （PDF 380.5 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/018/381/R7-3teirei_sicyo78.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 一般会計 | 補正第6号 | [第79号議案から第82号議案まで（令和7年度一般会計補正予算・3特別会計補正予算） （PDF 1.9 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/018/981/R7-4teirei_sicyo79-82.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 一般会計 | 補正第7号 | [第107号議案から第111号議案まで（令和7年度一般会計補正予算・3特別会計補正予算・下水道事業会計補正予算） （PDF 1.9 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/018/981/R7-4teirei_sicyo107-111.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 一般会計 | 補正第8号 | [第114号議案（令和7年度一般会計補正予算） （PDF 360.8 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/018/981/R7-4teirei_sicyo114.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 介護保険特別会計 | 補正第1号 | [第64号議案から第68号議案まで（令和7年度一般会計・3特別会計・下水道事業会計補正予算） （PDF 3.1 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/018/381/R7-3teirei_sicyo64-68.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 介護保険特別会計 | 補正第2号 | [第79号議案から第82号議案まで（令和7年度一般会計補正予算・3特別会計補正予算） （PDF 1.9 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/018/981/R7-4teirei_sicyo79-82.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 介護保険特別会計 | 補正第3号 | [第107号議案から第111号議案まで（令和7年度一般会計補正予算・3特別会計補正予算・下水道事業会計補正予算） （PDF 1.9 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/018/981/R7-4teirei_sicyo107-111.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 介護保険特別会計 | 補正第4号 | [第3号議案から第7号議案まで（令和7年度一般会計補正予算第11号・各特別会計補正予算・下水道事業会計補正予算） （PDF 3.2 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/019/604/R8-1teirei_sicyo3-7.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 国民健康保険特別会計 | 補正第1号 | [第64号議案から第68号議案まで（令和7年度一般会計・3特別会計・下水道事業会計補正予算） （PDF 3.1 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/018/381/R7-3teirei_sicyo64-68.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 国民健康保険特別会計 | 補正第2号 | [第79号議案から第82号議案まで（令和7年度一般会計補正予算・3特別会計補正予算） （PDF 1.9 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/018/981/R7-4teirei_sicyo79-82.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 国民健康保険特別会計 | 補正第3号 | [第107号議案から第111号議案まで（令和7年度一般会計補正予算・3特別会計補正予算・下水道事業会計補正予算） （PDF 1.9 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/018/981/R7-4teirei_sicyo107-111.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 国民健康保険特別会計 | 補正第4号 | [第3号議案から第7号議案まで（令和7年度一般会計補正予算第11号・各特別会計補正予算・下水道事業会計補正予算） （PDF 3.2 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/019/604/R8-1teirei_sicyo3-7.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 後期高齢者医療特別会計 | 補正第1号 | [第64号議案から第68号議案まで（令和7年度一般会計・3特別会計・下水道事業会計補正予算） （PDF 3.1 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/018/381/R7-3teirei_sicyo64-68.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 後期高齢者医療特別会計 | 補正第2号 | [第79号議案から第82号議案まで（令和7年度一般会計補正予算・3特別会計補正予算） （PDF 1.9 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/018/981/R7-4teirei_sicyo79-82.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 後期高齢者医療特別会計 | 補正第3号 | [第107号議案から第111号議案まで（令和7年度一般会計補正予算・3特別会計補正予算・下水道事業会計補正予算） （PDF 1.9 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/018/981/R7-4teirei_sicyo107-111.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2025 | 後期高齢者医療特別会計 | 補正第4号 | [第3号議案から第7号議案まで（令和7年度一般会計補正予算第11号・各特別会計補正予算・下水道事業会計補正予算） （PDF 3.2 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/019/604/R8-1teirei_sicyo3-7.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2026 | 一般会計 | 補正第1号 | [第39号議案から第40号議案まで（令和8年度一般会計補正予算第1号・介護保険特別会計補正予算） （PDF 815.9 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/019/604/R8-1teirei_sicyo39-40.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2026 | 一般会計 | 補正第2号 | [第41号議案（令和8年度一般会計補正予算第2号） （PDF 744.3 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/020/294/R8-2teirei_sicyo41.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2026 | 一般会計 | 補正第3号 | [第69号議案（令和8年度一般会計補正予算第3号） （PDF 368.6 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/020/294/R8-2teirei_sicyo69.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2026 | 一般会計 | 補正第4号 | [第75号議案から第78号議案まで（令和8年度一般会計・3特別会計補正予算） （PDF 2.6 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/021/205/R8-3teirei_sicyo75-78.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2026 | 介護保険特別会計 | 当初 | [第9号議案から第12号議案まで（令和8年度 各特別会計予算・下水道事業会計予算） （PDF 5.2 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/019/604/R8-1teirei_sicyo9-12.pdf) | 未確認 |
| 多摩市 | 2026 | 介護保険特別会計 | 補正第1号 | [第39号議案から第40号議案まで（令和8年度一般会計補正予算第1号・介護保険特別会計補正予算） （PDF 815.9 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/019/604/R8-1teirei_sicyo39-40.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2026 | 介護保険特別会計 | 補正第2号 | [第75号議案から第78号議案まで（令和8年度一般会計・3特別会計補正予算） （PDF 2.6 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/021/205/R8-3teirei_sicyo75-78.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2026 | 国民健康保険特別会計 | 当初 | [第9号議案から第12号議案まで（令和8年度 各特別会計予算・下水道事業会計予算） （PDF 5.2 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/019/604/R8-1teirei_sicyo9-12.pdf) | 未確認 |
| 多摩市 | 2026 | 国民健康保険特別会計 | 補正第1号 | [第75号議案から第78号議案まで（令和8年度一般会計・3特別会計補正予算） （PDF 2.6 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/021/205/R8-3teirei_sicyo75-78.pdf) | 候補1件（最新版の網羅確認なし） |
| 多摩市 | 2026 | 後期高齢者医療特別会計 | 当初 | [第9号議案から第12号議案まで（令和8年度 各特別会計予算・下水道事業会計予算） （PDF 5.2 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/019/604/R8-1teirei_sicyo9-12.pdf) | 未確認 |
| 多摩市 | 2026 | 後期高齢者医療特別会計 | 補正第1号 | [第75号議案から第78号議案まで（令和8年度一般会計・3特別会計補正予算） （PDF 2.6 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/021/205/R8-3teirei_sicyo75-78.pdf) | 候補1件（最新版の網羅確認なし） |

## 会計・補正号などが未確定の資料

これらは対象に分類できず、上の未採用対象には加算していない。同じ資料が分類済み対象にも含まれる場合がある。

| 自治体 | 掲載年度 | 掲載資料 | 未確定項目 |
|---|---|---|---|
| 千代田区 | 2020 | [介護保険特別会計歳入歳出決算事項別明細書（PDF：426KB）](https://www.city.chiyoda.lg.jp/documents/15979/r2kessansho-4.pdf) | expenditure_direction_unconfirmed |
| 千代田区 | 2020 | [後期高齢者医療特別会計歳入歳出決算事項別明細書（PDF：289KB）](https://www.city.chiyoda.lg.jp/documents/15979/r2kessansho-5.pdf) | expenditure_direction_unconfirmed |
| 千代田区 | 2020 | [国民健康保険事業会計歳入歳出決算事項別明細書（PDF：400KB）](https://www.city.chiyoda.lg.jp/documents/15979/r2kessansho-3.pdf) | expenditure_direction_unconfirmed |
| 千代田区 | 2020 | [千代田区各会計実質収支に関する調書（PDF：158KB）](https://www.city.chiyoda.lg.jp/documents/15979/r2kessansho-6.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2021 | [財政運営の状況（令和3年度財政レポート）（PDF：1,208KB）](https://www.city.chiyoda.lg.jp/documents/27821/r4zaiseijokyo_1.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2021 | [千代田区各会計実質収支に関する調書（PDF：153KB）](https://www.city.chiyoda.lg.jp/documents/15979/r3kessansho-6.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2021 | [介護保険特別会計歳入歳出決算事項別明細書（PDF：391KB）](https://www.city.chiyoda.lg.jp/documents/15979/r3kessansho-4.pdf) | expenditure_direction_unconfirmed |
| 千代田区 | 2021 | [後期高齢者医療特別会計歳入歳出決算事項別明細書（PDF：281KB）](https://www.city.chiyoda.lg.jp/documents/15979/r3kessansho-5.pdf) | expenditure_direction_unconfirmed |
| 千代田区 | 2021 | [国民健康保険事業会計歳入歳出決算事項別明細書（PDF：341KB）](https://www.city.chiyoda.lg.jp/documents/15979/r3kessansho-3.pdf) | expenditure_direction_unconfirmed |
| 千代田区 | 2022 | [令和4年度各会計予算（一般会計・国民健康保険事業会計・介護保険特別会計・後期高齢者医療特別会計）（PDF：2,353KB）](https://www.city.chiyoda.lg.jp/documents/583/r4yosansho.pdf) | detail_observation_only_in_contents |
| 千代田区 | 2022 | [ちよだみらいプロジェクトと令和4年度予算（PDF：498KB）](https://www.city.chiyoda.lg.jp/documents/27821/r4shuyojigyonogaiyo_1.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2022 | [予算編成の概況（PDF：793KB）](https://www.city.chiyoda.lg.jp/documents/27821/r4yosangaikyo_1.pdf) | moku_or_project_detail_not_observed |
| 千代田区 | 2022 | [区民生活を支えるために重点的に取り組む施策（PDF：5,347KB）](https://www.city.chiyoda.lg.jp/documents/27821/r4jutenshisaku_1.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2022 | [国民健康保険事業会計歳入歳出決算事項別明細書（PDF：706KB）](https://www.city.chiyoda.lg.jp/documents/15979/r4kessansho-3.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2022 | [千代田区各会計実質収支に関する調書（PDF：96KB）](https://www.city.chiyoda.lg.jp/documents/15979/r4kessansho-6.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2022 | [表紙・目次・歳入歳出決算総括・歳入歳出決算書（PDF：595KB）](https://www.city.chiyoda.lg.jp/documents/15979/r4kessansho-1.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2022 | [一般会計歳入歳出決算事項別明細書（PDF：3,599KB）](https://www.city.chiyoda.lg.jp/documents/15979/r4kessansho-2.pdf) | expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2022 | [介護保険特別会計歳入歳出決算事項別明細書（PDF：837KB）](https://www.city.chiyoda.lg.jp/documents/15979/r4kessansho-4.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2022 | [後期高齢者医療特別会計歳入歳出決算事項別明細書（PDF：453KB）](https://www.city.chiyoda.lg.jp/documents/15979/r4kessansho-5.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2023 | [令和5年度各会計予算（一般会計・国民健康保険事業会計・介護保険特別会計・後期高齢者医療特別会計）（PDF：1,888KB）](https://www.city.chiyoda.lg.jp/documents/583/r5yosansho.pdf) | detail_observation_only_in_contents |
| 千代田区 | 2023 | [基本構想と予算の関係性（PDF：1,017KB）](https://www.city.chiyoda.lg.jp/documents/28995/r5kihonkoso_1.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2023 | [予算編成の概況（PDF：787KB）](https://www.city.chiyoda.lg.jp/documents/28995/r5yosangaikyo_1.pdf) | moku_or_project_detail_not_observed |
| 千代田区 | 2023 | [重点的に取り組む施策（PDF：4,556KB）](https://www.city.chiyoda.lg.jp/documents/28995/r5jutenshisaku_1.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2023 | [国民健康保険事業会計歳入歳出決算事項別明細書（PDF：1,907KB）](https://www.city.chiyoda.lg.jp/documents/15979/r5kessansho-4.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2023 | [一般会計歳入歳出決算事項別明細書（歳入）（PDF：3,394KB）](https://www.city.chiyoda.lg.jp/documents/15979/r5kessansho-2.pdf) | expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2023 | [千代田区各会計実質収支に関する調書（PDF：236KB）](https://www.city.chiyoda.lg.jp/documents/15979/r5kessansho-7.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2023 | [表紙・目次・歳入歳出決算総括・歳入歳出決算書（PDF：2,094KB）](https://www.city.chiyoda.lg.jp/documents/15979/r5kessansho-1.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2023 | [後期高齢者医療特別会計歳入歳出決算事項別明細書（PDF：1,095KB）](https://www.city.chiyoda.lg.jp/documents/15979/r5kessansho-6.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2023 | [介護保険特別会計歳入歳出決算事項別明細書（PDF：2,109KB）](https://www.city.chiyoda.lg.jp/documents/15979/r5kessansho-5.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2023 | [一般会計歳入歳出決算事項別明細書（歳出）（PDF：4,902KB）](https://www.city.chiyoda.lg.jp/documents/15979/r5kessansho-3.pdf) | expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2024 | [令和6年度各会計予算（一般会計・国民健康保険事業会計・介護保険特別会計・後期高齢者医療特別会計）（PDF：2,363KB）](https://www.city.chiyoda.lg.jp/documents/583/r6kaikeiyosan.pdf) | detail_observation_only_in_contents |
| 千代田区 | 2024 | [予算編成の概況（PDF：1,167KB）](https://www.city.chiyoda.lg.jp/documents/31124/r6aramashi-gaikyo_1.pdf) | moku_or_project_detail_not_observed |
| 千代田区 | 2024 | [基本構想と予算の関係性（PDF：1,402KB）](https://www.city.chiyoda.lg.jp/documents/31124/r6aramashi-koso_1.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2024 | [重点的に取り組む施策（PDF：5,678KB）](https://www.city.chiyoda.lg.jp/documents/31124/r6aramashi-shisaku_1.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2024 | [後期高齢者医療特別会計歳入歳出決算事項別明細書（PDF：1,326KB）](https://www.city.chiyoda.lg.jp/documents/15979/r6kessansho-6.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2024 | [一般会計歳入歳出決算事項別明細書（歳入）（PDF：4,154KB）](https://www.city.chiyoda.lg.jp/documents/15979/r6kessansho-2.pdf) | expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2024 | [表紙・目次・歳入歳出決算総括・歳入歳出決算書（PDF：2,172KB）](https://www.city.chiyoda.lg.jp/documents/15979/r6kessansho-1.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2024 | [千代田区各会計実質収支に関する調書（PDF：265KB）](https://www.city.chiyoda.lg.jp/documents/15979/r6kessansho-7.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2024 | [一般会計歳入歳出決算事項別明細書（歳出）（PDF：6,228KB）](https://www.city.chiyoda.lg.jp/documents/15979/r6kessansho-3.pdf) | expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2024 | [国民健康保険事業会計歳入歳出決算事項別明細書（PDF：2,249KB）](https://www.city.chiyoda.lg.jp/documents/15979/r6kessansho-4.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2024 | [介護保険特別会計歳入歳出決算事項別明細書（PDF：2,622KB）](https://www.city.chiyoda.lg.jp/documents/15979/r6kessansho-5.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2025 | [重点的に取り組む施策（PDF：8,263KB）](https://www.city.chiyoda.lg.jp/documents/32625/r7aramashi03-shisaku_2.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2025 | [令和7年度各会計予算（一般会計・国民健康保険事業会計・介護保険特別会計・後期高齢者医療特別会計）（PDF：739KB）](https://www.city.chiyoda.lg.jp/documents/583/r7kaikeiyosan.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2025 | [予算編成の概況（PDF：1,172KB）](https://www.city.chiyoda.lg.jp/documents/32625/r7aramashi01-gaikyo_2.pdf) | moku_or_project_detail_not_observed |
| 千代田区 | 2025 | [基本構想と予算の関係性（PDF：2,073KB）](https://www.city.chiyoda.lg.jp/documents/32625/r7aramashi02-koso_2.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2026 | [重点的に取り組む施策（PDF：3,453KB）](https://www.city.chiyoda.lg.jp/documents/34000/r8aramashi-jutenshisaku_1.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 千代田区 | 2026 | [令和8年度各会計予算（一般会計・国民健康保険事業会計・介護保険特別会計・後期高齢者医療特別会計）（PDF：3,364KB）](https://www.city.chiyoda.lg.jp/documents/583/r8kaikeiyosan.pdf) | detail_observation_only_in_contents |
| 千代田区 | 2026 | [予算編成の概況（PDF：805KB）](https://www.city.chiyoda.lg.jp/documents/34000/r8aramashi-gaikyo_1.pdf) | moku_or_project_detail_not_observed |
| 千代田区 | 2026 | [基本構想と予算の関係性（PDF：1,755KB）](https://www.city.chiyoda.lg.jp/documents/34000/r8aramashi-kihonkoso_1.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 三鷹市 | 2006 | [平成18年度補正予算（PDF 102KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_11.pdf) | account_unconfirmed, amendment_number_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 三鷹市 | 2007 | [平成19年度補正予算（PDF 125KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_10.pdf) | account_unconfirmed, amendment_number_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 三鷹市 | 2013 | [平成25年度補正予算（PDF 523KB）](https://www.city.mitaka.lg.jp/c_service/037/attached/attach_37729_4.pdf) | moku_or_project_detail_not_observed |
| 三鷹市 | 2019 | [令和元年度9月補正予算（PDF 127KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_7.pdf) | moku_or_project_detail_not_observed |
| 三鷹市 | 2019 | [令和元年度12月補正予算（PDF 181KB）](https://www.city.mitaka.lg.jp/c_service/086/attached/attach_86443_4.pdf) | moku_or_project_detail_not_observed |
| 三鷹市 | 2020 | [令和2年度三鷹市一般会計・特別会計予算及び同説明書(1)（PDF 3140KB）](https://www.city.mitaka.lg.jp/c_service/090/attached/attach_90334_11.pdf) | detail_observation_only_in_contents |
| 三鷹市 | 2020 | [令和2年度3月補正予算（第12号）（PDF 236KB）](https://www.city.mitaka.lg.jp/c_service/091/attached/attach_91760_6.pdf) | account_unconfirmed, amendment_number_unconfirmed |
| 三鷹市 | 2020 | [令和2年度5月補正予算（第1号）（PDF 97KB）](https://www.city.mitaka.lg.jp/c_service/087/attached/attach_87484_11.pdf) | moku_or_project_detail_not_observed |
| 三鷹市 | 2020 | [令和2年度12月補正予算（第9号）（PDF 238KB）](https://www.city.mitaka.lg.jp/c_service/089/attached/attach_89550_2.pdf) | account_unconfirmed, amendment_number_unconfirmed, moku_or_project_detail_not_observed |
| 三鷹市 | 2020 | [令和2年度1月補正予算（第11号）（PDF 108KB）](https://www.city.mitaka.lg.jp/c_service/091/attached/attach_91760_9.pdf) | moku_or_project_detail_not_observed |
| 三鷹市 | 2021 | [令和3年度三鷹市一般会計・特別会計予算及び同説明書(1)（PDF 2844KB）](https://www.city.mitaka.lg.jp/c_service/090/attached/attach_90334_9.pdf) | detail_observation_only_in_contents |
| 三鷹市 | 2021 | [令和3年度9月補正予算（第6号）（PDF 85KB）](https://www.city.mitaka.lg.jp/c_service/093/attached/attach_93558_3.pdf) | moku_or_project_detail_not_observed |
| 三鷹市 | 2021 | [令和3年度6月補正予算（第3号）（PDF 155KB）](https://www.city.mitaka.lg.jp/c_service/093/attached/attach_93558_9.pdf) | moku_or_project_detail_not_observed |
| 三鷹市 | 2021 | [令和3年度3月補正予算（第14号）（PDF 243KB）](https://www.city.mitaka.lg.jp/c_service/097/attached/attach_97160_5.pdf) | account_unconfirmed, amendment_number_unconfirmed, moku_or_project_detail_not_observed |
| 三鷹市 | 2021 | [令和3年度三鷹市下水道事業会計補正予算（第1号）及び同説明書（PDF 201KB）](https://www.city.mitaka.lg.jp/c_service/094/attached/attach_94775_8.pdf) | expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 三鷹市 | 2021 | [令和3年度9月補正予算（第7号）（PDF 182KB）](https://www.city.mitaka.lg.jp/c_service/093/attached/attach_93558_1.pdf) | moku_or_project_detail_not_observed |
| 三鷹市 | 2022 | [令和4年度三鷹市一般会計・特別会計予算及び同説明書(1)（PDF 2853KB）](https://www.city.mitaka.lg.jp/c_service/090/attached/attach_90334_7.pdf) | detail_observation_only_in_contents |
| 三鷹市 | 2023 | [令和5年度三鷹市一般会計・特別会計予算及び同説明書(1)（PDF 2848KB）](https://www.city.mitaka.lg.jp/c_service/090/attached/attach_90334_5.pdf) | detail_observation_only_in_contents |
| 三鷹市 | 2024 | [令和6年度三鷹市一般会計・特別会計予算及び同説明書(1)（PDF 2854KB）](https://www.city.mitaka.lg.jp/c_service/090/attached/attach_90334_3.pdf) | detail_observation_only_in_contents |
| 三鷹市 | 2025 | [令和7年度三鷹市一般会計・特別会計予算及び同説明書(1)（PDF 2882KB）](https://www.city.mitaka.lg.jp/c_service/090/attached/attach_90334_1.pdf) | detail_observation_only_in_contents |
| 三鷹市 | 2025 | [令和7年度歳入歳出決算書（PDF 3352KB）](https://www.city.mitaka.lg.jp/c_service/087/attached/attach_87972_1.pdf) | detail_observation_only_in_contents |
| 三鷹市 | 2025 | [令和7年度下水道事業会計決算書（PDF 566KB）](https://www.city.mitaka.lg.jp/c_service/087/attached/attach_87972_2.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 三鷹市 | 2026 | [令和8年度三鷹市一般会計・特別会計予算及び同説明書(1)（PDF 2877KB）](https://www.city.mitaka.lg.jp/c_service/085/attached/attach_85303_11.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2020 | [令和2年度特別会計予算大綱 （PDF 999.9 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/269/tokkaitaikou.pdf) | moku_or_project_detail_not_observed |
| 昭島市 | 2020 | [全頁 （PDF 6.8 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/269/zennpe-ji.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2020 | [令和2年度一般会計予算大綱 （PDF 1.4 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/269/ippanntaikou.pdf) | moku_or_project_detail_not_observed |
| 昭島市 | 2020 | [令和2年度社会保障財源化分の地方消費税交付金が充てられる社会保障4経費その他社会保障施策に要する経費 （PDF 35.7 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/269/r2yosanshouhizei.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 昭島市 | 2020 | [中神土地区画整理事業特別会計当初予算書及び予算説明書 （PDF 794.7 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/269/kukaku.pdf) | account_unconfirmed |
| 昭島市 | 2020 | [令和2年度決算書（一般会計歳入事項別明細書） （PDF 344.7 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/261/r02kessannsyosainyuu.pdf) | expenditure_direction_unconfirmed |
| 昭島市 | 2020 | [令和2年度決算書（全項） （PDF 5.8 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/261/r02kessannsho.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2020 | [令和2年度決算書（表紙・目次・一般会計決算書） （PDF 378.6 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/261/r02kessannsyohyousi.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2021 | [令和3年度一般会計予算大綱 （PDF 387.8 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/268/3ippantaiko.pdf) | moku_or_project_detail_not_observed |
| 昭島市 | 2021 | [全頁 （PDF 5.6 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/268/00.r3zenbu.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2021 | [令和3年度特別会計予算大綱 （PDF 336.8 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/268/3tokkaitaiko.pdf) | moku_or_project_detail_not_observed |
| 昭島市 | 2021 | [令和3年度社会保障財源化分の地方消費税交付金が充てられる社会保障4経費その他社会保障施策に要する経費 （PDF 115.0 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/268/r3yosanshouhizei.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 昭島市 | 2021 | [令和3年度決算書（全項） （PDF 5.8 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/260/r3kessan0.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2021 | [令和3年度決算書（表紙・目次・一般会計決算書） （PDF 307.9 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/260/r3kessan1.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2021 | [令和3年度決算書（一般会計歳入事項別明細書） （PDF 352.7 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/260/r3kessan2.pdf) | expenditure_direction_unconfirmed |
| 昭島市 | 2022 | [社会保障財源化分の地方消費税交付金が充てられる社会保障4経費その他社会保障施策に要する経費 （PDF 115.0 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/267/r4syouhizeikouhukin.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 昭島市 | 2022 | [全頁 （PDF 7.1 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/267/00.r4zenbu.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2022 | [令和4年度特別会計予算大綱 （PDF 845.0 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/267/r4tokkaitaikou.pdf) | moku_or_project_detail_not_observed |
| 昭島市 | 2022 | [令和4年度一般会計予算大綱 （PDF 1.4 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/267/r4ippantaikou.pdf) | moku_or_project_detail_not_observed |
| 昭島市 | 2022 | [令和4年度決算書（一般会計歳入事項別明細書） （PDF 338.4 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/259/r4kessan2.pdf) | expenditure_direction_unconfirmed |
| 昭島市 | 2022 | [令和4年度決算書（全項） （PDF 2.3 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/259/r4kessan0.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2022 | [令和4年度決算書（表紙・目次・一般会計決算書） （PDF 296.7 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/259/r4kessan1.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2023 | [全頁（中神土地区画整理事業特別会計及び中神駅北側地域整備事業特別会計） （PDF 1.8 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/266/1-2.zenbu_kukaku.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 昭島市 | 2023 | [社会保障財源化分の地方消費税交付金が充てられる社会保障4経費その他社会保障施策に要する経費 （PDF 114.9 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/266/3.syouhizeikouhukin.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 昭島市 | 2023 | [中神駅北側地域整備事業特別会計当初予算書及び予算説明書 （PDF 721.0 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/266/2-7.kukaku_kitagawa.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 昭島市 | 2023 | [介護保険特別会計当初予算書及び予算説明書 （PDF 603.4 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/266/2-4.kaigo.pdf) | account_unconfirmed |
| 昭島市 | 2023 | [令和5年度特別会計予算大綱 （PDF 349.3 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/266/02_tokkaitaikour5.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 昭島市 | 2023 | [国民健康保険特別会計当初予算書及び予算説明書 （PDF 580.7 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/266/2-3.kokuho.pdf) | account_unconfirmed |
| 昭島市 | 2023 | [中神土地区画整理事業特別会計当初予算書及び予算説明書 （PDF 961.3 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/266/2-6.kuaku_kukaku.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 昭島市 | 2023 | [令和5年度一般会計予算大綱 （PDF 409.6 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/266/01_ippantaikour5.pdf) | expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 昭島市 | 2023 | [後期高齢者医療特別会計当初予算書及び予算説明書 （PDF 420.4 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/266/2-5.kouki.pdf) | account_unconfirmed |
| 昭島市 | 2023 | [令和5年度決算書（一般会計歳入事項別明細書） （PDF 300.5 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/258/r5kessan2.pdf) | expenditure_direction_unconfirmed |
| 昭島市 | 2023 | [令和5年度決算書（表紙・目次・一般会計決算書） （PDF 253.9 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/258/r5kessan1.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2023 | [令和5年度決算書（全項） （PDF 2.6 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/258/r5kessan0.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2024 | [社会保障財源化分の地方消費税交付金が充てられる社会保障4経費その他社会保障施策に要する経費 （PDF 115.0 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/265/3.syouhizeikouhukin.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 昭島市 | 2024 | [中神駅北側地域整備事業特別会計当初予算書及び予算説明書 （PDF 448.4 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/265/2-7.kitagawa.pdf) | account_unconfirmed |
| 昭島市 | 2024 | [全頁 （PDF 5.7 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/265/1-1.zenbu.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2024 | [令和6年度特別会計予算大綱 （PDF 477.8 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/265/02_tokkaitaikour6.pdf) | moku_or_project_detail_not_observed |
| 昭島市 | 2024 | [令和6年度一般会計予算大綱 （PDF 382.7 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/265/01_ippantaikour6.pdf) | moku_or_project_detail_not_observed |
| 昭島市 | 2024 | [令和6年度決算書（全項）（PDF:3,709KB） （PDF 3.7 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/009/130/r6kessan0.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2024 | [令和6年度決算書（表紙・目次・会計別一覧表）（PDF:103KB） （PDF 107.9 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/009/130/r6kessan1.pdf) | account_unconfirmed, detail_observation_only_in_contents |
| 昭島市 | 2024 | [令和6年度決算書（中神駅北側地域整備事業特別会計） （PDF 310.2 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/009/130/r6kessan7.pdf) | account_unconfirmed |
| 昭島市 | 2025 | [令和7年度一般会計予算大綱 （PDF 791.4 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/264/01_ippantaikour7.pdf) | moku_or_project_detail_not_observed |
| 昭島市 | 2025 | [一般会計当初予算及び予算説明書 （PDF 3.8 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/264/2-1.ippan.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2025 | [社会保障財源化分の地方消費税交付金が充てられる社会保障4経費その他社会保障施策に要する経費 （PDF 115.0 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/264/3-1.syouhizeikouhukin.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 昭島市 | 2025 | [全頁 （PDF 8.7 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/264/1-1.zenbu.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2025 | [後期高齢者医療特別会計当初予算書及び予算説明書 （PDF 353.1 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/264/2-4.kouki.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 昭島市 | 2025 | [介護保険特別会計当初予算書及び予算説明書 （PDF 872.9 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/264/2-3.kaigo.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2025 | [中神駅北側地域整備事業特別会計当初予算書及び予算説明書 （PDF 402.0 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/264/2-6.kitagawa.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 昭島市 | 2025 | [中神土地区画整理事業特別会計当初予算書及び予算説明書 （PDF 322.1 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/264/2-5.kukaku.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 昭島市 | 2025 | [国民健康保険特別会計当初予算書及び予算説明書 （PDF 386.5 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/264/2-2.kokuho.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2025 | [令和7年度特別会計予算大綱 （PDF 972.3 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/005/264/02_tokkaitaikour7.pdf) | moku_or_project_detail_not_observed |
| 昭島市 | 2026 | [後期高齢者医療特別会計当初予算書及び予算説明書 （PDF 2.6 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/011/521/2-4.kouki.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2026 | [国民健康保険特別会計当初予算書及び予算説明書 （PDF 551.2 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/011/521/2-2.kokuho.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2026 | [中神駅北側地域整備事業特別会計当初予算書及び予算説明書 （PDF 1.7 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/011/521/2-6.kitagawa.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 昭島市 | 2026 | [令和8年度一般会計予算大綱 （PDF 779.7 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/011/521/01.r8ippantaikou.pdf) | moku_or_project_detail_not_observed |
| 昭島市 | 2026 | [令和8年度特別会計予算大綱 （PDF 912.5 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/011/521/02.r8tokkaitaikou.pdf) | moku_or_project_detail_not_observed |
| 昭島市 | 2026 | [全頁 （PDF 12.0 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/011/521/1-1.zenbu.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2026 | [社会保障財源化分の地方消費税交付金が充てられる社会保障4経費その他社会保障施策に要する経費 （PDF 88.5 KB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/011/521/3-1.syouhizeikouhukin.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 昭島市 | 2026 | [介護保険特別会計当初予算書及び予算説明書 （PDF 2.7 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/011/521/2-3.kaigo.pdf) | detail_observation_only_in_contents |
| 昭島市 | 2026 | [中神土地区画整理事業特別会計当初予算書及び予算説明書 （PDF 1.6 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/011/521/2-5.kukaku.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 昭島市 | 2026 | [一般会計当初予算及び予算説明書 （PDF 2.7 MB）](https://www.city.akishima.lg.jp/_res/projects/default_project/_page_/001/011/521/2-1.ippan.pdf) | detail_observation_only_in_contents |
| 狛江市 | 不明 | [令和4年5月 狛江市議会第2回定例会提出議案 [2261KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,121266,c,html/121266/R4-2nd.pdf) | expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 狛江市 | 不明 | [令和3年2月 狛江市議会第1回定例会提出議案 [4595KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,113886,c,html/113886/R3-1st.gian.pdf) | expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 狛江市 | 不明 | [令和4年8月 狛江市議会第3回定例会提出議案 [5605KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,121266,c,html/121266/R4-3rd.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 不明 | [令和4年2月 狛江市議会第1回定例会提出議案 [11849KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,121266,c,html/121266/R4-1st.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 不明 | [令和７年狛江市議会第４回定例会提出議案 [ 72 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,136986,c,html/136986/20251126-132457.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed, year_or_document_kind_unconfirmed |
| 狛江市 | 不明 | [令和3年8月 狛江市議会第3回定例会提出議案 [5231KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,113886,c,html/113886/R3-3rd.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 不明 | [令和3年11月 狛江市議会第4回定例会提出議案 [4318KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,113886,c,html/113886/R3-4th.pdf) | expenditure_direction_unconfirmed |
| 狛江市 | 2020 | [出納検査報告書（令和2年度決算分） [99KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,870,c,html/870/20210701-091452.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 狛江市 | 2020 | [令和２年度一般会計・特別会計歳入歳出決算書について.pdf [ 85 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,117004,c,html/117004/20210721-183633.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 狛江市 | 2020 | [令和2年度 歳出事項別明細 [1868KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,130247,c,html/130247/R2-saishutsu-jikoubetsu-meisai.pdf) | account_unconfirmed, expenditure_direction_unconfirmed |
| 狛江市 | 2020 | [令和２年度補正予算案について.pdf [1829KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,107964,c,html/107964/20200706-155155.pdf) | account_unconfirmed, amendment_number_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 狛江市 | 2020 | [令和２年度補正予算案について.pdf [ 1071 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,114057,c,html/114057/20210304-092218.pdf) | account_unconfirmed, amendment_number_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 狛江市 | 2021 | [令和３年度当初予算案について.pdf [ 110 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,113863,c,html/113863/20210218-134035.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 狛江市 | 2021 | [令和３年度当初予算案について.pdf [ 184 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,113409,c,html/113409/20210218-131520.pdf) | account_unconfirmed, expenditure_direction_unconfirmed |
| 狛江市 | 2021 | [出納検査報告書（令和3年度決算分）](https://www.city.komae.tokyo.jp/index.cfm/46,870,c,html/870/20220804-113459.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 狛江市 | 2021 | [令和3年度 歳出事項別明細 [1954KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,130245,c,html/130245/saisyutu.pdf) | account_unconfirmed, expenditure_direction_unconfirmed |
| 狛江市 | 2021 | [令和3年度 新型コロナウイルス感染症対策関連事業に係る予算一覧 [112KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,113886,c,html/113886/COVID-19.yosan.pdf) | expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 狛江市 | 2021 | [令和３年度補正予算案について.pdf [ 872 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/50,114057,c,html/114057/20210304-092247.pdf) | account_unconfirmed, amendment_number_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 狛江市 | 2021 | [令和３年度補正予算案について](https://www.city.komae.tokyo.jp/index.cfm/50,115219,c,html/115219/20210507-150226.pdf) | account_unconfirmed, amendment_number_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 狛江市 | 2022 | [令和4年度 歳出事項別明細 [1968KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,130170,c,html/130170/20231005-114612.pdf) | account_unconfirmed, expenditure_direction_unconfirmed |
| 狛江市 | 2022 | [出納検査報告書（令和4年度決算分） [83KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,870,c,html/870/20230630-151619.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 狛江市 | 2022 | [令和4年度 東京都狛江市一般会計特別会計 歳入歳出決算書 [ 10142 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,128130,c,html/128130/20241011-133200.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 狛江市 | 2022 | [令和4年度 歳入事項別明細 [2868KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,130170,c,html/130170/20231005-114503.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 狛江市 | 2022 | [令和4年度 狛江市一般会計補正予算（6号） [89KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,126856,c,html/126856/1-hosei.pdf) | expenditure_direction_unconfirmed |
| 狛江市 | 2023 | [出納検査報告書 令和5年度（決算） [ 82 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,870,c,html/870/20250501-094206.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 狛江市 | 2023 | [令和５年度 東京都狛江市一般会計特別会計 歳入歳出決算書[ 9260 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,133351,c,html/133351/20241011-132915.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 狛江市 | 2023 | [令和5年度後期高齢者医療特別会計補正予算書（第2号） [228KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,126778,c,html/126778/20240222-154208.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2023 | [令和5年度一般会計補正予算書（第3号） [725KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,126778,c,html/126778/20230831-133307.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2023 | [令和5年度一般会計補正予算書（第5号） [271KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,126778,c,html/126778/20231222-094555.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2023 | [令和5年度一般会計補正予算書（第2号） [405KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,126778,c,html/126778/20230608-095441.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2023 | [令和5年度一般会計補正予算書（第4号） [700KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,126778,c,html/126778/20231124-133108.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2023 | [令和5年度一般会計補正予算書（第6号） [282KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,126778,c,html/126778/20240201-104448.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2023 | [令和5年度 狛江市一般会計補正予算（第4号） [95KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,126856,c,html/126856/4-hosei.pdf) | expenditure_direction_unconfirmed |
| 狛江市 | 2023 | [令和5年度後期高齢者医療特別会計補正予算書（第1号）[268KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,126778,c,html/126778/20230831-175511.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2023 | [令和5年度一般会計補正予算書（第1号） [599KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,126778,c,html/126778/20230601-112553.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2023 | [令和5年度国民健康保険特別会計補正予算書（第1号） [260KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,126778,c,html/126778/20230831-175344.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2023 | [令和5年度 狛江市一般会計補正予算（第2号） [113KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,126856,c,html/126856/2-hosei.pdf) | expenditure_direction_unconfirmed |
| 狛江市 | 2023 | [令和5年度国民健康保険特別会計補正予算書（第2号） [240KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,126778,c,html/126778/20231124-133139.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2023 | [令和5年度一般会計補正予算書（第7号） [475KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,126778,c,html/126778/20240222-154057.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2023 | [令和5年度 狛江市一般会計補正予算（7号） [73KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132125,c,html/132125/1-R5hosei7.pdf) | expenditure_direction_unconfirmed |
| 狛江市 | 2023 | [令和5年度介護保険特別会計補正予算書（第１号） [244KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,126778,c,html/126778/20230831-175641.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2023 | [令和5年度 狛江市一般会計補正予算（第3号） [117KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,126856,c,html/126856/3-hosei.pdf) | expenditure_direction_unconfirmed |
| 狛江市 | 2024 | [令和６年度 東京都狛江市一般会計特別会計歳入歳出決算書 [ 9435 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,137752,c,html/137752/20251006-151003.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 狛江市 | 2024 | [令和６年度国民健康保険特別会計補正予算書（第２号）.pdf [ 250 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132059,c,html/132059/20241127-152744.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2024 | [【概要】令和6年度一般会計補正予算書（第3号）.pdf [ 87 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132059,c,html/132059/20241016-111559.pdf) | expenditure_direction_unconfirmed |
| 狛江市 | 2024 | [【概要】令和６年度一般会計補正予算書（第６号）.pdf [ 74 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132059,c,html/132059/20241226-143036.pdf) | expenditure_direction_unconfirmed |
| 狛江市 | 2024 | [【概要】令和６年度一般会計補正予算書（第５号）.pdf [ 91 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132059,c,html/132059/20241127-152932.pdf) | expenditure_direction_unconfirmed |
| 狛江市 | 2024 | [【概要】令和6年度一般会計補正予算書（第1号）.pdf [ 92 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132059,c,html/132059/20241008-192757.pdf) | expenditure_direction_unconfirmed |
| 狛江市 | 2024 | [令和6年度狛江市一般会計補正予算（2号） [ 105 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132125,c,html/132125/20240830-143321.pdf) | expenditure_direction_unconfirmed |
| 狛江市 | 2024 | [令和6年度 狛江市一般会計補正予算（1号） [88KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132125,c,html/132125/2-hosei.pdf) | expenditure_direction_unconfirmed |
| 狛江市 | 2024 | [令和6年度後期高齢者医療特別会計補正予算書（第1号）.pdf [ 263 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132059,c,html/132059/20241008-193057.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2024 | [令和6年度国民健康保険特別会計補正予算書（第1号） .pdf [ 255 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132059,c,html/132059/20241008-193135.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2024 | [令和6年度一般会計補正予算書（第3号）.pdf [ 363 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132059,c,html/132059/20241008-193235.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2024 | [【概要】令和6年度一般会計補正予算書（第4号）.pdf [ 58 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132059,c,html/132059/20241016-111624.pdf) | expenditure_direction_unconfirmed |
| 狛江市 | 2024 | [令和6年度一般会計補正予算書（第1号）.pdf [ 345 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132059,c,html/132059/20241008-192627.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2024 | [令和６年度一般会計補正予算書（第６号）.pdf [ 366 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132059,c,html/132059/20241226-143012.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2024 | [【概要】令和6年度一般会計補正予算書（第2号）.pdf [ 104 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132059,c,html/132059/20241008-192917.pdf) | expenditure_direction_unconfirmed |
| 狛江市 | 2024 | [令和6年度狛江市一般会計補正予算（5号） [ 92 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132125,c,html/132125/20241126-132518.pdf) | expenditure_direction_unconfirmed |
| 狛江市 | 2024 | [令和6年度介護保険特別会計補正予算書（第1号）.pdf [ 233 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132059,c,html/132059/20241008-193023.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2024 | [令和６年度一般会計補正予算書（第５号）.pdf [ 674 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132059,c,html/132059/20241127-152828.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2024 | [【概要】令和６年度一般会計補正予算書（第７号）.pdf [ 92 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132059,c,html/132059/20250219-125646.pdf) | expenditure_direction_unconfirmed |
| 狛江市 | 2024 | [令和６年度一般会計補正予算書（第７号）.pdf [ 594 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,132059,c,html/132059/20250219-125740.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2025 | [令和７年駐車場事業特別会計補正予算書（第１号）.pdf [ 314 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,136999,c,html/136999/20250827-165156.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2025 | [令和７年度一般会計補正予算書（第５号）.pdf [ 361 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,136999,c,html/136999/20251222-121157.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2025 | [令和７年介護保険特別会計補正予算書（第１号）.pdf [ 288 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,136999,c,html/136999/20250827-165030.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2025 | [令和７年度国民健康保険特別会計補正予算書（第１号）.pdf [ 295 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,136999,c,html/136999/20250827-164753.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2025 | [令和７年度介護保険特別会計補正予算書（第２号）.pdf [ 275 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,136999,c,html/136999/20251126-164958.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2025 | [令和７年度国民健康保険特別会計補正予算書（第２号）.pdf [ 249 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,136999,c,html/136999/20251126-164741.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2025 | [令和７年度一般会計補正予算書（第７号）.pdf [ 510 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,136999,c,html/136999/20260220-165505.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2025 | [令和７年度一般会計補正予算書（第１号）.pdf [ 430 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,136999,c,html/136999/20250515-134219.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2025 | [令和７年度介護保険特別会計補正予算書（第３号）.pdf [ 73 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,136999,c,html/136999/20260220-164624.pdf) | expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 狛江市 | 2025 | [令和７年度一般会計補正予算書（第４号）.pdf [ 666 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,136999,c,html/136999/20251126-164544.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2025 | [令和７年度後期高齢者医療特別会計補正予算書（第２号）.pdf [ 328 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,136999,c,html/136999/20260220-164717.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2025 | [令和７年後期高齢者医療特別会計補正予算書（第１号）.pdf [ 311 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,136999,c,html/136999/20250827-164851.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2025 | [令和７年度駐車場事業特別会計補正予算書（第２号）.pdf [ 229 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,136999,c,html/136999/20260220-163818.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2025 | [令和７年度国民健康保険特別会計補正予算書（第３号）.pdf [ 325 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,136999,c,html/136999/20260220-164804.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2025 | [令和７年度一般会計補正予算予算書（第３号）.pdf [ 787 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,136999,c,html/136999/20250827-164335.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2025 | [令和７年度一般会計補正予算予算書（第２号）[ 314 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,136999,c,html/136999/20250611-100205.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2026 | [令和８年度一般会計補正予算書（第１号）.pdf [ 480 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,142125,c,html/142125/20260522-141814.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2026 | [令和８年度狛江市介護保険特別会計補正予算（第１号）.pdf [ 278 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,142125,c,html/142125/20260828-175439.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2026 | [令和８年度一般会計補正予算書（第２号）.pdf [ 334 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,142125,c,html/142125/20260807-105346.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2026 | [令和８年度狛江市後期高齢者医療特別会計補正予算（第１号）.pdf [ 320 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,142125,c,html/142125/20260828-180809.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2026 | [令和８年度狛江市国民健康保険特別会計補正予算（第１号）.pdf [ 298 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,142125,c,html/142125/20260828-175252.pdf) | moku_or_project_detail_not_observed |
| 狛江市 | 2026 | [令和８年度狛江市一般会計補正予算（第３号）.pdf [ 566 KB pdfファイル]](https://www.city.komae.tokyo.jp/index.cfm/46,142125,c,html/142125/20260828-175148.pdf) | moku_or_project_detail_not_observed |
| 多摩市 | 2017 | [平成29年度多摩市下水道事業会計決算書](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/002/458/29gesui_financial_statements.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2017 | [平成29年度下水道事業の決算の状況](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/002/458/29kessann.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2018 | [平成30年度下水道事業の決算の状況](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/002/458/h30kessan.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2018 | [平成30年度多摩市下水道事業会計決算書](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/002/458/h30kessansyo.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2019 | [平成31年度一般会計歳出（当初予算）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/885/h31saisyutsuippan.csv) | expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2019 | [平成31年度特別会計歳出（当初予算）（下水道事業会計除く） ](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/885/h31saisyutsutokubetsu.csv) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2019 | [令和元年度多摩市下水道事業会計決算書](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/002/458/r1kessansyo.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2019 | [平成31年度特別会計歳入（当初予算）（下水道事業会計除く）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/885/h31sainyuutokubetsu.csv) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2019 | [令和元年度下水道事業の決算の状況](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/002/458/r1kessan.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2019 | [平成31年度一般会計歳入（当初予算）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/885/h31sainyuuippan.csv) | expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2020 | [令和2年度 各会計歳入歳出決算書（1） （PDF 3.4 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/929/0201.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2020 | [令和2年度下水道事業の決算の状況](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/002/458/r2kessanngaiyou.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2020 | [令和2年度多摩市下水道事業会計決算書](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/002/458/r2kessann.pdf) | account_unconfirmed, expenditure_direction_unconfirmed |
| 多摩市 | 2020 | [令和2年度特別会計歳入（当初予算）（下水道事業会計除く）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/885/r2sainyuutokubetukaikei.csv) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2020 | [令和2年度 各会計歳入歳出決算書（3） （PDF 3.1 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/929/020373.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2020 | [令和2年度特別会計歳出（当初予算）（下水道事業会計除く）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/885/r2saisyututokubetukaikei.csv) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2020 | [令和2年度 各会計歳入歳出決算書（5） （PDF 2.4 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/929/0205120.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2020 | [令和2年度 各会計歳入歳出決算書（2） （PDF 2.0 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/929/0202.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2020 | [令和2年度 各会計歳入歳出決算書（7） （PDF 3.0 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/929/0207180.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2020 | [令和2年度 各会計歳入歳出決算書（8） （PDF 1.6 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/929/0208200.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2020 | [令和2年度 各会計歳入歳出決算書（9） （PDF 3.5 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/929/0209230.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2020 | [令和2年度 各会計歳入歳出決算書（6） （PDF 3.1 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/929/0206150.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2020 | [令和2年度 各会計歳入歳出決算書（4） （PDF 3.1 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/929/020499.pdf) | account_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2020 | [令和2年度一般会計歳出（当初予算）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/885/r2saisyutuippannkaikei.csv) | expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2020 | [令和2年度一般会計歳入（当初予算）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/885/r2sainyuuippannkaikei.csv) | expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2021 | [令和3年度 各会計歳入歳出決算書 （PDF 3.4 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/929/r3.pdf) | moku_or_project_detail_not_observed |
| 多摩市 | 2021 | [歳入構造の分析（自主財源と依存財源） （CSV 4.6 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/885/R6.09sainyuukouzoou.csv) | account_unconfirmed, expenditure_direction_unconfirmed |
| 多摩市 | 2021 | [令和3年度多摩市下水道事業会計決算書](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/002/458/r3kessann.pdf) | account_unconfirmed, expenditure_direction_unconfirmed |
| 多摩市 | 2021 | [歳入構造の分析（歳入構造の指標） （CSV 3.2 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/885/R6.08sainyuukouzou.csv) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2021 | [東京都多摩ニュータウン住宅建設対策補助金の影響額 （CSV 3.5 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/885/R6.12newtownhozyo.csv) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2021 | [令和3年度下水道事業の決算の状況](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/002/458/r3kessanngaiyou.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2022 | [令和4年度 予算の編成状況 （PDF 250.4 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/906/r4henseisaisyuu.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2022 | [令和4年度 一般会計予算書 1（歳出-民生費まで） （PDF 2.2 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/897/0401_ippan_p1-287.pdf) | detail_observation_only_in_contents |
| 多摩市 | 2022 | [令和4年度 各会計歳入歳出決算書 （PDF 3.7 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/929/R4kessann.pdf) | moku_or_project_detail_not_observed |
| 多摩市 | 2022 | [第70号議案（令和4年度下水道事業会計決算） （PDF 8.9 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/012/871/0503teirei_sicho70.pdf) | account_unconfirmed, expenditure_direction_unconfirmed |
| 多摩市 | 2022 | [第66号議案から第69号議案まで（令和4年度一般会計・各特別会計決算） （PDF 19.4 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/012/871/0503teirei_sicho66-69.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2023 | [令和5年度 予算の編成状況 （PDF 248.6 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/906/R5-henseijyoukyou.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2023 | [第5号議案（令和5年度一般会計予算） （PDF 2.9 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/010/509/0501teirei_sicyo5.pdf) | detail_observation_only_in_contents |
| 多摩市 | 2023 | [令和5年度 一般会計予算書 （PDF 4.5 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/897/05ippankaikeiyosansyo.pdf) | detail_observation_only_in_contents |
| 多摩市 | 2023 | [第68号議案（令和5年度下水道事業会計決算） （PDF 807.7 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/015/727/0603teirei_sicyo02.pdf) | account_unconfirmed, expenditure_direction_unconfirmed |
| 多摩市 | 2023 | [令和5年度 各会計歳入歳出決算書 （PDF 2.9 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/929/R5-kessann.pdf) | moku_or_project_detail_not_observed |
| 多摩市 | 2023 | [第25号議案（令和5年度一般会計補正予算第2号） （PDF 494.1 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/011/713/0516rinji_sicyo25.pdf) | expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2024 | [令和6年度 予算の編成状況 （PDF 247.9 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/906/R6-3gatutsuika-hennseijyoukyo.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2024 | [第8号議案（令和6年度一般会計予算） （PDF 7.8 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/014/321/0601teirei_sicyo8.pdf) | detail_observation_only_in_contents |
| 多摩市 | 2024 | [令和6年度 一般会計予算書 （PDF 7.6 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/897/06ippan.pdf) | detail_observation_only_in_contents |
| 多摩市 | 2024 | [令和6年度 各会計歳入歳出決算書 （PDF 3.3 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/929/R6kessann.pdf) | moku_or_project_detail_not_observed |
| 多摩市 | 2024 | [第63号議案（令和6年度下水道事業会計決算） （PDF 897.4 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/018/381/R7-3teirei_sicyo63.pdf) | account_unconfirmed, expenditure_direction_unconfirmed |
| 多摩市 | 2025 | [第6号議案（令和7年度一般会計予算） （PDF 5.6 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/016/909/R7teirei_sicyo06.pdf) | detail_observation_only_in_contents |
| 多摩市 | 2025 | [令和7年度 一般会計予算書 （PDF 5.6 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/897/07ippan-1.pdf) | detail_observation_only_in_contents |
| 多摩市 | 2025 | [令和7年度 予算の編成状況 （PDF 246.1 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/906/r7henseijoukyou.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2025 | [第70号議案から第73号議案まで（令和7年度一般会計・3特別会計歳入歳出決算） （PDF 19.6 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/021/205/R8-3teirei_sicyo70-73.pdf) | moku_or_project_detail_not_observed |
| 多摩市 | 2025 | [第74号議案（令和7年度下水道事業会計決算） （PDF 3.1 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/021/205/R8-3teirei_sicyo74.pdf) | account_unconfirmed, expenditure_direction_unconfirmed |
| 多摩市 | 2026 | [令和8年度 予算の編成状況 （PDF 128.1 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/906/R8henseijoukyou.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2026 | [第8号議案（令和8年度一般会計予算） （PDF 6.2 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/019/604/R8-1teirei_sicyo8.pdf) | detail_observation_only_in_contents |
| 多摩市 | 2026 | [令和8年度 一般会計予算書 （PDF 6.2 MB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/897/08ippan-1.pdf) | detail_observation_only_in_contents |
| 多摩市 | 2024 | [事業別歳出決算額一覧表（一般会計） （CSV 52.1 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/932/2024saisyutsu.csv) | moku_or_project_detail_not_observed |
| 多摩市 | 2024 | [事業別歳出決算額一覧表（国民健康保険特別会計） （CSV 2.1 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/932/2024kokuhosaisyutsu.csv) | moku_or_project_detail_not_observed |
| 多摩市 | 2024 | [事業別歳出決算額一覧表（介護保険特別会計） （CSV 3.1 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/932/2024kaigosaisyutsu.csv) | moku_or_project_detail_not_observed |
| 多摩市 | 2024 | [事業別歳出決算額一覧表（後期高齢者医療特別会計） （CSV 801 Bytes）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/932/2024koukisaisyutsu.csv) | moku_or_project_detail_not_observed |
| 多摩市 | 2024 | [支出決算額一覧表（下水道事業会計） （CSV 3.0 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/004/932/2024gesuishisyutsu.csv) | moku_or_project_detail_not_observed |
| 多摩市 | 2023 | [事業別歳出決算額一覧表（一般会計） （CSV 32.6 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/016/384/2023ippann4-3.csv) | moku_or_project_detail_not_observed |
| 多摩市 | 2023 | [事業別歳出決算額一覧表（国民健康保険特別会計） （CSV 2.3 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/016/384/2023kokuho7-3.csv) | moku_or_project_detail_not_observed |
| 多摩市 | 2023 | [事業別歳出決算額一覧表（介護保険特別会計） （CSV 3.2 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/016/384/2023kaigo13-3.csv) | moku_or_project_detail_not_observed |
| 多摩市 | 2023 | [事業別歳出決算額一覧表（後期高齢者医療特別会計） （CSV 743 Bytes）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/016/384/2023kouki16-3.csv) | moku_or_project_detail_not_observed |
| 多摩市 | 2023 | [支出決算額一覧表（下水道事業会計） （CSV 82 Bytes）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/016/384/2023gesui10-2.csv) | moku_or_project_detail_not_observed |
| 多摩市 | 2022 | [事業別歳出決算額一覧表（一般会計） （CSV 32.0 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/014/433/4-3.csv) | moku_or_project_detail_not_observed |
| 多摩市 | 2022 | [事業別歳出決算額一覧表（国民健康保険特別会計） （CSV 2.2 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/014/433/7-3.csv) | moku_or_project_detail_not_observed |
| 多摩市 | 2022 | [事業別歳出決算額一覧表（介護保険特別会計） （CSV 2.8 KB）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/014/433/13-3.csv) | moku_or_project_detail_not_observed |
| 多摩市 | 2022 | [事業別歳出決算額一覧表（後期高齢者医療特別会計） （CSV 742 Bytes）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/014/433/16-3.csv) | moku_or_project_detail_not_observed |
| 多摩市 | 2022 | [支出決算額一覧表（下水道事業会計） （CSV 113 Bytes）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/014/433/10-2.csv) | moku_or_project_detail_not_observed |
| 多摩市 | 2022 | [(2)事業別歳出決算額一覧表（一般会計）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/014/433/4-1.pdf) | moku_or_project_detail_not_observed |
| 多摩市 | 2018 | [平成30年度多摩市国民健康保険特別会計決算一覧表 歳出（資料3）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/006/473/3saisyutu.pdf) | moku_or_project_detail_not_observed |
| 多摩市 | 2018 | [平成30年度多摩市国民健康保険特別会計決算一覧表 歳入（資料4）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/006/473/4sainyu.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
| 多摩市 | 2019 | [令和元年度多摩市国民健康保険特別会計決算一覧表 歳出（資料3-2）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/006/464/3-2.pdf) | moku_or_project_detail_not_observed |
| 多摩市 | 2019 | [令和元年度多摩市国民健康保険特別会計決算一覧表 歳入（資料3-1）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/006/464/3-1.pdf) | account_unconfirmed, expenditure_direction_unconfirmed, moku_or_project_detail_not_observed |
