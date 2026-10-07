# G. 提供先と全公開範囲を通常監査で確認する

## 入力と作業

- 原典一覧・スキーマ、現行の固定入力一覧と宣言、全量buildのDB・manifest・CSV・検証記録を使う。
- 次の通常監査を実行して、現行コード・入力に対応するbuild、実CSVのSHA、datasetの提供先、原典行との対応、探索・対象集合の不足を確認する。

```bash
bun run --cwd pipeline coverage:fiscal --json
bun run --cwd pipeline coverage:fiscal --json --require-complete
bun run pipeline:report
```

## 完了判定と終了コード

- `coverage_audit.py` の `checked_datasets()` は現在の構築IDとDB・最新buildの対応、CSV集合と実ハッシュを照合する。過去のbuildを現在の入力の証拠にしない。
- `build_state=verified_current_build` は現行buildを照合できたことを表す。採用datasetの提供先・固定入力の対応・全公開範囲の不足は、同じ監査の別項目で確認する。
- `--require-complete` を付けない監査の終了コード0は、監査を実行できたことを表す。`complete=false` でも0を返すので、完了とは読み替えない。
- `--require-complete` は全対象が未完了なら2、監査自体のエラーは1を返す。2は個別の抽出失敗とは限らず、未収録・未検証・探索不足が残る場合にも返す。
- `--limit` は不足の表示件数だけを変える。完了判定の母集団を絞らない。
- source gap・search gap・boundary gap・population gapは原典レコードや探索・対象集合の不足で、残る実装タスク数とは別である。
- 事業×節の対応を確認できない原典は、その根拠と例外を照合する。候補表があるだけで深い粒度まで取得したと認定しない。

## 保存するものと戻る工程

- 検証報告は `pipeline/.build/report/`、監査の詳細な出力は作業別の検査記録へ保存する。原典の確認結果・不足をcoverageと団体ノートへ反映する。
- 系統は `pipeline/.build/dbt/manifest.json` から生成する。ノード・辺を手書きして現行モデルの図としない。
- 提供先・登録・列・行の不備はB・C・Fへ、原典・版・探索範囲の不足はAへ戻る。古いbuildの場合はFの現行構築を確認する。
- 採用分の構築・照合が通った場合、その対象範囲を受け入れる。全公開年度・全会計・全補正号・要求粒度の完了は、別に原典一覧と探索境界を照合して判断する。

## 現行の参照先

- 監査実装は `pipeline/ingestion/fiscal/coverage_audit.py` と資料別の `*_coverage.py`、報告生成は `pipeline/verify/report/fiscal/build.ts` を参照する。
- 全対象の受入条件は [全年度収録のPRD](../../../../docs/prd/fiscal-coverage/prd.md) を参照する。

## 既存の収録範囲報告で実測した注意点

- ⚠️ **団体で畳んだ割合は、年度の主張には使えない。** 報告は長く団体単位の集計しか持たず、
  COFOG の割当率も名称の充足も全年度の合算だった。名称の載った資料が一部の年度にしか無い団体では
  合算が実態から離れる（ある団体は科目名も事業名も無い年度と、9割に付く年度が同じ数字に潰れていた）。
  **原典が年度で割れる以上、収録範囲は年度ごとにしか正しく書けない**ので、
  報告は (年度, direction) を軸にした収録状況を別に持つ（`pipeline/verify/report/fiscal/build.ts` の `buildCoverage`）。
  ⚠️ **分母は指標ごとに違う。** 名称は行数、COFOG の到達は割当済みの金額、
  事業名は大事業の異なり数で、混ぜると別の数字になる。
  事業名は**出所が覆う範囲**（決算書 PDF は一般会計だけ）も併記して、
  「出所が届いていない」と「届いているが当たらなかった」を分ける
