# C. dbt側で保存済み取り込みJSONとParquetを読み、構築する

## 入力を確認する

1. `ingestion/fiscal/jurisdictions/<団体>/<年度>/<資料区分>/<方向>.json` を読み、そこで参照される保存済みParquetをdbt側で読み込む。別の宣言ディレクトリやdbt用JSONの提出は要求しない。未検査のPDFを保存状態だけで検査済みと扱わない。
2. `dbt:inputs:check` で `pipeline/dbt/inputs/` の表ID・配置対応を検査する。`ingestion:check` で対象・原典選定・scope・fingerprintを検査する。
3. 原典の抽出やBの検査は再実行しない。単位・金額段階・階層・独立内訳などの確認済み出力情報と、対象に必要なモデルが揃っていることを確認する。stagingの定義・限定検証は下の [stagingを定義する](#stagingを定義する) を使う。不足を推定値・空表で補わない。削除範囲と未完了項目は [保存設計](../../../../docs/prd/ingestion-storage/design-doc.md) と [移行記録](../../../../docs/prd/ingestion-storage/migration.md) を参照する。

## 入力を固定する

```bash
bun run pipeline:inputs
```

入力準備だけの確認は `pipeline/` で実行する。

```bash
uv run python -m build_inputs prepare --manifest <対象JSON>
```

- `pipeline:inputs` は管理JSONから保存済みParquetを復元する。
- `build_inputs prepare` はネットワークを使わず、管理JSON全体・解決済み原典情報・C側の配置対応・Parquetを `.cache/inputs/<入力fingerprint>/` に固定する。件数とファイルパスだけをcontextへ返す。表のSHA・サイズ、再利用するsnapshot、準備中の管理情報変更を検査する。
- `bun run pipeline:build` で残ったモデルを構築する。旧宣言JSONを読むモデルと依存先は削除済みで、旧JSONの存在を要求して停止しない。単位・金額段階・階層は必要なモデルの設定で扱い、Bへdbt専用の別ファイルの出力を要求しない。旧構成の全CSVの再生成や公開全年度の収録完了とは区別する。
- `--manifest` は入力範囲を指定する。dbtモデルの実行範囲は自動で絞らない。
- 同じ構築IDのCSVハッシュを照合し、初回成功だけで再構築一致を検査済みと扱わない。

## 構築結果を確認する

- 直前の採用buildとの差分、対象範囲、dbtの結果、実CSVハッシュ、再構築一致、未確認事項を記録する。入力準備・構文検査・限定実行・全量構築を区別する。
- 保存参照・コード・宣言・判断はGitで管理する。キャッシュ・catalog・DB・CSV・検査結果は再生成するローカル領域に置く。
- 検証報告には旧入力一覧を使う経路が残る。構築成功を全公開資料の収録完了と扱わない。[移行記録](../../../../docs/prd/ingestion-storage/migration.md) を確認する。
- 実装は `pipeline/build_inputs.py`・`build.ts`・`identity.ts`。構築・整形・分類の過去の実測は [dbtの注意点](../../../../docs/survey/dbt-transform-notes.md) を参照する。
- raw → staging → intermediate → marts → CSVの値と単位、原典行の対応、欠落・二重収録、集約を確認する。stagingの行数一致だけで全値一致としない。単位・金額段階の根拠は原典から取り、宣言どうしの一致だけで済ませない。

## stagingを定義する

1. 対象の管理JSONと、SHA・サイズを照合したParquetを読む。列・値はParquet、単位・粒度・列の所属は `tables[].metadata`、対象と原典情報は管理JSON・selectionから確認する。通常はこの入力だけで定義し、意味が不足する場合だけ原典に戻る。
2. 原典の明細・予備費充用・貸付金状況・検算用合計は、それぞれの役割を保ってstagingする。文字観測など調査だけに使う表は用途を確認して対象を決め、全表を歳出明細へ混ぜない。
3. `pipeline/dbt/models/staging/fiscal/` にsourceと薄いSQLを置く。書式・役割が同じ表は年度・会計ごとにSQLを複製せず、対象を区別して `union all` で扱う。原典行と1対1を保ち、単位換算・結合による名寄せ・集約・共通分類は後段に置く。
4. 原文へ戻れる対応を保持し、利用する文字列は必ず共通の `trim_cell`、金額は `staging_amount` を通す。NFKC・前後trimを既定とし、個別SQLへ変換を複製しない。金額は原文列を残して数値列を追加する。変換できない値を黙ってNULLや0にしない。
5. 管理JSONから入力を固定し、対象モデルだけを構築・検査する。入力固定は上の [入力を固定する](#入力を固定する) を使う。`--manifest` は入力だけを絞るので、dbtにも `--select <モデル>` を指定する。別の検証用DB・targetを使い、通常の構築結果を上書きしない。
6. 入力と出力の行の対応、重複を含む原文値の一致、識別情報、数値の型・単位を確認する。反復された親の金額を合計せず、原典で確認された粒度で照合する。
7. チャットでモデルの場所、実行範囲、変換前後の例と実施した変換を短く伝える。コードから読める処理を別の説明表や文書へ重ねない。入力条件不一致やSHA不一致で通常の準備が止まった場合は、限定検証と正式な構築成功を区別する。

stagingされた表をすべて配布・集計する必要はない。後段のconsumerと検査が、表ごとの役割を使い分ける。
