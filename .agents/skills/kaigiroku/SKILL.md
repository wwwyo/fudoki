---
name: kaigiroku
description: 会議録検索システム kaigiroku.net（NTT-AT の DiscussNetPremium）から地方議会の会議録を取得するときに参照する。ドキュメント化されていない JSON API の叩き方、tenant_id の調べ方、レスポンスの構造と自治体ごとの差異、取得前に確認する利用規約を扱う。
---

# kaigiroku.net からの会議録取得

`ssp.kaigiroku.net` は NTT-AT の会議録検索システム **DiscussNetPremium** のクラウド版。**477〜492 自治体が同一システムに載っている**ため、ここを1本叩ければ全国の大部分に効く。

公式にドキュメント化されていない JSON API があり、認証・クッキー不要で技術的には `curl` から叩ける。**ただし robots.txt が拒否しているので叩かない。**下記「取得方針」を先に読むこと。

## 取得方針 — robots.txt を尊重する

```
$ curl -s https://ssp.kaigiroku.net/robots.txt
User-agent: *
Disallow: /
Allow: /tenant/
Disallow: /tenant/js/
Disallow: /tenant/css/
Disallow: /tenant/help/
Disallow: /tenant/stats/
```

**JSON API（`/dnp/search/*`）は `Disallow: /` 配下。機械的な取得に使わない。**

取得は `Allow: /tenant/` の画面ページを**ブラウザ相当で描画して解析する**（Firecrawl / headless）。tenant ページは空テンプレートで本文は JS が API から取るため、静的 HTML の取得では中身が得られない。

⚠️ 描画しても裏で同じ API を呼ぶことになり、静的アセットも取るぶんサーバ負荷はむしろ重い。**「人間の閲覧と同等のレートで、許可されたページを見る」以上の正当化はしない。** 同時実行数を絞る／取得済みはスキップする／429・5xx で停止する／連絡先入りの User-Agent を使う。

**恒久的な解決は許諾**（議会事務局＝本文の再利用許諾、NTT-AT＝自動アクセスの可否）。許諾が取れれば API を直接使う方が軽く速く、相手にも優しい。

以下の API 仕様は、**許諾取得後に使うため／レスポンス構造を理解するための参照**として残す。少数の fixture 作成や仕様調査には使えるが、全量クロールには使わない。

## テナントと tenant_id

各自治体は `https://ssp.kaigiroku.net/tenant/<name>/` のテナントとして載っている。API に渡す `tenant_id` は、そのテナントの JS に平文で置かれている。

```bash
curl -s https://ssp.kaigiroku.net/tenant/nerima/js/tenant.js
# => dnp.params.tenant_id = 367
```

確認済み: 練馬区 367 / 大阪市 357 / 岡山県 455 / 大分県 499 / 久慈市 121。

**導入していない自治体はテナント URL が 404 を返す**ので、対象を広げるときは最初にこれで足切りする。東京の区市は未導入が多い（実測: 練馬区 200、品川区・世田谷区・杉並区・町田市・狛江市は 404）。

```bash
for t in nerima shinagawa machida; do
  printf "%-12s " "$t"
  curl -sL -o /dev/null -w "%{http_code}\n" "https://ssp.kaigiroku.net/tenant/$t/pg/index.html"
done
```

## エンドポイント

API root は `https://ssp.kaigiroku.net/dnp/search/`。全一覧は `https://ssp.kaigiroku.net/tenant/js/release/config.js` の `dnp.config.APIS` にある。

| endpoint | 用途 |
|---|---|
| `councils/index` | 会議の一覧（年度 → 会議種別 → 会議） |
| `councils/view` / `councils/get_view_years` | 会議の詳細 / 収録年度 |
| **`minutes/get_minute`** | **会議録本文** |
| `minutes/get_index` / `get_index_list` | 目次 |
| `minutes/get_schedule` / `get_schedule_all` | 日程（schedule_id の一覧） |
| `minutes/get_material_list` / `download` | 資料 |
| `speakers/get_council_speakers` | 会議の発言者一覧 |
| `speaker_collects/autogenerate` / `download` | 発言者別の収集 |
| `minute_searches/search` / `get_search_options` | 検索 |
| `cross_searches/search` | 横断検索 |
| `document_minings/get_associations` / `search_similar_sentence` | 関連語・類似文 |
| `rankings/get_ranking_words` / `get_ranking_cross` | 単語ランキング |

ブラウザからは JSONP（`?callback=...`）で呼ばれているが、**`callback` を付けなければ素の JSON が返る**。

## 呼び方

いずれも POST、`application/x-www-form-urlencoded`。

```bash
# 会議一覧。tenant_id だけで全年度返る（練馬区で約1.1MB、昭和22年〜令和8年）
curl -s -X POST https://ssp.kaigiroku.net/dnp/search/councils/index \
  --data "tenant_id=367"

# 会議録本文
curl -s -X POST https://ssp.kaigiroku.net/dnp/search/minutes/get_minute \
  --data "tenant_id=367&council_id=5717&schedule_id=1"
```

⚠️ `councils/index` に `view_years=2026` を付けると **500 を返すテナントがある**（練馬では通るが大阪市・岡山県・久慈市では落ちる）。**bare な `tenant_id` だけで呼び、年度の絞り込みはクライアント側でやる**のが安全。

### councils/index のレスポンス

```
councils[].view_years[]           view_year("2026") / japanese_year("令和8年")
  └ council_type[]                council_type_path("/0/1/4/8/11/")
                                  council_type_name1..5（全会議 > 委員会 > 常任委員会 > 企画総務委員会）
      └ councils[]                council_id / name / postit_count
```

`council_type_path` が会議体の階層を表す。`council_type_name*` は使われない階層が `null` になる。

## minutes/get_minute のレスポンス — ここが重要

`tenant_minutes[]` を返す。**多くの自治体で既に発言単位に分割されており、`title` が話者になっている**。発言分割も話者抽出も自前で書かなくてよい（ParlParse が自前でやっている工程が丸ごと不要）。

練馬区・企画総務委員会（令和8年6月16日）で 104 レコード:

```
minute_id=1   title='（名簿）'               出席委員・出席理事者の職名↔氏名
minute_id=3   title='小泉純二委員長'          議員は 氏名+役職
minute_id=5   title='１第二回定例会付託案件'   議題見出し
minute_id=13  title='情報公開課長'            理事者は 職名のみ（氏名なし）
```

各レコードは `minute_id` / `title` / `page_no` / `hit_count` / `body`。`body` は `<pre>` で包まれたプレーンテキスト。

### 落とし穴

- **理事者は職名でしか発言に現れない。** 人に紐づけるには**名簿レコード（通常 `minute_id=1`）の職名↔氏名対応**を使う。名簿は会議ごとに付くので、人事異動をまたいでも会議単位で正しく解決できる
- **話者の表記は自治体ごとに違う。** 練馬区は `小泉純二委員長`、岡山県は `議長（遠藤康洋君）`。**取得層は共通、正規化層は自治体別ルールが要る**
- **`schedule_id` によって目次と本文が分かれる。** 大阪市の `schedule_id=1` は索引ページで、`tenant_minutes` が1件（`title` が `null`、本文に目次が入る）しか返らない。**レコードが1件だけのときは「分割されていない」と決めつけず、`minutes/get_schedule_all` で他の schedule を確認する**
- 名簿には出席委員・出席理事者に加えて**開催日時・場所・傍聴者数・付託案件（議案第◯号）**が入る。工事請負契約などの調達案件もここに並ぶ

## 取得前に確認すること

**会議録の再利用そのものは著作権法40条1項**（公開して行われた政治上の演説・陳述は方法を問わず利用できる）が根拠になる。ただし**但書「同一の著作者のものを編集して利用する場合を除く」**があり、**議員別に発言を集めて編集した成果物は抵触しうる**。

これとは別レイヤーで、**各議会が自分のテナントに利用規約を掲げていることがある**。システム共通のテンプレではなく自治体ごとに異なるので、対象を追加するたびに確認する。

- 相模原市は index に「このデータの権利は、相模原市議会に帰属します。『私用のための複製』や『引用』など著作権法上認められた場合を除き、許可なく無断で複製や転用することはできません」を掲示
- 大阪市・岡山県・練馬区には権利表記なし（練馬は「設定」メニューの中身まで確認したが、色変更・履歴・文字サイズ・ヘルプの操作系のみで規約項目自体が存在しない）

テナントのトップは JS レンダリングなので、**静的 HTML の grep では判定できない**。ブラウザで描画して確認する。

法的な最終判断は専門家確認が要る。

## 調べ方（新しいエンドポイントやパラメータが要るとき）

1. ブラウザで対象ページを開き、ネットワークから `/dnp/search/` への POST を拾う
2. パラメータ名は**画面遷移後の URL クエリに出ている**ことが多い（例: `SpMinuteView.html?power_user=false&tenant_id=367&council_id=5717&schedule_id=1&view_years=2026`）
3. アプリの HTML ページ名一覧は `config.js` にある（`MinuteView.html` `MinuteSearch.html` `CrossSearch.html` `SpeakerCollect.html` など）
