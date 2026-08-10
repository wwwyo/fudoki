# sources — 会議録・オープンデータ源の manifest と driver

## manifest.json

東京都62区市町村の会議録システム・オープンデータ源の調査結果。**団体コード（全国地方公共団体コード）を主キー**にする。

```
jurisdictions.<団体コード>
├── name / ocdId
├── transcript      会議録: systemFamily / robots / tenant / entryUrl / confidence
├── openData        東京都カタログ(CKAN)由来: budget / memberRoster / procurement / gikaiDayori
│   └── ownPortal   独自ポータルがある場合: type(ckan|dcat|linkdata|html) / baseUrl
└── status          driver / ingestValidated / published
```

### なぜ `transcript` か

会議録そのものを表す型は **Popolo には無い**（Popolo が定義するのは Speech まで）。会議録＝逐語記録を指す語として、mySociety の **SayIt が使う `transcript`** に合わせた。Akoma Ntoso 系の `debate` も候補だが、委員会記録や要点記録も含む本 PJ の対象には `transcript` の方が広く当たる。

### robots の値

| 値 | 意味 | 団体数 |
|---|---|---|
| `disallow-all` | DB-Search（大和速記情報センター）。トップ以外 Disallow | 23 |
| `tenant-only` | DiscussNetPremium（NTT-AT）。`/tenant/` は Allow、JSON API は Disallow | 13 |
| `allowed` | VOICES/Web・kensakusystem・自治体サイト直 | 23 |
| `unknown` | 未調査（大島町・新島村・青ヶ島村） | 3 |

### 調査の出所

- 会議録システム: [地方議会会議録コーパスプロジェクト](http://local-politics.jp/) の全1,788自治体調査（2020年）を出発点に、2026-08-09 に現況を実測（ホスト移行が多数あった）
- オープンデータ: 東京都カタログ CKAN を `organization:t<団体コード>` で全件取得して分類

## driver

driver は**自治体単位ではなくシステム（ベンダー）単位**で切る。DiscussNetPremium 1本で全国約480自治体をカバーするため。

| driver | 対象 | 状態 |
|---|---|---|
| `dnp` | DiscussNetPremium | 未着手 |
| `voices` | VOICES/Web | 未着手 |
| `kensakusystem` | kensakusystem.jp | 未着手 |
| `dbsearch` | DB-Search | **許諾が取れるまで着手しない** |

## 会議録以外のデータ源

| 種別 | 経路 | 備考 |
|---|---|---|
| 予算・議会だより等 | **CKAN API** | 東京都カタログ / 港区 / BODIK。`isopen` で機械判定可 |
| 同（渋谷区） | **DCAT-US 1.1 フィード** | ArcGIS Hub |
| **調達（入札公告）** | **[官公需情報ポータルサイト 検索API](https://www.kkj.go.jp/api/)** | 中小企業庁・e-Gov API カタログ登録。**`CityCode` が団体コード**、`ProjectDescription` に公告全文。robots 制限なし |

⚠️ 東京電子自治体共同運営（e-tokyo.lg.jp）と東京都電子調達システムは robots が `Disallow: /*/` `/*?*` で全面拒否。**調達は官公需ポータル経由で取る。**
