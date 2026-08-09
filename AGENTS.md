# kotonoha（言の葉）

日本の地方議会の会議録を取得し、**Popolo** スキーマに正規化して、オープンデータ（データごとリポジトリに置き CI で自動更新）と MCP サーバとして配布する。

名前の由来は古今和歌集の仮名序「よろづの言の葉とぞなれりける」。扱う対象＝議会の発言そのもの。

## なぜ作るか

予算がどう決まり何に使われたかの**過程**は会議録にしか残らない（予算書は結果、事業評価は自己申告）。その会議録は公開されているのに機械可読ではなく、横断も経年比較もできない。法律上は再利用できるのに、形式が閉じている。

## 設計方針

- **独自スキーマを発明しない。** 人・組織・役職・発言は [Popolo](https://www.popoloproject.com/)、本文構造は [Akoma Ntoso](https://www.oasis-open.org/standard/akn-v1-0/) 互換を意識する（AKN 完全準拠は後追いでよい）
- **UI は特定自治体向けサイトではなく汎用層として作る。** mySociety が TheyWorkForYou（UK専用）と SayIt（汎用）を分離したから他国が再利用できた。同じ分け方をする
- **運営者が消えても止まらない形にする。** データごと git に置き CI で更新し MIT で fork 可能にする。先行事例は個人運営で消滅（chiholog）か、会社に吸収され無料枠の線引きを握られた（Open States → Plural）
- コードは MIT、生成データはオープンデータとして公開する

## データ源: kaigiroku.net の JSON API

会議録検索システム **DiscussNetPremium**（NTT-AT）のクラウド版 `ssp.kaigiroku.net` に、ドキュメント化されていない JSON API がある。**認証・クッキー不要**で 477〜492 自治体が同一システムに載っている。

```bash
# 会議一覧（tenant_id だけで全年度。練馬区は約1.1MB、昭和22年〜）
curl -s -X POST https://ssp.kaigiroku.net/dnp/search/councils/index --data "tenant_id=367"

# 会議録本文
curl -s -X POST https://ssp.kaigiroku.net/dnp/search/minutes/get_minute \
  --data "tenant_id=367&council_id=5717&schedule_id=1"
```

`tenant_id` は各テナントの `https://ssp.kaigiroku.net/tenant/<name>/js/tenant.js` に平文で置かれている（練馬367 / 大阪市357 / 岡山県455 / 大分県499 / 久慈市121）。

主なエンドポイント（`https://ssp.kaigiroku.net/tenant/js/release/config.js` の `dnp.config.APIS` が一覧）:

| endpoint | 用途 |
|---|---|
| `councils/index` / `councils/view` / `councils/get_view_years` | 会議の一覧・詳細・収録年度 |
| `minutes/get_minute` | **会議録本文** |
| `minutes/get_index` / `get_schedule_all` / `get_material_list` | 目次・日程・資料 |
| `speakers/get_council_speakers` | 会議の発言者一覧 |
| `minute_searches/search` / `cross_searches/search` | 検索・横断検索 |

### レスポンスの重要な性質

`minutes/get_minute` は `tenant_minutes[]` を返し、**既に発言単位に分割されていて `title` が話者**になっている。ParlParse が自前でやっている発言分割・話者抽出が不要。

```
minute_id=1  title='（名簿）'          ← 出席委員・出席理事者の職名↔氏名
minute_id=3  title='小泉純二委員長'     ← 議員は氏名＋役職
minute_id=5  title='１第二回定例会付託案件'  ← 議題見出し
minute_id=13 title='情報公開課長'       ← 理事者は職名のみ（氏名なし）
```

- **理事者は職名でしか発言に現れない**ので、名簿レコードの職名↔氏名対応で解決する。名簿は会議ごとにあるため人事異動をまたいでも正しく解ける
- **話者表記は自治体ごとに違う**（練馬「小泉純二委員長」／岡山県「議長（遠藤康洋君）」）。取得層は共通、正規化層は自治体別ルールが要る
- `schedule_id` によって目次と本文が分かれる（大阪市の `schedule_id=1` は索引ページ）
- `body` は `<pre>` で包まれたプレーンテキスト

## 権利

- 根拠は**著作権法40条1項**（公開して行われた政治上の演説・陳述は方法を問わず利用できる）
- **但書に注意**: 「同一の著作者のものを編集して利用する場合を除く」。**議員別に発言を集めて編集する形は抵触しうる**ので、そういう出力を作らない
- 会議録システムの利用規約は著作権とは別レイヤーの契約。**システム共通のテンプレは無く自治体ごとに異なる**（相模原市は「無断で複製や転用することはできません」を掲示、大阪市・岡山県・練馬区には権利表記なし）。取得元ごとに確認する
- 法的な最終判断は専門家確認が要る

## セットアップ

ツールは mise で管理している。

```bash
mise install
bun install
```

## 技術スタック

- Bun + TypeScript
- 配布形式: Popolo 準拠 JSON（リポジトリに commit）+ MCP サーバ

## 参考にする先行事例

| | |
|---|---|
| [ParlParse](https://github.com/mysociety/parlparse) | UK議会のスクレイパ／パーサ。`pyscraper/` `members/` `rawdata/` の分け方と、議員マスタを独立させる設計を借りる |
| [SayIt](https://www.mysociety.org/democracy/sayit/) | 議事録公開の汎用ツール。全文検索・話者フィルタ・**発言単位の permalink**・SEO という機能セットを借りる |
| [Open States / Plural Open](https://open.pluralpolicy.com/) | 米50州の立法データを標準化して無料 API + bulk download で配布 |
