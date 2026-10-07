# docs

設計・調査文書。判断の記録はコードと同じ寿命を持ち、git 管理する。

- `design-principles.md`: 設計方針・対象・パイプライン・パーサ原則
- `survey/`: データ源の実測・調査記録。測った日付が効くので、参照するときは再確認する
- `prd/<topic>/prd.md` + `prd/<topic>/design-doc.md`: 要件と設計書は同じ topic に併置し、その topic の作業記録（移行・回顧・生成一覧）も同じ dir に置く。データ源の実測・調査は `survey/`
- `adr/`: 決定の記録
