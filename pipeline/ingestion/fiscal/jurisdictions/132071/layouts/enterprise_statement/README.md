# 昭島の企業会計決算書

`convert.py` は昭島の罫線付き企業会計決算報告書・歳出明細書の測定済み書式を読む。年度は管理JSON、頁はoptionsから受け取り、年度ごとのコードを複製しない。2025下水道事業会計の物理4–7、24–28、30–31頁で構築を確認した。他の会計・書式への適用は未検証。

pipelineをcwdにし、通常の `ingestion:check --manifest <対象JSON>` と `ingestion:convert --manifest <対象JSON> --inputs <SHAとローカルパスのJSON> --output <未使用候補dir>` を実行する。原典はsource_selectionの保存済みPDFをSHA照合して復元する。

出力表IDは `table_prefix` に `-revenue-report`、`-capital-report`、`-revenue-detail`、`-capital-detail` を付ける。表の税区分・単位・反復する親金額の粒度はmetadataに持たせる。税抜の明細と税込の報告、予算額と決算額を同じ金額列へ混ぜない。

## 組版と出力

`pdftotext -bbox-layout` の単語を読み、`pdftocairo -svg` が出すページ直下の罫線矩形から金額欄の行境界を取る。共通 `ingestion.lib.pdf_table` のrow bandsと列への割当を使い、見開き報告は左右の横罫線が一致することを確認して対応するセルを組み立てる。収入欄の行は出力しない。

報告は項を一行とし、款の原典値を `区分_款_` 補助列へ反復する。明細は款→項→目→節→備考内訳の最細粒度を一行とし、備考内訳がない節は節で一行とする。備考の `予算額` は独立した `備考_予算額` に保持する。備考が同じ節の内訳であることは罫線で囲まれたセルの所属を根拠とし、隣り合う独立した欄をy位置だけで結合しない。

文字は行内x順、折り返しはy順で復元する。中央配置された款・項・目番号は同じセルの名称より前に置く。通常の単語を文字へ分割しない。Popplerが続き頁の目/節境界を跨いで一単語にする `費修` / `費補` の二字だけ、罫線と字形の大きさで分ける。この条件に一致しない跨ぎ単語、欠落金額、不明な備考行、継続目の相違、報告の行・ヘッダー相違は停止する。

単位・注記はmetadata、物理頁と印刷頁は別列、セル位置は表示頁上端左を原点とするpointで保持する。空の備考・予算欄はNULL、印字された0は文字列 `0`。

候補dirの `enterprise-observations/` に各頁のbbox XML、SVG、元単語JSON、表別構築観測JSONを出す。元単語には境界分割前の文字を保持する。ローカル検査用であり正式R2の取り込み表や別provenanceファイルにしない。親agentは独立に原典と保存済みParquetを読み、文字・所属と階層合計を検査する。変換器の成功は独立検査の合格を意味しない。

## 構築と独立検査のコマンド例

以下はpipelineをcwdとする。`candidate-new`、`origin-new`、`check-new` は毎回未使用のディレクトリを指定する。入力JSONは原典SHAから絶対ローカルPDFパスへのオブジェクトを持つ。

```sh
mise exec -- bun run ingestion:convert \
  --manifest ingestion/fiscal/jurisdictions/132071/2025/settlement/expenditure.json \
  --inputs ../.agent/2025-text-pdf-ingestion/001-akishima-sewer-settlement/inputs.json \
  --output .cache/ingestion/candidate-new
mise exec -- uv run python -m ingestion.fiscal.jurisdictions.132071.layouts.enterprise_statement.inspect_origin \
  --pdf .cache/objects/fiscal/source-selection/132071/2025/settlement.pdf \
  --out ../.agent/2025-text-pdf-ingestion/001-akishima-sewer-settlement/origin-new
mise exec -- uv run python -m ingestion.fiscal.jurisdictions.132071.layouts.enterprise_statement.validate_candidate \
  --pdf .cache/objects/fiscal/source-selection/132071/2025/settlement.pdf \
  --origin ../.agent/2025-text-pdf-ingestion/001-akishima-sewer-settlement/origin-new/origin.json \
  --manifest .cache/ingestion/candidate-new/manifest.json \
  --candidate .cache/ingestion/candidate-new \
  --out ../.agent/2025-text-pdf-ingestion/001-akishima-sewer-settlement/check-new
mise exec -- uv run python -m unittest ingestion.fiscal.jurisdictions.132071.layouts.enterprise_statement.convert_test
```

独立観測は `pdftohtml -xml` から文字ブロックを取得し、構築器や共通表組み立てmoduleをimportしない。検査は保存済みParquetのscalar列・原典文字・所属、反復親金額の一致と階層別合計を確認する。不一致・保留があれば非ゼロ終了し、全結果を `checks.json` に残す。検算不可は理由を残す。2025の候補検査では文字・所属1728セル、金額109比較が一致し、不一致・保留0。備考内訳がない57節と税込報告↔税抜明細2比較は検算不可。備考予算額18個は文字保持のみで、実績内訳から予算額を検算しない。

出力構造は収益的報告4行40列、資本的報告4行44列、収益的明細88行15列、資本的明細24行15列。明細の15列は款・項・目と各金額、節・金額（円）、備考_予算額・備考_名称・備考_金額、物理頁・印刷頁・原典位置_上端・原典位置_下端。独立検査成功と正式R2保存は別工程である。
