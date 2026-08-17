---
name: pipeline-design
description: "fudoki のデータパイプライン（Extract/Load/Transform、raw データの保存形式、開発サーバ起動）を設計・実装するときに踏みがちな非自明な制約。パイプラインの段構成を変える、生データの保存形式を決める、dev サーバを起動する、といった作業の前に参照する。"
---

# パイプライン設計

fudoki の ①予算パイプライン（そして今後の ②③ レイヤ）を設計・実装する際に、過去のセッションで摩擦になった非自明な事実。

- [raw データの git 保存形式](references/raw-data-storage.md) — 単一ファイル vs パーティション分割の git 履歴への影響
- [配布物（正本・派生 CSV）のサイズ膨張](references/distribution-size.md) — 原典比で最大8倍に膨らみ、全団体規模だとGB級になる
- [ELT の段名を独自定義しない](references/elt-terminology.md) — Load/Transform の意味を実装都合で書き換えない
- [dev サーバの起動先](references/dev-server.md) — `.claude/launch.json` は書き込み禁止
