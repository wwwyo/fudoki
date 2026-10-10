# E. 既存入力の復元・検査（旧検査・監査の互換経路）

旧検査・監査は、schemaVersion 3の `pipeline/ingestion/fiscal/sources.lock.json` を参照する。この文書は、その一覧が指す既存入力の復元と同一性検査を説明する。新規保存はBの対象別JSONと `ingestion:convert` に一本化し、[取り込みと保存](ingestion.md#現在版の保存・差し替え) を使う。

## 残っている参照と検査

- 旧入力一覧は、原典・ParquetのSHA・サイズ・保存先と、旧検査・監査が読む原典宣言を保持する。独立した `provenance.json` は生成・復元しない。
- `inputs/origin/sha256/<SHA>` と `inputs/table/sha256/<SHA>` は、旧一覧が参照する既存の非公開R2オブジェクトのkeyである。新しいBの保存先ではない。旧一覧の `read_lock()` はこのkey形式を要求するため、新keyへ参照文字列を替えるだけでは移行できない。
- `pipeline/ingestion/inputs.py` の `read_lock()` が旧一覧の構造・対象・保存参照を検査し、`verify_object()` が実バイト列のSHA・サイズを照合する。`source_metadata()` は固定Parquetを読み、行数・列型等を取得する。検査結果は必要時に再生成し、原典宣言へ写して正しさの証明と扱わない。
- `locked_objects()` は、旧一覧と既存の専用処理が参照する補助証拠を列挙する。原典画像・凍結OCR観測等の必要な補助入力を、provenanceの別ファイルがないことを理由に捨てない。
- ローカルオブジェクトキャッシュは `pipeline/.cache/objects/`。復元時も実ファイルのSHA・サイズを照合する。キャッシュの存在だけではR2から取得し直した証拠にはならない。

## 旧入力を読む検査の準備

旧一覧に依存する検査を実行する場合だけ、`pipeline/` から既存一覧を指定して復元する。

```bash
mise exec -- uv run --frozen python -m ingestion.inputs restore --lock ingestion/fiscal/sources.lock.json
mise exec -- uv run --frozen python -m ingestion.inputs describe --lock ingestion/fiscal/sources.lock.json
```

ローカルに必要な既存オブジェクトがなければ、復元の `restore` に `--remote` を付ける。`restore()` は既存参照を `remote_object(..., 'get')` で取得し、SHA・サイズを照合する。復元・検査は旧一覧の採用更新や新規保存を行わない。取得・復元の一致はバイト列の同一性であり、原典の意味や財政値の正しさの判定とは分ける。

## 現行の保存・後段との境界

新規の取り込み表は `ingestion/fiscal/jurisdictions/<団体>/<年度>/<資料区分>/<方向>.json` と `ingestion:convert` で管理・保存する。原典はsource_selectionの保存参照を使う。旧keyへのアップロードと旧入力一覧への採用更新を、新しいBの手順に含めない。

現在の `bun run pipeline:inputs` とFの入力準備は、対象別JSONと保存済みParquetを読む。旧一覧をFへ新しい入力として渡す手順ではない。現行入口は [pipeline/README.md](../../../../pipeline/README.md)、後段は [F](dbt.md) を参照する。

旧検査・通常監査Gの入口変更と、既存Parquetの保存先移行は別の作業である。旧一覧を参照するconsumerが残る間は、そのconsumerに必要な既存keyの保持と復元を続ける。移行・削除の確認範囲は [移行記録](../../../../docs/prd/ingestion-storage/migration.md) を参照する。
