# Cloudflare ゾーン設定のハマりどころ

- **Browser Integrity Check（BIC）は Bot Fight Mode とは別機能で、既定で ON になっている。** UA 署名ベースの拒否リストを持ち、Python 標準ライブラリ `urllib` の既定 UA（`Python-urllib/x.y`）を弾く（`error code: 1010`）。`python-requests` や UA 無しのリクエストは通るため、切り分け時は「Bot Fight Mode を疑う」より先に Security → Settings → Browser Integrity Check の状態を見る。
  - Why: BIC は「ブラウザらしさ」を UA 等のヘッダ署名で判定する仕組みで、非ブラウザ UA を機械的にブロックする。認証なし・公開データを配る読み取り専用 API では、クライアントがブラウザでないのが正常なので、この判定そのものが前提から成り立たない。
  - How to apply: `api.fudoki.dev` のように非ブラウザクライアント（スクリプト・MCP・別サーバ）からのアクセスを想定する公開 API ゾーンでは BIC を OFF にする。ダッシュボードの Configuration Rules でサブドメイン単位に絞る手もあるが、無料プランでもフォームは使えるものの、Browser 経由の自動操作（座標クリック中心の操作）は描画のずれで安定しないことがあった。ゾーン全体トグルの方が確実。
