# 東京都62区市町村 データ源調査（2026-08-09 実測）

東京都オープンデータカタログ（CKAN）を団体コードで横断し、予算・決算データを調べた。リンクは代表リソース（CSV優先）。

- **すべて CC-BY-4.0**（東京都カタログ全9,648件中9,645件が CC BY）

## 調達は自治体別ではなく共同システム

**[東京電子自治体共同運営 電子調達サービス](https://www.e-tokyo.lg.jp/)** に 23区+26市+4町+3村＝**56自治体**が参加。東京都本体は[東京都電子調達システム](https://www.e-procurement.metro.tokyo.lg.jp/)。

**driver は1本で56自治体に効く。**ただし robots は両方 `Disallow: /*/` ＋ `Disallow: /*?*` ＝ **実質全ページ拒否**。

CKAN 上で調達データを個別公開しているのは**練馬区のみ**（調達情報 XLSX 28 + CSV 6・随意契約の締結状況）。

## 一覧

| コード | 自治体 | 予算・決算 | OD総数 |
| --- | --- | --- | --- |
| 131016 | 千代田区 | — | 29 |
| 131024 | 中央区 | — | 47 |
| 131032 | 港区 | — | 268 |
| 131041 | 新宿区 | — | 137 |
| 131059 | 文京区 | [ZIP（他1件）](https://www.city.bunkyo.lg.jp/documents/6059/yosansokatsuhyo_excel.zip) | 57 |
| 131067 | 台東区 | — | 187 |
| 131075 | 墨田区 | — | 199 |
| 131083 | 江東区 | — | 97 |
| 131091 | 品川区 | — | 139 |
| 131105 | 目黒区 | [XLSM/XLSX](https://data.bodik.jp/dataset/498accc5-4a1b-44e1-b9df-29e9dd722107/resource/4b39cdc0-0a27-4d0b-a343-4c3f535e6026/download/131105_2011_zaiseijokyoshiryo.xlsx) | 186 |
| 131113 | 大田区 | [XLSX（他21件）](https://www.opendata.metro.tokyo.lg.jp/ota/R6/131113_R6_108_ootakudetagaiyou_reiwa5nendoippankaikeinokessangaku.xlsx) | 278 |
| 131121 | 世田谷区 | — | 25 |
| 131130 | 渋谷区 | — | 17 |
| 131148 | 中野区 | — | 167 |
| 131156 | 杉並区 | [CSV（他3件）](https://www.city.suginami.tokyo.jp/documents/18016/sainyu.csv) | 103 |
| 131164 | 豊島区 | — | 32 |
| 131172 | 北区 | — | 7 |
| 131181 | 荒川区 | — | 33 |
| 131199 | 板橋区 | — | 211 |
| 131202 | 練馬区 | [XLS/XLSX（他7件）](https://www.city.nerima.tokyo.jp/kusei/tokei/opendata/opendatasite/tokei_kusei/hikaku.files/h25_hikaku.xlsx) | 79 |
| 131211 | 足立区 | — | 10 |
| 131229 | 葛飾区 | — | 32 |
| 131237 | 江戸川区 | — | 266 |
| 132012 | 八王子市 | [PDF](https://www.city.hachioji.tokyo.jp/contents/open/002/p005883_d/fil/h24sainyuu.pdf) | 78 |
| 132021 | 立川市 | — | 35 |
| 132039 | 武蔵野市 | — | 24 |
| 132047 | 三鷹市 | [PDF（他3件）](https://www.city.mitaka.lg.jp/c_service/078/attached/attach_78398_1.pdf) | 32 |
| 132055 | 青梅市 | — | 51 |
| 132063 | 府中市 | — | 35 |
| 132071 | 昭島市 | — | 20 |
| 132080 | 調布市 | [XLS（他38件）](https://www.city.chofu.lg.jp/documents/16704/6_05_040.xls) | 1487 |
| 132098 | 町田市 | [PDF（他2件）](https://www.city.machida.tokyo.jp/shisei/opendata/zaiseizeimu/sainyusaishutsukessansho.files/2020_kessansho.pdf) | 127 |
| 132101 | 小金井市 | — | 50 |
| 132110 | 小平市 | — | 21 |
| 132128 | 日野市 | — | 30 |
| 132136 | 東村山市 | — | 45 |
| 132144 | 国分寺市 | — | 25 |
| 132152 | 国立市 | — | 29 |
| 132187 | 福生市 | — | 13 |
| 132195 | 狛江市 | [CSV（他27件）](https://www.opendata.metro.tokyo.lg.jp/komae/R05/132195_R5futukaikei26hikaku.csv) | 399 |
| 132209 | 東大和市 | — | 24 |
| 132217 | 清瀬市 | — | 64 |
| 132225 | 東久留米市 | — | 21 |
| 132233 | 武蔵村山市 | — | 14 |
| 132241 | 多摩市 | [PDF（他19件）](https://www.city.tama.lg.jp/_res/projects/default_project/_page_/001/002/458/29gesui_financial_statements.pdf) | 61 |
| 132250 | 稲城市 | — | 17 |
| 132276 | 羽村市 | — | 27 |
| 132284 | あきる野市 | — | 25 |
| 132292 | 西東京市 | — | 37 |
| 133035 | 瑞穂町 | — | 10 |
| 133051 | 日の出町 | — | 13 |
| 133078 | 檜原村 | — | 3 |
| 133086 | 奥多摩町 | — | 4 |
| 133612 | 大島町 | — | 2 |
| 133621 | 利島村 | — | 10 |
| 133639 | 新島村 | — | 4 |
| 133647 | 神津島村 | — | 0 |
| 133817 | 三宅村 | — | 2 |
| 133825 | 御蔵島村 | — | 4 |
| 134015 | 八丈町 | — | 14 |
| 134023 | 青ヶ島村 | — | 2 |
| 134210 | 小笠原村 | — | 10 |
