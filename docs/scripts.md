# スクリプト


**commit した生成物には生成手段を残す。**
生成物だけ残して作り方を消すと、そのファイルは誰も作り直せず検証もできない出所不明のデータになる。
方針3（fork できる、自分で維持する）が直接効く場所である。

⚠️ **ただし置き場は「調査スクリプト置き場」ではなく、生成物と consumer の近く。**
以前は `scripts/` に集めていたが、中身は補助スクリプトではなく
生成物の意味を決める domain code（ゲートのスキーマ、粒度の分類規則、taxonomy の生成）だった。

| script | 生むファイル | commit |
|---|---|---|
| `check:budget` | `ingestion/budget/observations/budget-granularity.json` | しない（ローカル観測） |
| （探索。エージェントが書く） | `ingestion/budget/observations/discovery/<団体コード>.json` | しない（ローカル観測） |
| `probe:documents` | `ingestion/budget/observations/budget-document-probe.json` | しない（ローカル観測） |
| `coverage:sources` | `ingestion/budget/observations/budget-source-coverage.json` | しない（ローカル観測） |
| `fetch:robots` | `ingestion/transcripts/observations/robots.json` | しない（ローカル観測） |
| `check:bulletins` | `ingestion/transcripts/bulletins.json` の `schemaCheck` 節 | ○（取得先マニフェストへの書き戻し） |
| `fetch:fdp-taxonomy` | `fdp/budget-taxonomy.json` | ○ |
| `fetch:account-master` | `dbt/seeds/budget/account_master.csv` | ○ |
| `survey:budget-years` | `ingestion/budget/observations/mitaka-budget-years.json` | しない（ローカル観測） |
| `survey:structure` | `ingestion/budget/observations/<団体コード>-budget-structure.json` | しない（ローカル観測） |
| `extract:statements` | `data/budget/raw/jurisdiction=*/`（事項別明細書 PDF から起こした表と証跡） | ○ |
| `eval:extraction` | `ingestion/budget/observations/<団体コード>-extraction-recall.json` | しない（ローカル観測） |
| `validate` | （検査。`ingestion/transcripts/gates.json` を宣言と、`ingestion/shared/jurisdictions.json` とコード集合で突き合わせる） | — |

⚠️ **ネットワークを叩くスクリプトは、サンドボックスを外して回す。**
開発環境の HTTP プロキシが応答を途中で切るため、サンドボックス内では
`IncompleteRead` が頻発する。取得元の問題と取り違えてリトライを実装しかけた
（実測: urllib + プロキシ経由は5回とも失敗、プロキシなしは5回とも成功。
切れる位置まで毎回一致するので、ランダムな不調ではない）。

ネットワークを叩くので CI では回さない。観測はローカルに書き出し、原文・URL・status・SHA-256・取得時刻を丸ごと持つ（要約しない）。

| script | 何を測るか |
|---|---|
| `bun run fetch:robots` | robots.txt の原文を取得して保存 |
| `bun run check:bulletins` | 議会だより CSV が観測プロファイルに適合するか（列構成で判定） |
| `bun run check:budget` | 予算系オープンデータが**どの粒度まで届いているか**（列構成で判定。名前では判定しない。**母集団は団体ごとの全データセット**で、クエリ語に依存させない） |
| `bun run probe:documents` | 探索が挙げた資料を**開いて中身で**粒度を測る（節の法定語の有無。資料名では判定しない）。アウトライン化・文字化け・WAF による拒否をそれぞれ別の出口として持つ |
| `bun run coverage:sources` | 上の3つの観測を突き合わせて「団体ごとに取得元が決まったか」を出す。**新しい事実は持たない** — 根拠は観測の側にある |
| `bun run survey:budget-years` | 同じ団体の他年度が収録済み年度と互換か（列構成・金額の型・引用符の有無・会計の範囲） |
| `bun run survey:structure <団体コード>` | その団体の原典が何を持っているか（階層が実際に使われているか・コードの再利用・行の同一性・歳出と歳入の一致）。**原典を読むだけでネットワークを叩かない** |
| `bun run extract:statements [<団体>:<年度>...]` | 事項別明細書（PDF）を原典として取り込む。**59/62 団体はこの経路しか無い**。冪等（原典の SHA-256 と抽出器の版で判定し、抽出の前に決める） |
| `bun run eval:extraction [団体コード...]` | PDF 抽出器の **recall**（原典にあって抽出できなかった目）を、正解のある団体で測る。年度ごと・経路（text / ocr）ごと・金額ベースでも出し、落とした目を一覧に残す。**抽出器を較正する場所**であって団体ごとのデータ検証ではない（正解があるのは 62 団体中 1 団体の歳入だけ）。**原典を読むだけでネットワークを叩かない** |
| `bun run pipeline` | 取得 → dbt → 配布物 → 報告。**検査が1つでも落ちたら下流を作らない** |
| `bun run dev` | 報告を作り直してダッシュボードを上げる（`apps/web/`） |
| `bun run fetch:fdp-taxonomy` | FDP の ColumnType 一覧を仕様の原文から起こして取り込む（正準 URL が 404 のため） |
