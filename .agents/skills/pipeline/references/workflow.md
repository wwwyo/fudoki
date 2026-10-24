# 出典選定から取り込み・提供用データまで

## フローを出典の形式で分ける

取り込みのフローは、出典選定・保存 → 形式別の取り込みと検査 → 取り込み表・管理情報の保存まで。dbt側は保存済みParquetと管理情報を読み、入力準備・モデル構築を行う。

| 出典の形式 | 取り込み完了の条件 | 実装の状態 |
| --- | --- | --- |
| ヘッダー付きCSV | 出典を読み直した全セル・列・行順・重複・空欄・物理行範囲がParquetと一致する | 共通CSV変換で自動検査。不一致は保存前に停止する |
| text PDF | 文字保持・出典との対応を確認し、ノードの表・金額の表にして全段の木の検査（印字された親＝子の値の和）と印字された数字の網羅の検査→不一致の修正→再検査を行う | 木の検査（`ingestion/lib/tree_checks.py`）・網羅の検査（`ingestion/lib/coverage_checks.py`）・単位の確かめ（`ingestion/fiscal/unit_checks.py`）は共通処理で、保存の前に必須（通らない表は保存しない）。比べる金額の段階は `pipeline/shared/fiscal_amount_map.csv` |
| scan PDF | OCRの観測と表への対応を確認し、text PDFと同じ木の検査→不一致の修正→再検査を行う | OCR・再読の手順はある。木の検査と保存前の停止はtext PDFと同じ |

取り込みと形式別の検査は [ingestion](ingestion.md) を読む。

## 保存と採用の境界

- 変換と保存の入口は `ingestion:convert`。ローカル実行は候補Parquet・候補manifest・形式別の検査結果を返し、`--remote` は全表の保存成功後に対象別JSONを更新する。手順は [ingestion](ingestion.md#管理jsonを確認して変換する)。
- `ingestion:check` は管理情報・選定・scope・fingerprintの検査で、財政値の正しさを認定しない。fingerprintが古いときは `ingestion:refresh --remote` が再変換して保存済みの表と中身を比べ、同じなら指紋だけを書き換える（違えば `ingestion:convert --remote`。手順は [ingestion](ingestion.md#指紋が古くなったとき)）。refresh は Jev の答え（`*.digit-recheck.jsonl`）を読むだけで、問い直しも書き込みもしない。答えの無い数字がある表は `blocked` になるので、その表は `ingestion:convert`（ローカルの候補でもよい）で答えを記録してから refresh をやり直す。dry-run でも commit 対象のファイルは変わらない。PDF表の木と印字された数字の網羅は保存時に必ず検査され、`ingestion:verify` で保存済み・候補の表に当て直せる（網羅の再検査は候補の scope 付きのみ）。
- 出典はsource_selection、表は対象・方向別のingestion領域に保存し、保存先と出典参照は対象別JSONに置く。独立したprovenanceファイルは作らない。
- C（dbt）は対象別JSONと保存済みParquetを読む。入口は `dbt:build`（[dbt](dbt.md)）。

## 重い実行の判定と待ち合わせ

OCR（8コアを使い切り80分以上）・全表の変換・`ingestion:refresh --remote` は重い。`refresh` は stale な表を `convert` と同じ処理で作り直すので、`convert` と同じ扱いにする。`ingestion:convert`・`ingestion:refresh`・`ingestion:ocr` は起動時に `ingestion/lib/heavy_lock.py` で判定する（待たずに即終了）。
- `ocr` は排他。ほかの OCR も、`convert`/`refresh` も走っていないときだけ起動できる（逆に `convert`/`refresh` は OCR が走っていても起動できる）。
- `convert`/`refresh` は合わせて2本まで（`MAX_CONCURRENT`）。ほかの重い実行が走っているときは、カーネルのメモリ圧力（`kern.memorystatus_vm_pressure_level`）が 1（normal）のときだけ起動できる。1本だけのときは圧力を見ない。閾値は `MAX_PRESSURE_LEVEL` の1箇所。swap の使用量は圧力が引いても残り、macOS の「空き」はカーネルの判断と一致しないので、どちらも判断に使わない。サンドボックスでは sysctl が読めないため、ほかの実行があると「メモリ圧力: unreadable」で断られる — 重い実行はサンドボックスの外から起動する。サンドボックスと外側では `TMPDIR` が別の値になるので、`$TMPDIR` に退避したファイルは外側の実行から見えない（2026-10-22 実測）。退避と受け渡しは worktree 内の相対パスに置く。測定の生データ・比較 script も worktree 内の `.agent/`（gitignore）へ置く — `.cache/` やサンドボックスの scratchpad に置いた観測は worktree を消すと残らず、ADR に書いた計測を後から検算できない（ADR 0033 の所要時間は生データを失った）。
- 同じ管理 JSON を書く実行は、種類を問わず同時に1本だけ（`same target`）。ほかの実行が同じ管理 JSON の保存済み表と指紋を上書きして、登録と R2 の実体が食い違うため。`refresh` を `--manifest` なしで流すと全管理 JSON を押さえる。
- 断られると保持者の PID・command・cwd と理由（`OCR exclusion` / `concurrency limit` / `same target` / `memory pressure`）を出して終了するので、出力の完了を待ってからやり直す。
- ロックは `flock` で、経路は `FUDOKI_HEAVY_LOCK`、無ければ `$XDG_STATE_HOME/fudoki/heavy.lock`、どちらも無ければ `~/.local/state/fudoki/heavy.lock`（環境変数は実行時に読む）。OCR は `heavy.lock`、`convert`/`refresh` は同じ場所の `heavy.lock.slot.<0|1>`、対象ごとに `heavy.lock.target.<ハッシュ>` を持つ。プロセスが死ねばカーネルが解放する。

ロックファイルを消したり作り直したりしない — 以前の `/tmp` のマーカーファイルは、ロックを取っていない実行が他の実行のマーカーを消し、`rm -rf` で解除できる規約だったため同日に2回破られた（2026-10-19）。エージェントのサンドボックスでは `ps` が `operation not permitted` で終わり、待ち合わせが静かに空振りする（1.5時間以上を消費した実測がある）。プロセスの確認はサンドボックス外の `pgrep -fl "[p]attern"`（`[p]attern` で自分のシェルへの一致を避ける）で行い、終了はバックグラウンド task の完了通知か出力ファイルで判定する。`sleep N` は遮断されるので、待つときは Monitor の until-loop を1本だけ張って id を state に持つ。Monitor は30分で expire するので、expire を「実行が止まった」と取り違えない。

## 後段で確認すること

年度・会計・単位・金額段階の解釈、staging、単位換算・分類・集約は [dbt](dbt.md) で確認する。取り込みの保存成功と後段の構築成功を分ける。収録漏れは、source_selection の選定済みscopeと取り込みの宣言（`<方向>.json`）の有無を突き合わせて確認する。

網羅の照合は同じ出典・物理頁を読む全表を集めて行い、木の検査は各表に行う。非採用の表・ブロックの頁・矩形は観測用の読み分けから実行時に生成し、種類と理由だけを人が宣言する。金額帯の未網羅は停止したままにする。詳細は [取り込みの手順](ingestion.md)。

流用・充用・不用額などの金額の注記は、原文・金額・単位・位置をノードと金額の表に保持する。種類は `pipeline/shared/fiscal_annotation_map.csv` で解き、金額の段階は付けない。木の親子合計と歳出のintermediateへ足さず、stagingには残す。基準額は印字された月額セルと同じ括弧内の「1回…円」の金額に限定する。判断は [ADR 0024](../../../../docs/adr/0024-monetary-annotations-without-phase.md)。
