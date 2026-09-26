# ① 予算パイプライン


⚠️ **この文書に個別の団体の話を書かない。** 団体固有の実測・原典の癖・注意は
`ingestion/budget/jurisdictions/<団体コード>.md` に書く（取得元の宣言の隣）。
ここに書き込むと、団体を足すたびにこの文書が肥大して設計が読めなくなる。
収録済みの団体と年度は `ingestion/budget/sources.toml` が正本。

```bash
bun run pipeline    # 取得（CSV と PDF）→ dbt → 配布物 → 報告
bun run dev         # 報告を作り直してダッシュボードを上げる
```

**原典は CSV とは限らない。取得の経路が2つある。**

| 経路 | 取得器 | 原典 | `raw_form` |
|---|---|---|---|
| カタログの CSV | `ingestion/budget/fetch.py` | CKAN のリソース | `verbatim`（復元一致を検査） |
| 事項別明細書の PDF | `ingestion/budget/extract_statement.py` | 自治体サイトの予算書 | `extracted`（復元一致は成立しない） |

⚠️ **PDF のほうが例外ではない。** 東京62団体のうち**59団体は事業単位の資料を PDF でしか
出していない**（2026-08-30 実測。節まで届いた資料87本はすべて PDF で、カタログの CSV で
事業単位に届くのは既収録の3団体だけ）。CSV を背骨にした取得器では1団体も足せない。

⚠️ **抽出した表は「原典 CSV と同じ形」で落とす。** そうすると `budget_staging` 以降
（宣言・検査・配布物の生成）はそのまま効き、経路の差が取得の1段に閉じる。
`staging_is_one_to_one` などの原典突合は**抽出結果との一致**を見ることになり、
検査の意味は保たれるが**保証の強さが変わる**（原文へ戻す検査は不可逆なので成立しない）。
`fdp/build.py` は証跡が名乗る保証（`roundtrip_verified` / `verification`）と `raw_form` が
食い違っていないかを見て、配布物の説明文に強さの違いを載せる。

⚠️ **事項別明細書は法定様式なので、列の意味は全団体で共通。組版は共通でない。**
読み取り（款・項・目・節・説明という列が何を意味するか）は `statement_layout.py` が共有し、
座標と作りは団体ごとに `sources.toml` が宣言する。原則5の、共有側と個体差側の切り分けにあたる。
**2団体を通した時点で、宣言に出すことになったのは次の6つ**（どれも実物を見ないと書けない）。

| 宣言 | 何が割れたか |
|---|---|
| `columns` | 列の x 範囲。**direction でも割れる**（同じ資料で目の欄の幅が歳出と歳入で違う） |
| `left_page_columns` | 見開きのどちら側に来るか（節が右頁の団体と左頁の団体がある） |
| `heading_style` | 款・項の見出しの記法（`第 １ 款 …` / `（款） 1 …`） |
| `explanation.model` | 説明欄の作り（節の内訳か、説明欄自身が入れ子か） |
| `explanation.levels` | 説明欄の段と、その金額の右端 x |
| `explanation.amount_suffix` | 説明欄の金額に付く単位（`千円`。付かない団体もある） |
| `explanation.numbered` | 説明欄の項目に通し番号が振られているか（`１ 議員報酬…`） |

⚠️ **原典の利用条件が未判断の団体では、配布物に `licenses` を書かない。**
抽出した事実に原典のライセンスは付いてこないので、選択と構成の部分を fudoki が
CC BY 4.0 で配ることは**できる**。だがそれは「配ってよい条件が決まった」という主張であり、
**判断が済んでいない段階で出すと済んだように読める**。仕様上も任意のフィールドなので、
**未確定は書かないことで表す**（未定を表す値が仕様に無い）。整理は [data/LICENSE](../data/LICENSE)。

⚠️ **抽出物のスキーマは団体でも direction でも同じにする。** 埋まる列は作りで変わるが、
列そのものを変えると抽出器が団体の数だけスキーマを持ち、`read_parquet` の glob も割れる。
使われない段は空文字で残し、**どの段を使うかは `budget_levels` が宣言する**。

**配布の単位は団体である。** 判断（COFOG、事業名）もその団体のパッケージへ入れる。

| | 単位 | 中身 |
|---|---|---|
| `data/raw/` | (団体, 年度, direction) | 原典。Parquet。判断ゼロ |
| `data/budget/datapackages/<団体>/` | 団体ごと・**全年度** | 正本（`expenditure` / `revenue`）と判断（`cofog` / `cofog_rules` / `project_names`） |

**正本と判断はリソースで分ける。ファイルは混ぜない。**
`expenditure.csv` は原典と突き合わせて検証できるが、`cofog.csv` には突き合わせる相手がいない。
1つの表に混ぜると、市が公表した事実と fudoki の判断を利用者が列で見分けられなくなる。
`budget_line_id` で join できるので、分けても失うものが無い。

⚠️ **団体をまたぐ結合ファイルは作らない。** 以前は判断だけを `derived/` へ団体をまたいで1つに集めていたが、
横断が派生でしか成立しないという主張自体が誤りだった。実際には団体ごとのファイルを1行の glob で読める
（`read_csv('data/budget/datapackages/*/cofog.csv')`）。横断の問い合わせは API 側の仕事で、
配布物を1つに畳む理由にならない。むしろ結合ファイルは、
**正本ごとに違うライセンスと出典を1つのライセンス表示に潰す**という害がある。
判断を各団体のパッケージへ置けば、その団体の `licenses` / `sources` / `modifications` がそのまま効く。

**団体をまたいで正本を1つにしない**理由は別で、階層の構成が団体ごとに違い
（事業階層の名前も段数も揃っていない）、揃えることが「同じ概念だ」という**判断**になるため。

**系統は dbt の `manifest.json` から取る。** 段はモデルの置き場（`staging` / `core` / `package`）が決めるので、
ディレクトリを動かせば画面の図も動く。以前は `topology.ts` が宣言しており、パイプラインを変えても図が変わらない状態を2度作った。

**descriptor に独自プロパティを足さない。** 足すほど、標準しか読まない実装から見える情報が減る
（読み手はその property の名前を知らない）。足す前に必ず仕様本文を当たること。
実際、独自の `constants` として持っていたものは仕様の **Constant Fields**
（リソースの `schema.extraFields` の各項目に `constant` を持たせる）そのものだったし、
`provenance` は取得物の隣の provenance.json を descriptor へ写しただけだった。
CC BY が求める帰属と改変の明示には標準のプロパティが無いが、
これも独自フィールドではなく標準の `description`（Markdown 可）と
`sources` / `contributors` に載せる（整理は [data/LICENSE](../data/LICENSE)）。

**パッケージ直下の `columnTypes` とリソースの `schema.fields[].columnType` は重複ではない。**
前者は仕様が定める _ColumnType_ definition package の置き場（宣言）で、後者は個々の列がそこを指す参照である。

**集計は `report/budget/build.ts` の1箇所だけ**で行う（画面側でも集計すると、同じ数字が2通りに計算されて、いずれ食い違う）。

⚠️ **型が効かない場所は、実装を変えた瞬間に壊れる場所である。**
明細を `Record<string, string>` で運んでいたため、配布物から `*_source` 列を落としたとき
画面はその列で絞り込んだままになり、**型検査も通ったまま明細タブが空になった**。
いまは `report/budget/detail.ts` が列を宣言し、3箇所で守っている。

| どこ | いつ | 何を |
|---|---|---|
| 生成側 | 実行時 | 宣言した列が射影に無ければ落とす |
| 画面側 | コンパイル時 | 宣言に無い列を読めない |
| JSON の境界 | 読み込み時 | 古い `pipeline.json` を掴んだら理由を出して止める |

真ん中が要るのは、**型は生成側と画面側の両方に効くが、間に挟まる JSON には効かない**ため。

**実データで判明した想定外は `.agents/skills/pipeline/references/budget-extraction.md` に書く**
（この文書には書かない）。団体固有の癖は `ingestion/budget/jurisdictions/` へ。

### 科目マスタ（法定の款・項）

**款のコードは団体ごとに法定とずれる**ので、コードでは団体をまたいで比較できない。
地方自治法施行規則 別記「歳入歳出予算の款項の区分及び目の区分」（第15条関係）の市町村の表
（歳入・歳出の両方）を原文から起こしてマスタにし（`bun run fetch:account-master` → `dbt/seeds/budget/account_master.csv`）、
団体のコード・名称との対応を `dbt/seeds/budget/account_map.csv`（判断）で持つ。

- **遵守はテストで縛る。** 一般会計の歳出に対応表へ無い款・項が現れたら
  `dbt/tests/account_map_covers_lines.sql` が止める。黙って未対応のまま配らない
- **法定に無い科目は誤りではない**（様式の備考1が行政権能の差による追加を認める）。
  `kind=addition` として明示登録する。現行様式から削除された旧法定区分
  （例: 自動車取得税交付金）は `kind=historical`（どの科目がそうかは `account_map.csv` と各団体の文書にある）
- **目は揃えない。** 目以下の横断は COFOG が担う（科目の再編を同一視する根拠が無い）
- 適用範囲は**一般会計だけ**（様式の備考: 特別会計は長が定めた区分による）。
  歳入・歳出の両方に効くが、**科目の名称が得られていない団体 × 方向には対応を付けない** —
  名称の根拠なしにコードで対応づけるのは、款コードの誤りを一度やった当の推測にあたる
- ⚠️ **起こしているのは基本の表だけで、備考の読み替え規定は起こしていない。**
  歳入の備考2は、ゴルフ場所在市町村や国有提供施設等所在市町村助成交付金の適用市町村について
  款を挿入し以降を繰り下げる読み替えを定めている（多摩市がこれに当たる）。
  読み替えで現れる款はマスタに無いので `kind=addition` として登録し、根拠を `basis` に書く。
  ⚠️ **これを「マスタの抽出漏れ」と読み違えた**（PDF の 9〜12 ページにある読み替え後の表を、
  基本の表と同じものだと思った）。マスタに無い款を見つけたら、まず備考を読むこと
- ⚠️ **e-Gov の法令 XML にこの別記は入っていない**（`<Fig src="">` が空。2026-08-23 実測）。
  添付 PDF の直リンクから起こしており、`fetch:fdp-taxonomy` と同じ「正準が壊れているので
  自分で維持する」型にあたる。原文の SHA-256 をスクリプトに固定してあり、改正されると止まる
- 配布は団体ごとの `account_names.csv`（判断のリソース）。名称の出所（原典か決算書 PDF か）を
  `name_source` で区別し、マスタへの対応を `master_*` 列で持つ

### 団体を足す手順

**団体差はすべて宣言に出す。** モデルを団体ごとに写経しない（片方だけ直る）。

⚠️ **まず取得の経路を決める**（上表）。カタログに事業単位の CSV があるなら
`sources.toml` のトップレベルへ、PDF しか無いなら `[statement]` 節へ足す。
以下の手順は2〜3の書き方だけが経路で変わり、4以降は同じである。

1. **実測してから決める**（推測で埋めない。原則3・原則4）
   兄弟間でコードが一意か、コードの桁数、その階層が無い行のプレースホルダ、文字コード、
   階層だけで行が一意になるか、金額が何段階あるか、単位。
   観測は `ingestion/**/observations/` に残す（commit しない）。要約ではなく数字を残し、主張には実測日を添える
2. `ingestion/budget/sources.toml` に取得元を足す（歳出と歳入でデータセットが別なら
   `dataset_title` はリソース側に置く。同名のデータセットが複数あるなら `resource_url_contains`）。
   ⚠️ **原典は公開されているのにカタログへ登録されていない**ことがある（多摩市は令和4年度で
   登録が止まっているが市サイトには令和7年度まで置いてある）。そのときだけリソースに
   `url` を直接宣言する。**理由（`url_basis`）が無ければ停止する** — 名前から解決する経路の
   安定性を捨てる判断なので、後から読んだ者に「カタログにあるのに横着した」のと区別が付く必要がある。
   ⚠️ **その年度ブロックから `catalog` / `dataset_title` / `fiscal_year_label` を消すこと**
   （全リソースが直 URL のとき）。3つとも CKAN を引くときにしか読まれず、
   残すと**証跡と配布物の `sources[].title` に、引いてもいないカタログのデータセット名が載る**。
   書いてあれば `load_sources` が止める（逆にカタログ経由なら無いことで止まる）。
   ⚠️ **再配布の根拠も、カタログではなく取得元のページの表示に取り直すこと。**
   カタログに登録の無いものへカタログのライセンスは援用できない。
   ⚠️ 直 URL では取得時の年度照合（リソース名に年度表記があるか）が自己参照になって効かなくなり、
   年度の裏づけは原典の年度列と partition の突き合わせだけになる。
   ⚠️ **原典に年度の列も無ければ、機械はその年度を一度も照合しない**
   （多摩市の令和7年度の歳出がこれにあたる）。裏づけが無いという意味ではない —
   直 URL を人が拾った元のページに見出しとリンクテキストがあり、それが CKAN の
   `resource_name` と同じ役割を果たしている。**その文字列を `url_basis` に書き残すこと。**
   人が読んだ根拠を宣言に残さないと、機械が見ていないことと区別が付かなくなる
3. `uv run python -m ingestion.budget.fetch <団体>:<年度>` で取得。
   **引数なしなら登録済みの全取得元**を回す（`bun run pipeline` はこれを使う）
4. `dbt/dbt_project.yml` の vars に1ブロックずつ足す。
   `budget_levels` / `budget_source_columns` / `budget_extra_key_columns` /
   `budget_extra_key_source_columns` / `budget_absent_level_markers` / `budget_code_style` /
   `budget_label_columns` / `budget_levels_without_code` / `budget_extra_key_labels` /
   `budget_amounts` / `budget_source_year_columns` / `budget_expenditure_revenue_balance`
   （**単位は `budget_amounts` だけが宣言する**。語彙に無い単位を使うなら
   `budget_amount_unit_multipliers` に倍率と対で足す。
   **年度で列名・単位・年度の列の有無が割れるなら、各宣言に `years` を書いて分ける** —
   宣言を写経して団体ごとに増やさない）
5. `dbt/models/staging/budget/_sources.yml` にソースを、`stg_<団体>__{expenditure,revenue}.sql` に
   `{{ budget_staging('<団体>', '<direction>') }}` の1行を書く（本体はマクロが宣言から組み立てる）
6. `dbt/models/package/budget/pkg_<団体>__*.sql` を書く。**正本は団体ごとの形のまま**で、
   共通化しない（揃えることが判断になる）
7. `dbt/seeds/budget/cofog_rules.csv` に規則を足す。名称が無い団体は `match_kan_code` で当て、
   何の款かとその出所を `basis` に書く
8. `fdp/build.py` の `IMPLEMENTED` と `fdp/field_types.json`（新しい列の ColumnType）
9. `report/budget/static.ts` の `BY_JURISDICTION` に caveats・notYetReconciled・consolidationScope
   （**宣言が無ければ report が止まる**。他団体の文言を流用させないため）
10. `bun run survey:structure <団体コード>` で観測を残す（主張の出所になる）。
    団体固有の癖・実測・注意は `ingestion/budget/jurisdictions/<団体コード>.md` に書く
    （**この文書には書かない**）
11. `bun run pipeline` / `bun run typecheck`（root と web）/ `bun run validate` を通し、
    `data/budget/` の生成物を commit する（CI が `git diff --exit-code` で見る）

足し忘れは**エラーで止まる**ようにしてある。黙って欠ける事故は起きない。

| 足し忘れたもの | 止める場所 |
|---|---|
| staging を足して core の union を直し忘れた | `dbt/tests/budget_core_covers_all_staging.sql` |
| core を足して判断の配布物を直し忘れた | `dbt/tests/judgment_package_covers_core.sql` |
| `fdp/build.py` の `IMPLEMENTED` | `sources.toml` の集合と一致しないと停止 |
| 新しい列の ColumnType | `fdp/build.py`（宣言の無い列は配らない） |
| 段階・単位の宣言と配布物の食い違い | `fdp/build.py` の `verify_against_csv` |
| `static.ts` の団体固有の内容 | `report/budget/build.ts`（既定値で埋めない） |
| 明細の列 | `report/budget/detail.ts`（生成時）と `web/src/lib/pipeline.ts`（読み込み時） |
| `budget_label_columns`（code-only の団体） | `macros/budget_staging.sql`（宣言が無ければコンパイルエラー） |
| 原典を取ったのに宣言していない | `dbt/tests/declarations_cover_raw.sql`（原典の側を母集団にする。事業名の抽出物も見る） |
| 金額の宣言を `years` で絞って、原典の年度を覆い忘れた | `dbt/tests/amount_declarations_cover_years.sql`（同じく原典の側を母集団にする） |
| 年度の列の宣言を `years` で絞って、照合を素通りさせた | `dbt/tests/source_year_column_scope_is_real.sql`（外した年度で列が本当に無いか） |
| 事業名の取得元（`[project_names]`）を消した | `dbt/tests/project_names_cover_budget.sql`（年度を宣言で持つので、消すと 0% で落ちる） |
| package モデル（`pkg_<団体>__*`）を足し忘れた | `fdp/build.py`（⚠️ **dbt は無いノードを警告して検査ごと無効化する** — 4本の検査が黙って消えるので、宣言を母集団にファイルの存在を見る） |
| 事項別明細書の団体を報告に足し忘れた | `report/budget/build.ts`（`[statement]` も母集団に入るので `static.ts` の宣言が無ければ止まる） |
| 証跡の名乗る保証と `raw_form` が食い違う | `fdp/build.py`（`verbatim` なのに復元未検査／`extracted` なのに復元済みを名乗る、を停止） |

**宣言どうしの矛盾は、足し忘れとは別の失敗の型である。** 足し忘れは「無い」を見れば済むが、
矛盾は両方揃っているので、突き合わせの粒度が粗ければ通ってしまう（金額の単位で実際に通した）。
だから**宣言を2つ持たない**のが第一で、それでも宣言が正しいかを見たいときは原典と突き合わせる。

| 宣言が間違っていたら | 止める場所 |
|---|---|
| 単位と倍率が対になっていない（`{千円, 1}`） | `dbt/tests/amount_units_match_source.sql`（**母集団は宣言**。モデルを1つ組む前にコンパイルエラーで止まる） |
| 宣言した単位が原典の列名（`予算現額(千円)`）と違う | 同上。⚠️ **列名が単位を名乗っていない団体（三鷹市の `08予算額`）は突き合わせる相手がいない** — その団体で確かめられるのは倍率との対応だけ |
| `years` が重なる・全年度の宣言が2つある・ある年度の primary が1つでない | `dbt/tests/amount_units_match_source.sql`（`check_budget_amount_scopes`。同じくコンパイルエラー） |
| 抽出が行の境界に乗っている | `extract_projects.py`（許容幅を変えて事業名が変わったら止まる） |
| 目の合計と事業の合計が合わない | `extract_projects.py`（合わない目からは名前を採らない） |

未確定のまま残したことは、パイプライン報告の Caveats 節にある。

## 未確定（移行に伴うもの）

- **配布形式は CSV のまま。** 全量（62団体 × 9年度）への外挿は CSV 1.1 GB / gzip 156 MB / Parquet 141 MB。
  gzip は Data Package の仕様に `compression` プロパティが無く、Parquet は `format` が「csv, xls, json etc.」と開いているだけで明記が無い。
  **62団体のうち3団体しか無い段階で、外挿値だけを根拠に標準から外れる判断はしない。** 実際に増えたときに決める。
  ⚠️ 決算書の団体は正本が1桁大きくなる（年度数と、予算段階ごとの行への展開の両方が効く）
- **1パッケージに複数年度を入れて FDP のバリデータが通るか未確認。**
  `date:fiscal-year` はそのための ColumnType なので通るはずだが確認する
- **`adjusted-before-transfer` は fudoki が宣言した予算段階。**
  FDP の慣行（proposed / approved / adjusted / executed）に該当が無い。
  `phase:id` は仕様上ただの文字列なので適合はするが、**他の実装がこの id を知っているわけではない**
- **款・項・目の名称は決算書 PDF の見出しにある。** 一般会計 2020〜2023年度に限られ、
  PDF の無い 2018〜2019年度と特別会計には付かない。
  ⚠️ **名称は次の行へ折り返す**（`１.保健衛生` + `総務費`）。繋がないと実在しない科目名になり、
  規則が当たらないか別の科目に当たる
- **TypeScript 版と同一結果であることの検査は、TypeScript 版を消すときに一緒に消える。**
  そのとき保証されなくなるのは「配布済みの識別子と割当が変わっていないこと」で、
  証明そのものは git 履歴（`944866c` 識別子、`83bd132` COFOG）に残る

