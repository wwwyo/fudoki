# F. 保存済み取り込み表と確定済み宣言からdbtを構築する

## 入力を確認する

1. 保存済みの対象別JSONと、確定済み宣言のディレクトリを受け取る。宣言は `sources.json`（出典・意味）と `history.json`（予算履歴）で、どちらもdbt用の行配列である。履歴がなければ空配列を渡す。未検査のPDFを保存状態だけで採用済みと扱わない。
2. `dbt:inputs:check` で `pipeline/dbt/inputs/` の表ID・配置・意味の対応JSONを検査する。型は `bindings.schema.json` を使う。dbt用の情報を取り込みJSONへ追加しない。
3. `ingestion:check` で対象別JSON・原典選定・scope・fingerprintを検査する。F入口では宣言の団体・年度・方向・資料種類と、その範囲の原典または表のSHA集合への所属を検査する。補正号・会計・個別表との1対1対応の認定とは区別する。
4. 対象に必要なstaging・intermediate・marts・CSVのモデルと宣言を揃える。既存モデルが要求する補助表を欠く場合は停止し、空表・推定値で補わない。受け渡し契約と移行境界は [保存設計](../../../../docs/prd/ingestion-storage/design-doc.md) を参照する。

## 入力を復元して構築する

rootから実行する。`DECLARATIONS` は受け取った宣言ディレクトリの絶対パスを指定する。`FUDOKI_INPUT_DECLARATIONS_DIR` でも指定できる。Cからこのディレクトリへの宣言出力接続は未完了なので、確定済みJSONが用意されたことを確認してから構築する。

```bash
bun run pipeline:inputs
bun run pipeline:build --declarations "$DECLARATIONS"
bun run pipeline:build --declarations "$DECLARATIONS" --rebuild
```

- `pipeline:inputs` は新しい対象別JSONから保存済みParquetだけを復元する。原典・OCR・補助証拠の復元やCの再実行は行わない。
- `pipeline:build` はネットワークを使わず、Parquetと受け取ったJSONを `.cache/inputs/<入力fingerprint>/` に固定してdbtの変換・検査とmarts CSV生成を実行する。復元が不足していれば先に `pipeline:inputs` を実行する。
- 構築入力fingerprintは対象別JSON・F側の入力対応JSON・受け取った宣言JSONの内容から作る。F側の変更を取り込みfingerprintへ混ぜない。表のSHA・サイズ、宣言との対応、入力準備中の参照変更を検査する。再利用するローカルsnapshotも内容を照合する。
- 入力を絞る場合は `pipeline:inputs` と `pipeline:build` の両方に同じ `--manifest <対象JSON>` を繰り返して渡す。この指定は入力範囲であり、dbtモデルの選択を自動で絞る指定ではない。全量モデルが必要な表を欠く範囲では実行しない。
- `.build/workspace/`・warehouse・dbt targetを作り直し、成功結果を `.build/builds/<構築ID>/` に保存する。CSV一覧とSHAは `verification.json`、入力catalogとDBとの対応は `latest.json`・`warehouse.json` に記録する。
- 同じ構築IDがあれば保存済みCSVを照合し、再生成CSVのハッシュも比較する。初回成功だけでは再構築一致を検査済みにせず、`determinismChecked` を確認する。

## 結果を確認して後段へ渡す

- 直前の採用buildとの差分、対象範囲、dbtの結果、実CSVハッシュ、再構築一致、未確認事項を記録する。入力準備・構文検査・限定実行・全量構築を区別する。
- 保存参照・コード・宣言・判断はGitで管理する。キャッシュ・catalog・DB・CSV・検査結果は再生成するローカル領域に置く。
- 通常監査G・検証報告には旧入力一覧を使う経路が残る。新しいFの成功だけでGの移行・全公開資料の収録完了を宣言しない。[移行記録](../../../../docs/prd/ingestion-storage/migration.md) と [通常監査](coverage-audit.md) を確認する。
- 実装は `pipeline/build_inputs.py`・`build.ts`・`identity.ts`。操作の詳細は [pipeline/README.md](../../../../pipeline/README.md)、構築・整形・分類の過去の実測は [dbtの注意点](../../../../docs/survey/dbt-transform-notes.md) を参照する。
