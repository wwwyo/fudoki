# Fiscal Data Package の版と維持状況の実測

「自分で維持する」が既定運用である根拠の実測。測った日付が効く記録なので、
参照するときは再確認すること。

⚠️ **参照先を間違えないこと。** FDP は3箇所に版が散らばっており、古い方を現行と誤読して設計しかけた（実際に2度やった）。

| 版 | 場所 | 位置づけ |
|---|---|---|
| 0.3.0（2016） | `openspending/fiscal-data-package` | **前身**。`measures` / `dimensions` / `granularity` はここだけの語彙 |
| 1.0-rc.1（2018） | `specs.frictionlessdata.io` | 旧（Data Package v1 サイト） |
| **1.0.0** | **`fiscal.datapackage.org`** | **現行**。repo は `frictionlessdata/datapackage-fiscal` |

⚠️ **現行サイトのドメインにありながら中身が旧版のファイルがある。**
`fiscal.datapackage.org/profiles/fiscal-data-package.json` は 1.0.0 の profile ではない（2026-08-23 実測）。
`model`（`measures` / `dimensions`）を required に持っており、これは 1.0.0 が廃止した 0.3 の語彙である。
repo でもこのファイルは 2024-01-05 の bootstrap 以降 1 度も更新されていない。
**1.0.0 に対応する profile JSON は存在しない** — 1.0.0 への適合を機械に検査させる経路が無く、
仕様本文（`/specifications/fiscal-data-package/`）に照らして人が確かめるしかない。

⚠️ **ただし `profile` の値はこれとは別の話である。** `datapackage.json` の
`profile: "tabular-data-package"` は profile JSON が無いための妥協ではなく、**正しい値**である。
FDP の profile は Tabular Data Package を `allOf` で継承しており、継承元の `profile` は
enum で `tabular-data-package` に固定されているので、FDP の URL を入れると継承元に違反する。
**「これは FDP である」を宣言する口は仕様の設計上どこにも無い**ので、
`fudoki.specification` は間に合わせではなく構造的に標準へ寄せられないものにあたる。
⚠️ **この事実は配布物に書かない。** 読んでも利用者のすることは変わらない
（`profile` が何に照らして検査すべきかを既に言っている）ので、fudoki の調査メモにあたる。
配布物に載せるのは「FDP 1.0.0 に沿って作った」という版の宣言（`fudoki.specification`）までで、
`profile` は下層の Tabular Data Package しか言わないため標準フィールドでは代替できない。

⚠️ **採用した3標準のうち2つが止まっている**（最終コミット、2026-08-15 実測）。

| | 最終コミット |
|---|---|
| OCDS | 2026-05-21（現役） |
| Data Package（FDP の下層） | 2026-05-05（現役） |
| **Fiscal Data Package** | **2024-03-28** |
| **Popolo** | **2023-02-13** |
| Akoma Ntoso | 2022-06-02 |

**したがって「止まったら自分で維持する」は保険ではなく既定の運用**として扱う（方針3）。①の粒度を直接狙った現役の代替は調査の結果存在しなかったので、FDP の採用自体は変えない — SDMX は統計集計の交換、IATI は援助フロー、OCDS は調達側からの参照、日本の統一的な基準による地方公会計は発生主義の財務書類で、いずれも予算の事業別明細を対象にしていない。

