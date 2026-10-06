# pipeline skill 保守規約

- load order: SKILL.md（Routing table）→ 全体確認なら references/workflow.md → 作業する工程の reference のみ
- validation: 現行コード・実行記録で確認した手順と、ユーザーが合意した保存境界を記録する。失敗例は観測した範囲を明記し、未解決を解消済みに変えない。未実装の改善案を現行手順として書かず、未確立の部分を推測で埋めない。現行コードと矛盾する記述は根拠つきで更新・削除する
- scope: 各工程の入力・作業・保存先・検査・次工程へ渡せる範囲を references/ に置く。団体固有の実測値は取り込みノート、設計は既存の設計書、実行コマンドはコードと pipeline/README.md を参照する。最新の入力件数や構築IDをskillへ固定しない
- governance: このスキルは `session-retro` が維持する個人の学び skill。追記は session-retro の自動実行フロー、または対話中の明示的な指示によって行う。他人・チームの skill ではないため、重複・陳腐化エントリの整理は自由に行ってよい
