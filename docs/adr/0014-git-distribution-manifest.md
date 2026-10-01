---
status: accepted
---

# 最新の収録一覧と配布先を一つの Git manifest にまとめる

D1 の全体構築版とその公開参照に関する決定は、[ADR 0017](0017-jurisdiction-data-versions.md) の自治体データ版と公開一覧に置き換えた。以下は当時の決定を記録する。共通マスタ・Git manifest・R2 の団体別配布という方針は維持する。

収録範囲と配布物の参照を辿るために catalog と release manifest の両方を読む構造をやめ、Git の `pipeline/publish/manifest.json` 一つに団体・年度・文書・出典・注意点・配布物の版とハッシュをまとめる。Git には最新の一つを置き、過去の一覧は Git 履歴で保持するため、R2 の `releases/` と版一覧は廃止する。R2 は原典・取り込み済みの表・団体別配布物の実体を保存し、D1 は実際の公開状態を管理する。

## Consequences

- Git の採用と公開成功は別であり、API は D1 に記録した公開中の Git commit 固定の manifest URL を返す。Git の最新 manifest が公開前の候補であることもある。
- build が生成する manifest を構築 fingerprint とコード commit の選定から除き、manifest だけの commit が次の manifest を生む循環を防ぐ。採用 manifest を commit してから publish し、候補との内容一致を検査する。
- D1 の全行照合用のハッシュ・件数・合計はローカル `verification.json`、遠隔照合の結果は `publication-verification.json` に残す。非公開 Worker は検査情報を RPC セッションで受け取り、R2 の候補記録を読み書きしない。
- 旧 D1 の即時切り戻しは、保持中の表とローカルの検査済み候補がある間だけ行える。ローカル候補を消した場合は過去の Git と固定入力から再構築する。公開する一覧のために最低3版を保存する要件は廃止し、旧 D1 の保持期間はページングと運用上の猶予として扱う。
