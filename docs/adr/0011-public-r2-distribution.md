# 0011: 配布物を R2 の独自ドメインから直接配信する

- 日付: 2026-10-01
- 状態: Accepted（実装・遠隔設定は未反映）

採用した入力の証跡の保管先は、後続の [ADR 0012](0012-git-input-provenance.md) で Git に更新した。

配布物は公開データであり、転送中のファイルへのアクセスを Worker で禁止する必要はないため、ADR 0010 の download Worker を R2 の直接配信へ置き換える。既存の `download.fudoki.dev` を公開用 bucket に接続し、Cloudflare のキャッシュとレート制限で過剰なアクセスを抑える。原典・取り込み・証跡、候補 manifest、内部検証結果は非公開 bucket に分け、公開 bucket に置かない。

公開用 manifest は完成した配布版を示す記録とし、HTTP のアクセス制御には使わない。manifest の配置前でも、転送済みファイルの URL を知っていれば取得できる。版一覧は完成後に更新する静的 JSON とし、API/D1 に依存せず一覧から manifest と各ファイルへ辿れるようにする。

独自ドメインは R2 と同じアカウントの Cloudflare zone に接続する。新しい登録ドメインの購入は不要であり、現在の `fudoki.dev` を利用する。キャッシュ・WAF を通らない `r2.dev` の公開入口は無効にする。[R2 の公開 bucket](https://developers.cloudflare.com/r2/buckets/public-buckets/)。

利用者向け URL を既存 web と同じ hostname のパスに揃える場合は Cloud Connector による振り分けも候補になるが、R2 側には同じ zone の独自ドメイン接続が別途必要になる。Beta の振り分け設定と現在の web Worker との共存を検証する必要があるため、初期構成は既存の配布専用 hostname を使う。[Cloud Connector](https://developers.cloudflare.com/rules/cloud-connector/)、[R2 の接続条件](https://developers.cloudflare.com/rules/cloud-connector/providers/#cloudflare-r2)。

CSV・JSON は Cache Rules で明示的にキャッシュ対象にし、固定した版のファイルは長く、更新する版一覧は短く保持する。HTTP の ETag を配布物の SHA-256 と同一視せず、公開前検証では取得した内容と manifest の SHA-256 を照合する。

現在の zone は Free プランであり、レート制限の条件に hostname を指定できないため、配布専用の `/fiscal/` と `/releases/` パスを対象にする。IP ごとの制限値は一括取得と共有 IP の利用を妨げないよう実測で調整し、通常の分析ツールや bot の取得も許容する。レート制限は応答を抑制する手段であり、請求額の上限を保証しない。[レート制限のプラン別機能](https://developers.cloudflare.com/waf/rate-limiting-rules/)。

現行コードと report の ER 図・R2 構造図は download Worker を使う実装を示す。移行では内部オブジェクトを非公開 bucket へ分離し、配信・publish 検証・ローカルの Cloudflare 検証経路を変更してから独自ドメインを接続する。
