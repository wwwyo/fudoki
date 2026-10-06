# 原典の収録候補一覧（census v1）

`coverage.json` は、対象5団体について公式サイト・公式カタログで発見した財政資料と未確認事項を Git に保存する一覧である。JSON の構造は [coverage.schema.json](coverage.schema.json) に定義する。これは取得宣言でも固定入力一覧でもない。採用は `sources.toml` と `sources.lock.json`、提供用データの検査は現在の構築結果で判定する。

2026-10-04 に確認した有限の探索結果を収録した。公開された全資料を網羅したとは宣言しない。現在の予算ページに古い年度がない場合も、有償刊行物・庁議・記者会見・議会議案・東京都カタログを探し、探索できていない範囲を `jurisdictions[].gaps` に残す。リンクが見つからない、404、画像で読めない、といった事情を「公開なし」やゼロに置き換えない。

## 記録の単位

`sources[]` の1件は、団体・発見したダウンロードURL・掲載年度の組合せである。分冊、概要と予算書、同一内容の別URL、カタログの旧版・新版を別候補として保持する。この件数は自治体の会計数、補正号数、独立した金額表の数ではない。`id` はこの組合せを基に固定した識別子で、採用・検査状態や文書段階の訂正で変更しない。合集は `fiscal_year: null`、`document_phase: mixed` とし、読めた各版を `editions[]` で識別する。

URLの同一性とバイト列の版は分ける。`download_url` は掲載された正確なURL、`content_inspection.final_url` は取得後のURL、`content_inspection.sha256` は今回取得した原典の版である。`landing_url` と `listing_evidence` に掲載ページ・ラベル・周辺見出しを保存し、リンク名が空なら空文字をそのまま残す。`document_title` はラベル又は確認できた表紙の名称である。`inspected_at` はISO日付で、この census の確認日を表す。

`fiscal_year` は会計年度であり、ページの更新年・議会開催年・ダウンロードファイル名の日付ではない。`editions[]` は読めた本文の年度、会計名、文書段階、補正号と根拠ページを持つ。年度のないCSVでは年度・文書段階を公式掲載ラベルで裏付け、会計名はCSVの実際の値で確認したことを `basis` に明記する。CSVの会計コード付き名称は宣言された形式でだけ会計コードと会計ラベルを分け、原典値は `account_labels` と `csv_sample` に残す。三鷹の `prefix2` はdbtの `fiscal_code_style` の宣言で、先頭2桁のみをコードとする。名称に含む残りの数字は保持し、数字の一般的な削除を行わない。PDFで他年度や他会計の比較額を見つけても、独立した当初予算・決算の版には数えない。

## 状態の読み方

| 項目 | 意味 |
| --- | --- |
| 掲載候補 | `listing_evidence` に公式の掲載根拠がある。原典本文の到達性・粒度は未確認でも保持する |
| `content_inspection.status: not_inspected` | 掲載情報だけを確認した。本文を読んだとは扱わない |
| `text_probed` | PDFの全バイトを取得し、文字抽出で表紙・表候補の見出しを採取した。数値、画像併存頁、全会計の全量検査ではない |
| `csv_inspected` | CSVを復号し、見出し、先頭2行、行数、会計列の全行異なり値を確認した。列が全行使われること・金額の意味の検証とは別である |
| `image_only` | PDFは取得できたが、文字抽出で本文を確認できない。画像の視認・OCRが必要 |
| `fetch_or_decode_failed` | 掲載URLの取得・復号に失敗した。資料が存在しないという判断ではない |
| `fixed_inputs[]` | 現在のlockにある採用証跡のURLと対応した、採用済み入力のスナップショット。文書全体の採用とは限らない |
| `fixed_inputs[].current_origin_match` | 今回取得した原典ハッシュと採用版の一致。未取得は `not_checked`、差は `different` |
| `marts.status: not_checked` | この census は現在の提供用データを検査していない。採用だけで `verified` にしない |

`account_scope_status` と `edition_status` は掲載ラベル、内容での確認、未解決を区別する。`content_inspected` は列・見出しで確認できた範囲の意味であり、全会計・全補正号の完全性の宣言ではない。`amendment_numbers` は当該ファイル内で発見した号の便宜的な一覧で、号と会計の対応は `editions[]` を参照する。議案番号・月名・ファイル末尾の数字を補正号として使わない。資料名が「予算」でも、本文が補正なら補正として記録する。

`document_phase` の `initial` / `supplementary` / `settlement` は文書の種類を表す。金額の段階（`approved` / `adjusted` / `executed` など）ではない。予算案・議案、可決後の予算書、専決処分の確認は別途必要である。決算CSVに当初・補正後・執行の列があっても、各補正号の金額が採用されたとは扱わない。

`directions` は本文の方向見出し又はCSVの列・観測値で確認した `expenditure` / `revenue` を列挙する。空配列は未確認である。ファイル名・掲載ラベルだけでは埋めない。概要で両方向が見つかっても、両方向の全明細があるとは意味しない。

`in_scope` は候補の収録対象判定で、原典と現在のPRDを根拠に `included` / `excluded` / `unconfirmed` を保持する。一般会計と特別会計を含み、公営企業会計は現在の対象外である。複数会計のPDFは対象となる会計の版を残す。下水道という名称だけでは企業会計と判定せず、年度ごとの会計名と企業会計の表・法令の記載で裏付ける。対象候補に含むことと、明細の収録完了は別である。

## 粒度と未確認事項

`content_grain.observed_levels` はCSV列やPDFの表候補の抽出文字で観測した語であり、全明細の最深粒度ではない。証拠の位置・表見出し・原典の値は `content_inspection.evidence[]` に保存する。PDFページは1から数えるファイル内ページで、紙面に印字されたページ番号とは区別する。CSVは `page: null` とする。

`content_grain.project_setsu_relation` は `unconfirmed` / `confirmed_explicit` / `independent_breakdowns` を区別し、判断根拠を `relation_evidence` に保存する。`confirmed_explicit` は原典が事業と節を同じ明細で対応付け、当該範囲の検査で確認できた場合に限る。事業別集計と節別集計が別々に載る場合は `independent_breakdowns` であり、原典にない配賦・直積・比例按分で結び付けない。この census の文字・見出しプローブだけでは対応を確定しないため、現時点では `unconfirmed` を保持する。

複数会計の同じPDFで確認できる粒度が異なる場合は、任意の `editions[].content_grain` にその年度・会計・段階の実観測を記録する。その版だけが文書単位の粒度より優先され、他会計の確認根拠には使わない。版の原典ハッシュ・会計・方向の本文確認、実際のphase出力との照合は引き続き必要である。原典に予備費の節欄が空白の会計と、全行で節が印字された会計を同じ状態へまとめない。

`jurisdictions[].search_boundaries` は実際に探索した公式ページとカタログの境界、`gaps` は年度・文書段階・会計別の残件を持つ。`years: []` は特定の年度集合を確定できない境界を表し、残件がないという意味ではない。

| gap status | 判断 |
| --- | --- |
| `search_incomplete` | 探索が完了していない。未発見を未公開とは判定しない |
| `content_unconfirmed` | 資料・版は発見したが、本文・会計範囲・号数・粒度などが未確定 |
| `listed_download_failed` | 掲載された候補の取得に失敗。代替原典を探索する |
| `publisher_declares_unavailable` | 発行者が対象年度・会計・段階の非公開/未作成を明示した場合だけ。根拠URLを必須とする |

現在の census は `publisher_declares_unavailable` を使っていない。予算ページの「直近5年掲載」はそのページの探索境界であり、過去年の公開なしの証明ではない。

## 固定入力との照合と更新

`lock_reconciliation` は照合した `sources.lock.json` の正確なハッシュ、全入力件数、対応した入力パス、未対応パスを保存する。現時点の採用を再計算する際はlockと採用証跡の `request_url` を読んで対応付ける。URLで同じ資料に当たっても版が違う場合は、その違いを解消するまで現在版の採用とは判断しない。`fixed_inputs.scope` の頁・方向・表IDを保持し、補正履歴の二目だけの入力や名称補完用PDFを全会計の金額収録と数えない。

候補を追加するときは、掲載ページ・正確なURL・年度・会計・文書/版の根拠、確認日、確認方法、残件を一緒に追加する。本文を読めた部分だけ状態を進める。全号を発見したと判断する前に、会計ごとの号の連続性・年度末の号・専決処分・訂正版と、索引の掲載期間を確認する。採用や提供用データの状態を更新するときは、現在のlockと構築ID・出力ハッシュ・全量検査の証拠を再確認する。

既存フィールドの意味や必須構造を変更するときは `schema_version` を更新する。候補登録と完了証跡を区別する任意フィールドの追加はv1互換とする。v1の意味の変更は既存フィールドを読み替えず、新しい版として明示する。構造検証にはJSON Schema Draft 2020-12の検証器を使う。

```bash
mise exec -- uv run --directory pipeline --no-sync python - <<'PY'
import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
root = Path('ingestion/fiscal')
schema = json.loads((root / 'coverage.schema.json').read_text())
inventory = json.loads((root / 'coverage.json').read_text())
Draft202012Validator.check_schema(schema)
Draft202012Validator(schema, format_checker=FormatChecker()).validate(inventory)
print('coverage schema: PASS')
PY
```

構造検証は公開資料の完全性や提供用データの正しさを証明しない。現在の採用・martsとの照合は [coverage_audit.py](coverage_audit.py) を参照する。


## 収録完了の判定（v1の任意証跡フィールド）

`coverage_audit.py --require-complete` は、一覧の登録・本文のプローブ・固定入力の採用を完了と数えない。現在の1,015候補はそのまま保持し、以下の証跡が揃うまで `complete: false`、終了コード2を返す。`--help` と `--describe` は倉庫を読まず、後者は候補登録と任意証跡を含むJSON Schemaを返す。通常の照合は読み取り専用である。

- 5団体のすべてに有限の `search_boundaries` が必要で、各境界は `status: inspected` と `completion_proof` を持つ。`inspected` はページを読めた状態であり、探索の完了を意味しない。失敗・未完了・空の境界一覧は、それ自体を完了の阻害要因とする。
- 境界の `completion_proof` は、探索を閉じた根拠 `basis` / `evidence_urls`、列挙した `source_ids`、年度・会計・文書段階ごとの有限な `scopes` を持つ。各scopeは `fiscal_year` / `account_label` / `document_phase` / `amendment_numbers` / `last_amendment_number` / 根拠を記録する。補正は公式の最終号を確認し、1から最終号まで各版の出力が必要である。当初・決算は号一覧を空、最終号をnullとする。単に見つかった最大号を最終号と断定しない。
- 各団体で当初・補正・決算の年度・会計別scopeが確認される必要がある。発行者による非公開宣言は `publisher_declares_unavailable` の根拠URLと具体的年度・会計・文書段階に限って該当scopeを閉じる。`account_scope` はこの場合、scopeの会計ラベルと一致させる。補正が公開されない明示的scopeの最終号は0・号一覧は空とする。年度不明・`phase: all`・URLなしの宣言は完了の根拠にしない。一般的な「過去資料なし」や境界の未発見を代用しない。
- 歳出の各 `editions[]` には、原典の版と一致する `content_confirmation.origin_sha256`、`direction: expenditure`、会計・版・方向それぞれの `*_evidence_indices` が必要である。索引は `content_inspection.evidence[]` の0始まりの位置で、原典本文又はCSVと公式掲載根拠の対応を人が確認して記録する。年度・会計・文書段階・補正号が現在の採用証跡と一致し、対象外判定にも根拠が必要である。
- 通常経路は `content_grain.status: observed`、目・節の観測、空でない `relation_evidence` を要求する。`confirmed_explicit` は実際の提供行にも対応する経路・節が残る場合だけ通る。独立内訳の `independent_breakdowns` は、同じ年度・会計・版の「目×事業」と「目×節」の両方が別のdatasetの検査済み提供表として保持される場合だけ通る。採用された独立side表は、通常の明細用 `int_fiscal_lines` へ入れる必要がなく、下記の直接照合で確認する。同じCSVに含む場合もdatasetによる区別が必要で、両内訳を一つの対応表へ混ぜない。片方の明細と他方の制御合計だけでは通らない。全原典に当該対応又は節が無い場合に限り、下記の公開粒度例外を使用できる。直積や配賦で対応を生成しない。

現在の構築ID、コード・入力の識別、CSV集合と全CSVハッシュを確認してから、実際の `fiscal/<団体>/` CSVを読む。当初は `initial_expenditure_budget.csv` のapprovedに当たる内訳、補正は `expenditure_budget_changes.csv` の原典増減額、決算は `settlement_expenditure.csv` と `settlement_expenditure_setsu.csv` のexecutedに当たる内訳を、datasetごとに照合する。予算対象への参照は `expenditure_budget_items.csv` と照合する。要求される金額段階に全原典行が一度ずつ含まれ、原典行ID・行番号・金額・会計、内訳合計、出力行IDが一致する必要がある。決算の原典行表と集約表は別々に同じ原典行集合を確認し、両表の金額を足さない。proposedだけの当初やexecutedのない決算、対象の二目だけを採用した入力、中間の `int_fiscal_datasets` 登録だけでは完了しない。

`unresolved` の各文字列は残件の識別子としてそのまま残す。任意の `unresolved_resolutions[]` は一件の完全一致する `item` に対して、解消理由 `basis`、今回の `origin_sha256` と現行 `lock_sha256`、この資料の全対象版を検査した `dataset_ids`、解消を裏付ける `evidence_indices` を記録する。粒度・会計・版・方向・実出力など他の条件が一つでも未確認、ハッシュや対象datasetが不一致、原典証拠の索引が無効なら、その残件は解消しない。任意証跡は根拠を人が確認した記録であり、文字列の存在だけで内容の真実を証明するものではない。残件の全削除、martsの状態ラベル、lock採用だけを一括の免除に使わない。年度・段階別の `jurisdictions[].gaps` は別途保持し、本文未確認・探索未完了の状態をこの解消記録で免除しない。

照合結果の `boundary_gaps` / `population_gaps` は探索と段階別母集団、`source_gaps` は資料の内容・採用・提供、`dataset_output_gaps` は実出力の欠落・重複・金額/原典対応を示す。これらと現行固定入力の未対応が全てなく、現行全量buildの証明がある場合だけ完了とする。構造が正しい証跡と現在のCSVの一致を検査するものであり、公式ページを再探索したりPDFを読み直したりする代わりにはならない。


### 正式な階層名と独立した目×節の直接照合

提供行の事業相当の階層には、dbtが宣言する `jikou` / `saimoku` / `jigyo` / `daijigyo` / `chujigyo` / `shojigyo`、狛江の補正説明明細では `project` を使う。原典の観測語（事項、細目、事業等）と提供行の正式なlevelを区別し、`jigyou` 等の別の綴りで提供経路を判定しない。経路JSONに宣言ノードがあってもコード・名称とも空、又は当該団体が宣言した欠如記号だけなら、その階層を観測済みと数えない。

狛江の `supplementary-expenditure-project-setsu` は、原典に印字された事業・節・担当課の増減額を正本の変更として保存する。監査はこのdatasetの全行を `int_supplementary_expenditure_changes` と実変更CSV・予算対象CSVへ照合する。当初対象との対応が未確認でも、補正の原典行を落とさない。旧 `expenditure-detail` の同じ年度・会計・補正号は `source_json.observationRole: nonadditive-supplementary-reference` として、全旧原典列・行番号・金額・版を `supplementary_moku_reference_observations.csv` に保存する。参照の原典行は正本の変更CSVに重複収録されていないことも確認する。`nonadditive_reference_tables` はその保存結果であり、事業×節の対応済み件数には加えない。

狛江の新しい当初明細は `source_json.observationRole: authoritative-initial-detail`、`canonicalInitial: true` とする。監査は当該datasetの全行を `int_132195_initial_detail` から取得し、通常の当初CSV・予算対象CSVへ一対一で照合する。さらに `initial-detail/` の採用原典・Parquet・証跡のハッシュと、Parquetの全原典列・全行が中間表で保持されていることを確認する。`initial_expenditure_budget.csv` の全列を実際のCSV用モデルへ照合し、金額・階層・印字節・担当課・頁・原典位置・印字事業合計・目合計・承認根拠・単位のJSON証拠を原典列へ直接照合する。これらの処理を追加した段階では、実際の採用・現行全量build・提供確認は未完了である。

同じ年度・会計の旧二目の当初額は `nonadditive-initial-moku-reference` として、全旧原典列と金額を `initial_moku_reference.csv` へ保存する。監査は正本の当初明細に同じ原典行が残っていないことと、参照を置き換える採用済み当初明細が実際に存在することを確認する。参照CSVの確認結果は `nonadditive_reference_tables` に含め、会計別の当初収録完了や対応済み事業×節の件数には加えない。

会計の照合は原典セルの宣言された同一性を保つ。例えば三鷹の `01一般会計` は、当該団体のCSVに対する `dbt_project.yml` の `prefix2` 宣言によりコード `01` と名称 `一般会計` になる。原典の会計集合と版の会計名をこの対応で照合し、提供datasetのfundもコードと名称の両方が一致する必要がある。同じ名称に複数コードが当たる場合は自動で選ばない。別団体、PDF、宣言のない名前から数字を除くことはない。

千代田の `statement-moku-setsu/` 固定入力は、左頁の目×印字された節を保持する独立した表である。採用証跡は `observation_role: independent-moku-setsu`、`grain: document-fund-moku-printed-setsu-row`、`project_setsu_linkage: unconfirmed`、説明欄の `explanation_dataset_id` を持つ。提供CSVは `fiscal/131016/initial_expenditure_moku_setsu.csv`、粒度は `line_granularity: independent-moku-setsu` とする。独自のdataset IDは団体・年度・方向・文書・原典ハッシュ・partitionのtable IDから、観測IDはdataset IDと原典行番号から作る。legacy説明欄はtable partitionがないIDを保ち、証跡内の説明用table名をそのIDへ混ぜない。

監査は現行buildのCSV集合・全ハッシュを確認した後、lockで採用された原典とParquet objectのハッシュ・サイズ、Git証跡のハッシュ、全原典行とside CSVを直接照合する。倉庫内のside用明細登録や `int_fiscal_lines` への参加を完了条件にしない。行番号・観測ID・年度・会計・科目/節コードと名称・表ID・原典金額・単位（千円）と円換算・元のページとbbox・内部突合状態・approved・未確認の事業節対応・証跡メタデータが一致し、重複も欠落もない場合だけside表の出力を確認済みとする。説明欄datasetへの参照は同じ原典版・年度・会計・文書に当たり、その説明欄の提供も別途確認される必要がある。

事業・説明の内容をside表へ生成したり、制御合計を節明細に置き換えたりしない。`moku_without_printed_setsu` は印字された節のない目の原典情報として照合結果に保持し、ゼロや推定の節を追加しない。目×事業と目×節は同じ金額の別の分解であり、金額を足し合わせない。side表の確認だけでは、censusの版・方向・関係根拠・探索境界・残件や他会計の不足を解消しない。採用side表のCSVがない、Parquet/objectが失われた、説明datasetの参照が違う場合は未完了を保つ。

照合結果の `adopted_independent_side_table_count` は現行lockの採用数、`independent_side_tables` は現行buildを確認できた場合の直接照合結果である。後者には各表の原典・Parquet・証跡ハッシュ、固定入力パス、出力ファイル、成功/失敗、印字された節のない目を保持する。buildの証明がない場合は空配列であり、独立表の提供を確認済みとは意味しない。

多摩市の `tama-settlement-pdf/` は、決算書の目×法定節と事業別資料の事業×財源を別の入力・dataset・提供CSVにする。`legal-setsu` と `project-funding` の各原典行について、採用Parquetの全列、原典行番号、版・会計・金額段階・原単位と円換算、原典位置・原観測JSONを実CSVへ直接照合する。各表は自分の粒度内で加算できるが、両表の金額を重ねて加算せず、事業×節の対応も生成しない。目・会計・事業の印字合計は非加算の別CSVで全行・全列を照合する。位置付き原典単語は内部martsの全行・全列を採用表へ照合し、金額を生成しない。非加算観測は会計別の金額段階の提供完了や事業×節の確認件数に加えない。

`adopted_independent_settlement_table_count` は現行lockの採用数、`independent_settlement_tables` は現行の全量buildを確認した後の直接照合結果を表す。datasetが実登録に存在しない採用表も欠落として報告し、監査内で登録済みへ昇格させない。原典・Parquet・採用証跡の各ハッシュを照合し、対応するCSVの未採用datasetや原典行の欠落・重複、単位変換や粒度の変更を拒否する。この処理の追加だけで、実CSVの保存や全公開年度の完了を認めるものではない。

### 全公開原典の粒度を保存する限定例外（v1）

PRDは、原典で事業×節の対応を確認できない場合も、確認できる原典粒度の全明細を保存する。`editions[].published_grain_exception` はこの場合の任意証跡であり、候補の登録には不要である。例外がなければ従来の粒度条件を使う。見出しのプローブ、数頁の抽出、原典の一部分の合計だけでは例外を使えない。親又は原典確認者が全原典を読んだ後に記録し、監査は証跡と現行固定入力・提供表の一致を検査する。

| フィールド | 必要な証拠 |
| --- | --- |
| `schema_version: 1`, `origin_sha256`, `lock_sha256` | 今回検査した全原典の版と現行lockに完全一致する |
| `fiscal_year`, `account_label`, `document_phase`, `amendment_number` | 当該editionと同じ年度・会計・文書・号。元の `content_confirmation` も引き続き必要 |
| `whole_original_inspection` | `scope: whole_original`, `independent_breakdowns_absent: true`, `method`, `row_count`, `page_count`, `basis`, `evidence_indices`。CSVは `method: csv_all_rows` と全データ行数、page_countはnull。PDFは `method: pdf_all_pages` と全物理頁数、row_countはnullで、索引の証拠が1から全頁を覆う必要がある。別頁/独立表の未採用を本当の欠如と混同しない根拠 |
| `absent_dimensions[]` | `dimension: project_setsu_relation` は必須、節も全原典に無ければ `setsu` を追加。各要素の `basis` と `evidence_indices` が印字された欠如を説明する。索引は `content_inspection.evidence[]` の0始まりの位置 |
| `dataset_ids` | 当該edition/accountで検査済み出力と採用版が一致したdataset集合に完全一致。原典の一部のdatasetだけを選べない |
| `preservation[]` | datasetごとに `dataset_id`, `fixed_input_path`, `scope: whole_expenditure_table`, `phase`, `row_count`, `source_row_column`, `account_column`, `amount_column`, `amount_unit`, `moku_columns`, `project_columns`, `setsu_columns`, `basis`, `evidence_indices` を持つ |
| `approval` | 補正だけ必須。`status: approved`, `basis`, `evidence_indices` に当該号の承認根拠を記録。掲載された議案だけでは通らない |

`preservation.phase` は当初 `approved`、補正 `delta`、決算 `executed`。列名は採用Parquetの実際の列名で、列の意味・元の年度/会計/金額段階・単位（円又は千円）・表が歳出の全行を覆う根拠を索引の原典証拠に残す。`source_row_column: null` は元のCSVに行番号列がなくヘッダを1とした物理データ行を2から数える場合だけ使う。金額セルは有限の十進数として読む。空欄、未知の区切り表記、推定値をゼロにしない。

監査は現行の構築identity・CSV集合と全ハッシュを確認し、採用原典object、Parquet、Git証跡のハッシュとサイズを直接照合する。CSVはverbatim・復元確認済みの採用証跡が必要で、さらに原典バイト列を採用encodingで可逆復号し、全ヘッダ・全セル・source_rowをParquetと直接比較する。このCSV経路の `source_row_column` は採用表の `source_row` に限る。元の末尾空レコードは取り込みと同じ規則で金融明細から除き、途中の行を落とさない。その上で全Parquet行の行番号・会計・金額を当該phaseの実CSVの原典行参照と一対一で確認する。行数は証跡の `rows`、datasetの `line_count`、例外の `row_count` とも一致する必要がある。目が全行存在し、原典の事業/節の有無が提供経路でも保持される必要がある。印字された節/事業列を宣言から外すこと、節の分類に失敗したものを欠如扱いすること、原典に無い事業や節を追加することは拒否する。

既に確認した明示的対応又は独立内訳をこの例外へ切り替えない。対応する採用side表のCSVが欠けた場合も例外は使えない。全原典の欠如モードでは、原典に事業と節の両方が同じ行で印字されている場合は通常の明示的対応経路で検査する。全原典で節が無いと宣言しながら本文の観測語に節を記録している場合も矛盾として止める。明示的対応と本当の予備費例外が同じ版に混在する場合だけ、下記の厳密な行限定モードを使う。新しい未知の列名の意味や全PDFの印字の網羅性は、列名の機械推測では証明できないため、全原典を確認した人の索引付き証拠が必要である。

例外が通っても `project_setsu_relation: unconfirmed` を維持する。成功した資料の `published_grain_exceptions` は対象版、dataset IDs、欠如した区分、`project_setsu_confirmed: false` を報告し、対応済み事業×節の件数に加えない。例外は粒度に関する条件だけに作用する。会計・版・方向・対象範囲・補正承認・探索境界・phase出力・各 `unresolved` の完全一致する解消証跡が欠けていれば、資料と全体は引き続き未完了である。原典確認者の根拠の真実を、JSONの形やハッシュ一致だけで代替できるという意味ではない。

#### 同じ版の印字された予備費だけを限定する行モード

任意の `preservation[].row_exceptions[]` が一件でもある場合は行限定モードになる。例外行は `dataset_id + source_row` で列挙し、各行に `role: printed_reserve`, `role_column`, `basis`, `evidence_indices`, `printed_setsu_evidence_indices` を記録する。`role_column` は原典の目の列の一つで、実際の値が `予備費` でなければならない。別の目の名寄せ/分類失敗を予備費と呼ばない。最後の索引は、**本当の法定節の印字欄が空**である頁/領域の原典証拠を指す。説明欄に「予備費」があること、抽出器が未確認と記録したことだけではこの証拠にならない。

このモードでは全preservationに `statutory_setsu_code_column` が必要で、列は `setsu_columns` に含める。指定した原典の法定節コード欄は例外行でnull又は空白である必要がある。欠如記号や非数値を自動で空欄へ変換しない。例外行を除く**全原典行**には目・事業・節と数字の印字法定節コードがあり、実CSVにもその経路と法定節IDが保存されなければならない。例外datasetだけを選んだり、他の行を確認せず例外行だけの合計を保存したりできない。原典/Parquet/当該phase出力の全行・全金額・全会計の照合条件は両モードで同じである。

例外行には法定節IDを生成しない。原典に印字された予備費の説明名を持つことと法定節に対応することを区別し、名前だけの原典の欄を法定節へ昇格させない。`absent_dimensions` の `setsu` はこのモードでは列挙した行の法定節欠如を意味し、版全体の節欠如とは意味しない。成功報告には `row_exceptions` としてdataset・source_row・roleを返す。残りの行が明示的対応であっても、例外を含む版全体を確認済み事業×節と呼ばない。全原典が節を持たないCSVには引き続き全原典欠如モードを使う。

狛江の採用済み `initial-detail/` では、`observationRole: authoritative-initial-detail`、`canonicalInitial: true` の実datasetに限り、この行モードを使う。採用Parquetの全列と現在の当初CSVを直接照合済みで、原典の承認を表紙で確認し、全観測粒度の検査が完了して抽出残件がなく、予備費の原典行が明示列挙されていることを要求する。旧二目の非加算参照は残すが、この例外の金融明細へ混ぜない。独立内訳、決算の財源表、合計・単語表など別の観測役割へこの許可を広げない。

2023〜2026年度の公式8冊・全1,849物理頁と19会計表・7,409行について、既存の構築ID `b-57c23b1b7c3b4153d80cb7c48ced2b99` の実CSVを全行照合し、予備費16行の実法定節領域に位置付き単語がないことを原典から読み直した。原典の全頁観測・空白領域の位置・印字金額を一覧へ追加し、16会計版に行限定例外、予備費のない3会計版に明示的対応の根拠を記録した。これは有限の原典・出力照合であり、追加した監査コードで現行の全量buildが済んだという宣言ではない。通常の構築identity検査・再構築と全公開探索の条件は引き続き必要である。

現在の例外v1は、一意の見出しを持つverbatim CSVの全金融明細が有限の金額を持ち、Parquet行数とphase明細行数が一致する形を扱う。空/重複ヘッダを位置で保持するCSV、印字された金額なしの事業行、注記/参照/末尾の空レコードを独立した観測表へ出す形は未実装である。多摩の決算CSVにはこれらの実物があり、候補を発見しただけでは例外で通らない。金額なしはゼロにせず、別の決定的な原典観測出力と金融明細の母集団を対応付ける契約が必要である。原典の口座全体が途中で切れているCSVもwhole-original/whole-accountの完了証拠にはならない。
