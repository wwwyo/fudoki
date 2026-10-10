# F. dbt側で保存済み取り込みJSONとParquetを読み、構築する

## 入力を確認する

1. `ingestion/fiscal/jurisdictions/<団体>/<年度>/<資料区分>/<方向>.json` を読み、そこで参照される保存済みParquetをdbt側で読み込む。別の宣言ディレクトリやdbt用JSONの提出は要求しない。未検査のPDFを保存状態だけで検査済みと扱わない。
2. `dbt:inputs:check` で `pipeline/dbt/inputs/` の表ID・配置対応を検査する。`ingestion:check` で対象・原典選定・scope・fingerprintを検査する。
3. 原典の抽出やCの検査は再実行しない。単位・金額段階・階層・独立内訳などの確認済み出力情報と、対象に必要なモデルが揃っていることを確認する。stagingの定義・限定検証は [staging手順](staging.md) を使う。不足を推定値・空表で補わない。削除範囲と未完了項目は [保存設計](../../../../docs/prd/ingestion-storage/design-doc.md) と [移行記録](../../../../docs/prd/ingestion-storage/migration.md) を参照する。

## 入力を固定する

```bash
bun run pipeline:inputs
```

入力準備だけの確認は `pipeline/` で実行する。

```bash
uv run python -m build_inputs prepare --manifest <対象JSON>
```

- `pipeline:inputs` は管理JSONから保存済みParquetを復元する。
- `build_inputs prepare` はネットワークを使わず、管理JSON全体・解決済み原典情報・F側の配置対応・Parquetを `.cache/inputs/<入力fingerprint>/` に固定する。件数とファイルパスだけをcontextへ返す。表のSHA・サイズ、再利用するsnapshot、準備中の管理情報変更を検査する。
- `bun run pipeline:build` で残ったモデルを構築する。旧宣言JSONを読むモデルと依存先は削除済みで、旧JSONの存在を要求して停止しない。単位・金額段階・階層は必要なモデルの設定で扱い、Cへdbt専用の別ファイルの出力を要求しない。旧構成の全CSVの再生成や公開全年度の収録完了とは区別する。
- `--manifest` は入力範囲を指定する。dbtモデルの実行範囲は自動で絞らない。
- 同じ構築IDのCSVハッシュを照合し、初回成功だけで再構築一致を検査済みと扱わない。

## 構築結果を確認する

- 直前の採用buildとの差分、対象範囲、dbtの結果、実CSVハッシュ、再構築一致、未確認事項を記録する。入力準備・構文検査・限定実行・全量構築を区別する。
- 保存参照・コード・宣言・判断はGitで管理する。キャッシュ・catalog・DB・CSV・検査結果は再生成するローカル領域に置く。
- 通常監査G・検証報告には旧入力一覧を使う経路が残る。新しいFの成功だけでGの移行・全公開資料の収録完了を宣言しない。[移行記録](../../../../docs/prd/ingestion-storage/migration.md) と [通常監査](coverage-audit.md) を確認する。
- 実装は `pipeline/build_inputs.py`・`build.ts`・`identity.ts`。操作の詳細は [pipeline/README.md](../../../../pipeline/README.md)、構築・整形・分類の過去の実測は [dbtの注意点](../../../../docs/survey/dbt-transform-notes.md) を参照する。
