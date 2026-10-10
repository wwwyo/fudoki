# 小金井市 132101 settlement-3 議会費 scan converter

`convert(inputs, destination, options)` は固定原典・凍結 native・書式設定の SHA を照合し、未使用 dir へ Parquet と検算用観測を生成する。OCR の起動・入力の取得・正式 manifest の更新は行わない。

対象は FY2025 `settlement-3.pdf`（SHA `0b1af0ae…` 全文は layout.json の `origin_sha256`）、一般会計・歳出・議会費・物理 1–4 頁だけ。横長 1 頁に左右 2 表（左：科目・予算現額・節／右：支出・繰越・不用・備考）が載る。

- `details.parquet`: 備考の最細費目 75 行 × 50 列。款項目の独立印字金額と事業・節・費目の所属を通常列へ展開する。金額は原典の comma・符号・0 を保持した VARCHAR、原典頁 2 列のみ BIGINT。印字頁 2 列は本冊に印字頁番号がないため全行 NULL。`備考_末端金額` が唯一の加算列。反復した親の額は非加算参照。
- `candidate-observations.json`: 法定節 14 行、款項目の独立統制行 3 行、備考ノード 110（事業 5＋節 30＋末端 75）、歳出合計 control、継続マーカー 3、確認済み空欄、header、marginalia。検算観測は raw へ入れない。
- `bindings.json`: 全 region 観測の native SHA・実観測 ID・原文字・原位置・分類、原典 cell から raw 列/行への対応。
- `headers.json` / `metadata.json` / `receipt.json`: 原見出し、金額の役割・grain・単位・実 schema・SHA・局所訂正と共通辞書照合の結果（本原典では適用 0 件）。

`corrections.json` は OCR 挿入空白だけの局所訂正（comma/digits/符号/0 不変）。原典 SHA・頁・bbox・native SHA・実 ID・before で fail closed にする。括弧の開き記号の欠落・`C` 誤読は bbox で除外し、名称末尾の開き括弧だけを除去する parse 規則（原文は bindings に保持）として扱う。

`build_layout.py` は凍結 native から `layout.json` と `corrections.json` を導出する凍結生成器である。期待件数（統制 3＋法定節 14、事業 5・節 30・末端 75）に合わなければ停止する。生成物は SHA で固定し、converter は layout の bbox を宣言として厳密に検査する。

再生例（repo root。出力 dir は未使用であること）：

```sh
mise exec -- uv run --frozen python pipeline/ingestion/fiscal/jurisdictions/132101/layouts/scan_settlement/convert.py \
  --inputs pipeline/ingestion/fiscal/observations/scan-2025-devin-max-2026-10-09/132101/general/settlement-3/candidate-001/inputs-001.json \
  --options pipeline/ingestion/fiscal/observations/scan-2025-devin-max-2026-10-09/132101/general/settlement-3/candidate-001/options-001.json \
  --output pipeline/ingestion/fiscal/observations/scan-2025-devin-max-2026-10-09/132101/general/settlement-3/candidate-001/output
```

候補の原典照合と受容は独立 operator が行い、構築側の合計一致・再生一致はその代わりにならない。
