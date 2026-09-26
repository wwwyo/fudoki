# 3本の標準（FDP・OCDS・Popolo）を使い分ける

守備範囲（何にいくら／いつ何が公告されたか／どう決まったか）は1本の標準に収まらないので、レイヤーごとに Fiscal Data Package・OCDS・Popolo を使い分け、継ぎ目も標準が規定した場所（OCDS `planning.budget.uri`、Popolo の Motion/Vote）で繋ぐ。独自スキーマは発明しない。

## Considered Options

- 単一標準に全て載せる — Popolo は財政の語彙を持たず、予算側を載せると必ず独自拡張になる
- FDP 以外の予算用標準（SDMX は統計集計の交換、IATI は援助フロー、日本の統一的な基準による地方公会計は発生主義の財務書類） — いずれも予算の事業別明細を対象にしていない
