# sources — 会議録・オープンデータ源の manifest と driver

## manifest.json

東京都62区市町村の会議録システム・オープンデータ源の調査結果。**団体コード（全国地方公共団体コード）を主キー**にする。

```
jurisdictions.<団体コード>
├── name / ocdId
├── transcript      会議録: systemFamily / robots / gate / tenant / entryUrl / confidence
├── openData        東京都カタログ(CKAN)由来: budget / memberRoster / procurement / gikaiDayori
│   └── ownPortal   独自ポータルがある場合: type(ckan|dcat|linkdata|html) / baseUrl
└── status          driver / ingestValidated / published
```

### なぜ `transcript` か

会議録そのものを表す型は **Popolo には無い**（Popolo が定義するのは Speech まで）。会議録＝逐語記録を指す語として、mySociety の **SayIt が使う `transcript`** に合わせた。Akoma Ntoso 系の `debate` も候補だが、委員会記録や要点記録も含む本 PJ の対象には `transcript` の方が広く当たる。

### robots と gate

**取得（fetch）と再配布（redistribute）は別のゲートで判断する。**取得してよいこと（robots・技術的到達性）と、正規化して公開してよいこと（著作権・利用規約）は別問題で、混ぜると「robots がクリアだから公開してよい」という誤りになる。

`gate.fetch` / `gate.redistribute` はいずれも `allow` / `review` / `deny` の3値。理由は `gate.constraints[]` に列挙する（`policy.constraints` が語彙の定義）。

| `fetch` | 意味 | 団体数 |
|---|---|---:|
| `allow` | 判断が済んでいて取得してよい | 17 |
| `review` | 未確定。照会が通るまで取得しない | 16 |
| `deny` | 構造的に不可、または方針として取得しない | 29 |

`redistribute` は現在 **`allow` が0団体**。著作権法40条1項を主要な候補根拠としているが、発言種別・会議の公開性・非発言部分・配布形態の確認が済んでいない。

**robots.txt の原文は manifest に持たない。**`data/observations/robots.json` が single source of truth で、manifest 側は `robots.observation` として取得 URL・HTTP status・SHA-256・取得時刻だけを参照する。要約を manifest に持つと RFC 9309 準拠の再判定ができなくなるため。原文は `bun run fetch:robots -- --write` で取り直せる。

SHA-256 が一致することで「ベンダーごとに robots が一様」は主張ではなく事実になっている — dbsr.jp の22ホストが同一の75バイト、VOICES の4ホストが同一の1621バイト。

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
