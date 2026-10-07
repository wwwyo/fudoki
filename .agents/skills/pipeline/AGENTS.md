# pipeline skill 保守規約

- load order: SKILL.md（Routing table）→ 全体確認なら references/workflow.md → 作業する工程の reference のみ
- validation: 現行コードの説明は実行記録と照合し、失敗例は観測した範囲を明記する。ユーザーが合意した目標手順は現行実装と区別して記録し、未実装を実装済みと扱わない。Aの `references/source-selection.md` は目標手順であり、現行コードに合わせて書き戻さない。未解決を解消済みに変えず、未確立の部分を推測で埋めない。現行コードを説明する記載の矛盾は根拠つきで更新・削除する
- scope: 各工程のワークフロー・ツールの使い方を references/ に置く。データ構造・スキーマ・型定義はコードを正本とし、skillには参照だけを置く。団体固有の実測値は取り込みノート、設計は既存の設計書、実行コマンドはコードと pipeline/README.md を参照する。最新の入力件数や構築IDをskillへ固定しない
- improvement: workflow の全ステップで、失敗したら原因を確認して手順・ツールの使い方を改善し、他の対象にも使える形に汎用化して該当する skill の reference に反映する。個別事例の経緯を積み増さず、再発を防ぐ実行手順として残す
- governance: このスキルは `session-retro` が維持する個人の学び skill。追記は session-retro の自動実行フロー、または対話中の明示的な指示によって行う。他人・チームの skill ではないため、重複・陳腐化エントリの整理は自由に行ってよい
