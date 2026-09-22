# 東京都62区市町村 データ源調査（2026-08-09 実測）

出発点は[地方議会会議録コーパスプロジェクト](http://local-politics.jp/)の全1,788自治体調査（2020年・団体コード付き）。ホスト移行が多いため現況を叩き直し、東京都オープンデータカタログ（CKAN）を団体コードで横断した。

- 会議録システム = 2020年調査のホストから判定したベンダーファミリー
- robots = ✗ 取得不可 ／ △ 条件付き ／ ○ 取得可 ／ ? 未調査
- 予算・議員名簿・議会だよりは CKAN の各自治体オーガニゼーション（`organization:t<団体コード>`）配下を全件取得して分類。リンクは代表リソース（CSV優先）
- **すべて CC-BY-4.0**（東京都カタログ全9,648件中9,645件が CC BY）

## 調達は自治体別ではなく共同システム

**[東京電子自治体共同運営 電子調達サービス](https://www.e-tokyo.lg.jp/)** に 23区+26市+4町+3村＝**56自治体**が参加。東京都本体は[東京都電子調達システム](https://www.e-procurement.metro.tokyo.lg.jp/)。

**driver は1本で56自治体に効く。**ただし robots は両方 `Disallow: /*/` ＋ `Disallow: /*?*` ＝ **実質全ページ拒否**。

CKAN 上で調達データを個別公開しているのは**練馬区のみ**（調達情報 XLSX 28 + CSV 6・随意契約の締結状況）。

## 一覧

| コード | 自治体 | 会議録システム | robots | 予算・決算 | 議員名簿 | 議会だより | OD総数 |
|---|---|---|---|---|---|---|---|
| 131016 | 千代田区 | DB-Search | ✗ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/chiyoda/131016_chiyodaku_gikaidayori.csv) | 29 |
| 131024 | 中央区 | 自治体サイト/その他 | ○ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/chuo/131024_chuoku_gikaidayori.csv) | 47 |
| 131032 | 港区 | DB-Search | ✗ | — | — | — | 268 |
| 131041 | 新宿区 | DNP | △ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/shinjyuku/131041_shinjyukuku_gikaidayori.csv) | 137 |
| 131059 | 文京区 | DB-Search | ✗ | [ZIP（他1件）](https://www.city.bunkyo.lg.jp/documents/6059/yosansokatsuhyo_excel.zip) | — | — | 57 |
| 131067 | 台東区 | VOICES | ○ | — | — | — | 187 |
| 131075 | 墨田区 | DNP | △ | — | — | — | 199 |
| 131083 | 江東区 | DB-Search | ✗ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/koto/131083_kotoku_gikaidayori.csv) | 97 |
| 131091 | 品川区 | DB-Search | ✗ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/shinagawa/131091_shinagawaku_gikaidayori.csv) | 139 |
| 131105 | 目黒区 | kensakusystem | ○ | [XLSM/XLSX](https://data.bodik.jp/dataset/498accc5-4a1b-44e1-b9df-29e9dd722107/resource/4b39cdc0-0a27-4d0b-a343-4c3f535e6026/download/131105_2011_zaiseijokyoshiryo.xlsx) | — | [CSV（他1件）](https://data.bodik.jp/dataset/3261f592-309b-47ff-8fee-bb34cbeff6f0/resource/217003c1-2600-4280-b004-18d1a43fe552/download/131105_gikaidayori.csv) | 186 |
| 131113 | 大田区 | VOICES | ○ | [XLSX（他21件）](https://www.opendata.metro.tokyo.lg.jp/ota/R6/131113_R6_108_ootakudetagaiyou_reiwa5nendoippankaikeinokessangaku.xlsx) | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/ota/131113_otaku_gikaidayori.csv) | 278 |
| 131121 | 世田谷区 | 自治体サイト/その他 | ○ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/setagaya/131121_setagayaku_gikaidayori.csv) | 25 |
| 131130 | 渋谷区 | DNP | △ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/shibuya/131130_shibuyaku_gikaidayori.csv) | 17 |
| 131148 | 中野区 | 自治体サイト/その他 | ○ | — | — | [CSV](https://www2.wagmap.jp/nakanodatamap/nakanodatamap/opendatafile/map_1/CSV/opendata_57001289.csv) | 167 |
| 131156 | 杉並区 | VOICES | ○ | [CSV（他3件）](https://www.city.suginami.tokyo.jp/documents/18016/sainyu.csv) | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/suginami/131156_suginamiku_gikaidayori.csv) | 103 |
| 131164 | 豊島区 | kensakusystem | ○ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/toshima/131164_toshimaku_gikaidayori.csv) | 32 |
| 131172 | 北区 | DNP | △ | — | — | — | 7 |
| 131181 | 荒川区 | DNP | △ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/arakawa/131181_arakawaku_gikaidayori.csv) | 33 |
| 131199 | 板橋区 | DB-Search | ✗ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/itabashi/131199_itabashiku_gikaidayori.csv) | 211 |
| 131202 | 練馬区 | DNP | △ | [XLS/XLSX（他7件）](https://www.city.nerima.tokyo.jp/kusei/tokei/opendata/opendatasite/tokei_kusei/hikaku.files/h25_hikaku.xlsx) | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/nerima/131202_nerimaku_gikaidayori.csv) | 79 |
| 131211 | 足立区 | 自治体サイト/その他 | ○ | — | — | — | 10 |
| 131229 | 葛飾区 | kensakusystem | ○ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/katsushika/131229_katsushikaku_gikaidayori.csv) | 32 |
| 131237 | 江戸川区 | VOICES | ○ | — | — | — | 266 |
| 132012 | 八王子市 | DB-Search | ✗ | [PDF](https://www.city.hachioji.tokyo.jp/contents/open/002/p005883_d/fil/h24sainyuu.pdf) | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/hachioji/132012_hachiojishi_gikaidayori.csv) | 78 |
| 132021 | 立川市 | DNP | △ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/tachikawa/132021_tachikawashi_gikaidayori.csv) | 35 |
| 132039 | 武蔵野市 | DB-Search | ✗ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/musashino/132039_musashinoshi_gikaidayori.csv) | 24 |
| 132047 | 三鷹市 | DB-Search | ✗ | [PDF（他3件）](https://www.city.mitaka.lg.jp/c_service/078/attached/attach_78398_1.pdf) | — | [CSV](https://www.city.mitaka.lg.jp/c_service/111/attached/attach_111857_1.csv) | 32 |
| 132055 | 青梅市 | DNP | △ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/ome/132055_omeshi_gikaidayori.csv) | 51 |
| 132063 | 府中市 | DB-Search | ✗ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/fuchu/132063_fuchushi_gikaidayori.csv) | 35 |
| 132071 | 昭島市 | DNP | △ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/akishima/132071_akishimashi_gikaidayori.csv) | 20 |
| 132080 | 調布市 | VOICES | ○ | [XLS（他38件）](https://www.city.chofu.lg.jp/documents/16704/6_05_040.xls) | — | — | 1487 |
| 132098 | 町田市 | VOICES | ○ | [PDF（他2件）](https://www.city.machida.tokyo.jp/shisei/opendata/zaiseizeimu/sainyusaishutsukessansho.files/2020_kessansho.pdf) | [CSV/PDF](https://www.city.machida.tokyo.jp/shisei/opendata/senkyo/giinmeibo.files/giinmeibo.csv) | [CSV](https://www.opendata.metro.tokyo.lg.jp/machida/132098_machidashi_gikaidayori.csv) | 127 |
| 132101 | 小金井市 | DB-Search | ✗ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/koganei/132101_gikaidayori.csv) | 50 |
| 132110 | 小平市 | DNP | △ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/kodaira/132110_kodairashi_gikaidayori.csv) | 21 |
| 132128 | 日野市 | DB-Search | ✗ | — | — | — | 30 |
| 132136 | 東村山市 | 自治体サイト/その他 | ○ | — | — | — | 45 |
| 132144 | 国分寺市 | DB-Search | ✗ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/kokubunji/132144_kokubunjishi_gikaidayori.csv) | 25 |
| 132152 | 国立市 | DB-Search | ✗ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/kunitachi/132152_kunitachishi_gikaidayori.csv) | 29 |
| 132187 | 福生市 | DB-Search | ✗ | — | — | — | 13 |
| 132195 | 狛江市 | DB-Search | ✗ | [CSV（他27件）](https://www.opendata.metro.tokyo.lg.jp/komae/R05/132195_R5futukaikei26hikaku.csv) | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/komae/132195_komaeshi_gikaidayori.csv) | 399 |
| 132209 | 東大和市 | 自治体サイト/その他 | ○ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/higashiyamato/132209_higashiyamatoshi_gikaidayori.csv) | 24 |
| 132217 | 清瀬市 | DNP | △ | — | — | [HTML](https://www.city.kiyose.lg.jp/opendata/opendata/opendataichiran/1014942.html) | 64 |
| 132225 | 東久留米市 | DB-Search | ✗ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/higashikurume/132225_higashikurumeshi_gikaidayori.csv) | 21 |
| 132233 | 武蔵村山市 | DNP | △ | — | — | — | 14 |
| 132241 | 多摩市 | DB-Search | ✗ | [PDF（他19件）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/002/458/29gesui_financial_statements.pdf) | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/tama/132241_tamashi_gikaidayori.csv) | 61 |
| 132250 | 稲城市 | DB-Search | ✗ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/inagi/132250_inagishi_gikaidayori.csv) | 17 |
| 132276 | 羽村市 | DB-Search | ✗ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/hamura/132276_hamurashi_gikaidayori.csv) | 27 |
| 132284 | あきる野市 | DB-Search | ✗ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/akiruno/132284_akirunoshi_gikaidayori.csv) | 25 |
| 132292 | 西東京市 | DB-Search | ✗ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/nishitokyo/132292_nishitokyoshi_gikaidayori.csv) | 37 |
| 133035 | 瑞穂町 | DNP | △ | — | — | — | 10 |
| 133051 | 日の出町 | DB-Search | ✗ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/hinode/133051_hinodemachi_gikaidayori.csv) | 13 |
| 133078 | 檜原村 | 自治体サイト/その他 | ○ | — | — | — | 3 |
| 133086 | 奥多摩町 | 自治体サイト/その他 | ○ | — | — | — | 4 |
| 133612 | 大島町 | 自治体サイト/その他 | ? | — | — | — | 2 |
| 133621 | 利島村 | 自治体サイト/その他 | ○ | — | — | — | 10 |
| 133639 | 新島村 | 自治体サイト/その他 | ? | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/niijima/133639_niijimamura_gikaidayori.csv) | 4 |
| 133647 | 神津島村 | 自治体サイト/その他 | ○ | — | — | — | 0 |
| 133817 | 三宅村 | 自治体サイト/その他 | ○ | — | — | — | 2 |
| 133825 | 御蔵島村 | 自治体サイト/その他 | ○ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/mikurajima/133825_mikurajimamura_gikaidayori.csv) | 4 |
| 134015 | 八丈町 | 自治体サイト/その他 | ○ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/hachijo/134015_hachijomachi_gikaidayori.csv) | 14 |
| 134023 | 青ヶ島村 | 自治体サイト/その他 | ? | — | — | — | 2 |
| 134210 | 小笠原村 | 自治体サイト/その他 | ○ | — | — | [CSV](https://www.opendata.metro.tokyo.lg.jp/ogasawara/134210_ogasawaramura_gikaidayori.csv) | 10 |
