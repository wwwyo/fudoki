# monorepo 移行の検証記録

2026-10-01。設計 PR [#38](https://github.com/wwwyo/fudoki/pull/38) はマージ済み。実装の完了をこの記録の途中結果だけから判断しない。

これまでの検証を時点ごとに記録する。初期の R2 manifest・catalog・版一覧・遠隔検証記録の配置は、後述の Git manifest 統合で置き換えた。現在の設計は [ADR 0014](adr/0014-git-distribution-manifest.md) を参照する。

## 確認できたこと

- ingestion・dbt・FDP・報告・ローカル検証画面を `pipeline/`、共有する純粋なデータ規則を `packages/`、slides を root に移した。
- 全36入力の33種類の原典 CSV/PDF を回収し、既存の証跡の SHA-256 と一致した。取り込み済みの表・証跡を別の内容アドレスとして保存し、固定入力のローカル復元で build した。原典の欠落は0。
- [ADR 0012](adr/0012-git-input-provenance.md) により採用した証跡36件・59,999 bytesを ingestion 配下の Git ファイルへ変更した。schema 2 の移行用 lock から表をキャッシュ、証跡をファイルとして復元する。正規 lock の固定は原典・表の遠隔保管を検証してから行う。
- 全量 dbt build の156項目（85検査とモデル・seed の構築）が通過し、5団体・32配布 CSV を生成した。配布数値・出典・分類判断と元の配布物の比較を実施した。ID と dataset/document/edition の列は新契約に変更した。
- D1 取込用の8表は合計732,065行。SQLite の保存形式・外部キー・整数精度の検査に成功した。実際の release ID を使った DB は423,673,856 bytes、3版の単純推計は1,271,021,568 bytes。Cloudflare の保存容量・性能の実測値ではない。
- 公開 web の実ブラウザで狛江市の2023決算の集計と明細を確認した。公開 Worker のローカル D1 へ全量を入れて利用した。
- publish の転送失敗、D1 照合失敗、API の金額不一致、atomic な切り替え失敗、再実行、切り戻し、期限切れ処理を fixture で検査した。候補を完成前に API の公開参照へ切り替えない。
- 実際の Cloudflare D1 を APAC・read replication 無効で作成し、schema を適用した。REST batch が制約違反で失敗したとき、前の書込も残らないことを確認した。全量の遠隔取込は未実施。

- 固定入力のバックアップから空の別キャッシュへ全オブジェクトを復元し、33種類の原典のハッシュを照合した。PDF のローカル文字層・行対応を原典ハッシュに固定して生成した（千代田区1,235行）。

- バックアップから復元した固定入力で再 build し、完成済み候補の manifest が完全一致した。macOS のネットワーク拒否 sandbox 内でも全量 build と再 build が成功した。
- ローカル download Worker から配布38ファイルを GET し、内容の SHA-256・サイズ・ETag が一致した。
- download の版一覧は公開用 manifest のある版だけを列挙し、D1 を使わず次ページと個別 manifest へ辿れる。未完成の版だけのページ、入力不正、ストレージ障害を検査した。全量 CI に同一コード・固定入力の再 build と manifest 一致検査を追加した。
- TypeScript の92テスト・各 workspace の型検査・Python の11テスト・公開アプリの依存境界検査が通過した。API のコードを誤って除外する ignore を修正し、公開 web の component 検査も CI の実行対象に含めた。修正後の GitHub の新規 checkout の fixture・コード CI も成功した。
- ローカル download Worker の manifest と配布38ファイルを比較元として取得し、内容ハッシュを確認したうえで全46範囲の金額・ID・分類・注意点・出典に変更がないことを確認した。相殺される金額変更、版変更による ID の交代、出典・分類変更、壊れた比較元を Python の3検査で区別した。全量 CI は比較元を取得してから通信を禁止して build する。
- publish の検証結果を非公開 R2 に保存し、GET の内容を確認してから公開切替する処理を追加した。fixture では保存済み記録のハッシュ・download の非公開境界を確認し、記録の内容が壊れた場合は旧公開版が維持されること、再実行で復旧できることを検査した。
- ローカル view の実画面で、狛江市2023決算の原典 CSV と取り込み済みの表の行2が同時に選択されることを確認した。千代田区2026予算では、表の行4から PDF 45頁の該当行へ移動し、PDF の行5の文字から表の行5を選択できた。画面の repo 案内も新配置・R2/D1 の役割に更新した。

## Cloudflare CLI への移行

公開 API・download・docs・web の配信と非公開検証 Worker を `cloudflare.config.ts` / `cf` に移行し、旧 `wrangler.jsonc` を削除した。全5 Worker の `cf deploy --dry-run`、各 workspace の型検査、92個の Bun 検査を実施した。Web は Vite で画面を build し、`apps/web/deploy/` で静的配信用の Build Output を作る。

`cf dev` の API と download をループバックで起動し、狛江市2023決算の retained / executed を 2,217行・48,685,415,877円と照合した。download の38ファイルは全てハッシュ・サイズが一致した。ローカル D1 の投入、KV のキー発行・失効も確認した。ビルダーの既定保存先 `.wrangler/state/v3/` を共有し、ローカル投入と RPC に使う一時 JSON は cf の宣言から生成する。

新規依存の追加には cooldown 7日を指定した。公式設定ライブラリ 0.17.0・ビルダー 4.137.0 は exact pin、既存の mise CLI 1.0.0-beta.6 は維持した。現在の CLI でローカル D1 query が未対応、ローカル KV/R2 コマンドが書込後に終了しないことを確認したため、その操作だけはビルダーの proxy ライブラリを使う。CLI での本番配備・遠隔 RPC 接続は、下記の公開前検証で実施する。

## 全体の release と団体別配布物の版の分離

[ADR 0013](adr/0013-jurisdiction-package-versions.md) により、団体別配布物を `fiscal/<団体コード>/p-<内容hash>/` に置き、全体の release manifest と catalog から参照する実装に変更した。未変更の団体を複数 release から再利用し、D1 の `files.object_key` に同じキーを記録して API の配布 URL を生成する。D1 の派生表の保持単位は全体の release のままである。

Bun の97テスト・全 workspace の型検査が通過した。新しい全体の release で配布物を再転送しないこと、一団体の変更で他団体のキーが変わらないこと、複数年度・補正の原典版を別 dataset として収録すること、FDP の相対 resource path と API の共有 URL を検査した。補正予算のテストは架空の dataset であり、実際の取得対象には補正予算を追加していない。

全量 dbt build は156項目が成功し、5団体・28 dataset・46 dataset/phase を照合した。`cf dev` のローカル R2 から38ファイルの GET・HEAD・ETag による条件付き取得を確認し、全ファイルの SHA-256・サイズ・content type が manifest と一致した。遠隔 R2 への反映と直接配信への置き換えは下記の未完了条件に残る。

## 最新 manifest の Git 統合

[ADR 0014](adr/0014-git-distribution-manifest.md) により、収録範囲と配布物の参照を `pipeline/publish/manifest.json` 一つに統合した。Git には最新の採用候補を置き、過去は Git 履歴で辿る。R2 の catalog・release manifest・版一覧・候補 manifest・検証記録は廃止し、公開 R2 の対象は団体別の CSV と FDP descriptor の37ファイルとなる。D1 の公開中 metadata は Git commit 固定の manifest URL を持ち、Git の採用だけでは公開成功と扱わない。

Bun の100テスト・全 workspace の型検査・Python の比較検査3件が通過した。manifest だけの commit が構築版を変えないこと、空の初期 D1 schema の列変更と既存公開データがある場合の拒否、Git manifest とローカル照合記録の内容一致を検査した。配布物のファイルごとの用途、複数年度・補正予算の未実装条件も設計書に追記した。

全量 build の156項目が成功し、5団体・28 dataset・46 dataset/phase を確認した。`cf dev` の公開配信から37ファイル全件の SHA-256・サイズを照合し、旧 manifest・catalog・版一覧の route が404となることを確認した。Git manifest 相当の比較元を別のローカル HTTP 入口から取得し、配布物の別入口からのハッシュ照合と全46範囲の意味の比較が通過した。

非公開検証 Worker と呼出側 Worker を `cf dev` で別々に起動し、実際の service binding / RPC session から候補照合と D1 の1行 chunk を取得した。コード revision を改変した検査情報は拒否された。これは Cloudflare のローカル実行であり、遠隔 binding・全量 D1 の性能は未検証である。

## 団体マスタの分離

[ADR 0015](adr/0015-jurisdiction-master.md) により、`jurisdictions` は団体コードだけを主キーとする共通マスタへ変更した。公開版の注意点と名称・OCD ID の記録は `release_jurisdictions` に移し、dataset からの複合外部キーを追加した。候補の途中失敗・再試行・切り戻しで API の説明が公開版に対応することを検査した。空の旧 schema の初期化では団体表と dataset の外部キーを再作成し、既存データがある場合は拒否する。

Bun の103テスト、全 workspace の型検査、API と非公開検証 Worker のビルドが通過した。全量 dbt build の157項目が成功し、5団体・28 dataset・46 dataset/phase の API と dbt の集計が一致した。共通マスタ62行と公開版別8表732,065行を分けて検査し、SQLite は423,690,240 bytesとなった。これはローカルの候補であり、遠隔 D1 の適用・性能確認ではない。

COFOG マスタと明細の外部キーへの統合案、補正予算の再計算条件は設計書に整理した。COFOG の現行表は変更しておらず、補正予算の取得・文書間の明細対応・再計算も未実装である。

`cf dev` のローカル D1 で団体情報62件の名称・OCD ID・注意点が Git manifest と一致し、28 dataset の取得が成功した。既存配布物との比較では全46範囲の明細・金額・分類に差分がなく、manifest 採用後も同じ構築版を再利用できた。

## 歳出予算を事業×歳出の節へ揃える変更の設計

2026-10-02 に採用した設計では、共通マスタ `fiscal_expenditure_setsu` と参照列 `expenditure_setsu_id` を設ける。歳出予算対象は事業×歳出の節、当初予算・変更の下位内訳と原典行への対応は `details_json` とする。歳出の節と COFOG を独立した分類軸として扱い、GFSM は提供しない。決算・歳入の明細はこの集約の対象に含めない。

設計書・ER 図・PRD の更新のみ完了し、マスタ・集約・JSON 内訳の実装は未着手。現行の予算明細は原典行の粒度である。[財政データの設計](design-doc-fiscal-records.md) の未完了タスクとして追跡する。

## COFOG マスタと明細の統合

[ADR 0016](adr/0016-cofog-master-and-assignment.md) により、D1 の1対1の `cofog` 表を廃止した。分類コード・名称・階層は共通マスタ `cofog_codes` へ生成し、明細の `cofog_code` から外部キー参照する。現在使用するコードと祖先の37件を保持し、全分類の一覧を新たに管理してはいない。状態・規則・根拠・連結の判断は明細に保持する。

Bun の107テスト、全 workspace の型検査が通過した。全量 dbt build の158項目が成功し、R2 の分類 CSV と D1 の39,552明細で分類・連結判断が一致した。分類コードを CSV の自動型推論で数値や日付へ変換しないよう、配布物の再読込時の型を明示した。粗い粒度の割当・NULL の分類不能・存在しないコードの拒否・マスタの定義の衝突・空の旧 schema の置換も検査した。

公開版別の7表は692,513行、共通マスタは団体62行・分類37行となった。SQLite は410,300,416 bytes。5団体・28 dataset・46 dataset/phase の API と dbt の集計が一致した。補正等の取得と照合が揃った後に決算の提供用明細を実績1金額へ整理する方針は設計書に反映し、今回の金額段階は変更していない。

`cf dev` のローカル D1 で、大分類・中分類・小分類の割当、分類不能・対象外・歳入の適用対象外の6ケースを確認した。各階層の集計とページ継続も同じ候補の SQL 結果に一致した。既存配布物との差分は全46範囲でゼロであり、再構築時の manifest・内部検査記録も一致した。遠隔への適用は未完了である。

## 自治体別の直接取り込みへの再設計

[ADR 0017](adr/0017-jurisdiction-data-versions.md) を更新した。団体別の内容版は維持し、全体公開一覧・公開切替・非公開候補・guard を廃止する。取り込み途中の明細も通常 API から取得できる。部分失敗は反映済みの行を残し、同じ主キーで再実行する。

上記は各段階の旧実装の履歴である。以下の新しい実装は22表へ変更し、決算実績と当初予算を分離した。5団体・28 dataset の254項目の dbt build と、D1/API の28範囲の件数・金額照合が通った。D1 用 SQLite は218,005,504 bytesで、遠隔 D1 の性能値ではない。変更・対応の実資料は未収録で `unconfirmed`。2026-10-02の遠隔 R2 確認も403/10042だった。

- [x] D1 と dbt の団体別内容版、歳出歳入・予算決算の分離。
- [x] 実績 amount 一つ、原典の報告値の保持、予算履歴の未確認範囲の明示。
- [x] Git manifest と R2 固定 URL、未変更団体の再利用。
- [x] 公開切替・guard・全体 release のコードと API 契約の除去。
- [x] 部分取り込みの通常 API での取得と再実行。
- [x] Cloudflare ローカル環境・全量入力の検証と新しい overview。
- [x] PR [#39](https://github.com/wwwyo/fudoki/pull/39) の作成、Pi レビューと指摘対応。

最新版のコード検証では Bun 85 件、Python 15 件、全 workspace の型検査と公開アプリのビルド・境界検査が通過した。新提供 CSV と D1 の明細・金額・分類・連結判断を dbt の双方向差分で検査する。応答途中に新版が登録されても応答内の版が混ざらないことを競合の fixture で確認した。

2026-10-02 の最終検証では、`cf dev` の通常 API から5団体・28 dataset を取得し、公開 R2 のローカル adapter 経由で82ファイル全件の GET/HEAD・サイズ・SHA-256 と、存在しないファイルの404・キャッシュ抑止を確認した。全量の再構築で配布 manifest と内部検査記録が一致し、初回提供として意味の比較検査も通過した。予算変更は通常の履歴 API から変更行を照合する検査を追加し、fixture では金額を改変した応答を拒否した。実資料の変更行は現在0件であり、収録完了とは扱わない。

Pi の別 harness レビューと再レビューを実施し、公開 docs の旧契約、予算変更の公開 API 照合不足、取得層の保存先説明、COFOG のエラー文言を修正した。PR の bot 指摘は origin の説明・版配列の順序・団体限定の名称 JOIN の理由を補った。コードの再利用・品質・効率と、実ブラウザでの歳入歳出・ページ継続も別に確認した。

再構築を繰り返す中で、狛江市の決算歳出 CSV に表走査順による行順差を検出した。行集合と金額は同じだったが配布ハッシュが変わるため、全77配布 CSV の書き出しを共有マクロへ移し、全列で順序を固定した。

順序固定後の254項目の build と再構築が成功し、manifest・検証記録の完全一致を確認した。変更した会計フィルターを含む Bun 85 件（253アサーション）も通過した。

## 2026-10-02: 遠隔のキャッシュ設定を先行適用

R2 を再確認し、403/10042 と `Please enable R2 through the Cloudflare Dashboard` が継続していた。R2 の有効化待ちとは独立した Cache Rules を `fudoki.dev` へ先行適用した。サーバーでの検証と適用後の読み返しで、`fudoki_distribution_cache` が Git の定義と一致し有効であることを確認した。R2 の直接配信・原典と配布物の転送・D1/API の更新は未完了。公開後の `CF-Cache-Status` 実測も残る。

Free zone の rate limit 枠には既存の `Leaked credential check` があり、配布用ルールは適用しなかった。既存ルールは変更・削除していない。

## マスタを概念と表名で明示する変更の設計

団体マスタ・COFOG分類マスタ・歳出の節マスタを、年度や資料に属する予算対象・金額明細とは区別する。設計上の表名を `jurisdiction_master`、`cofog_master`、`fiscal_expenditure_setsu_master` に揃える。現行 SQL の `jurisdictions`・`cofog_codes` の改名と節マスタの追加は未実装であり、上記の移行記録にある旧名は当時の実装を表す。共通マスタは自治体の提供データ版 `version_id` に依存させない。
