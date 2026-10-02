# 公開 R2 の設定

`fudoki-releases` だけを `download.fudoki.dev` へ接続する。原典・取り込み表の bucket は非公開のままにする。設定は `cf` で適用し、認証は mise + age の環境を使う。

`cache-rule.json` は不変の配布パスの CSV/JSON を一年間キャッシュし、404 と 5xx を保存しない。`rate-rule.json` は Free zone の制約に合わせ、`/fiscal/` を IP ごとに 10 秒間で 300 件まで許可し、超過時に 10 秒遮断する。現行の全 82 ファイルの一括取得と転送後の照合を妨げない初期値で、遠隔公開後の観測で調整する。キャッシュ済みのリクエストも数える。zone 内の同じパスにも適用されるため、公開 web/API は `/fiscal/` を使わない。

zone と bucket は同じアカウントに置く。`zone_id`、`cache_ruleset_id`、`rate_ruleset_id` は対象アカウントの実値を使う。

```bash
cf rulesets account-rulesets phases get http_request_cache_settings --zone "$zone_id"
cf rulesets account-rulesets phases get http_ratelimit --zone "$zone_id"
cf r2 buckets domains custom list fudoki-releases
cf r2 buckets cors get fudoki-releases
```

既存の zone ruleset 全体を置き換えない。該当する `ref` が未登録なら以下の rule 作成を使い、登録済みならその rule ID に対する `rules update` を使う。phase の ruleset が存在しない場合だけ、空の entrypoint を `phases update` で作る。Free zone の rate rule 枠が他の用途で埋まっている場合は適用を止め、既存 rule を削除しない。

```bash
cf rulesets account-rulesets rules create "$cache_ruleset_id" --zone "$zone_id" --body @pipeline/publish/cloudflare/cache-rule.json --dry-run
cf rulesets account-rulesets rules create "$rate_ruleset_id" --zone "$zone_id" --body @pipeline/publish/cloudflare/rate-rule.json --dry-run
cf r2 buckets cors update fudoki-releases --body @pipeline/publish/cloudflare/cors.json --dry-run
cf r2 buckets domains managed update fudoki-releases --enabled false --force --dry-run
cf r2 buckets domains custom create fudoki-releases --domain download.fudoki.dev --enabled true --min-tls 1.2 --zone-id "$zone_id" --dry-run
```

dry-run の対象・差分を確認したら同じコマンドから `--dry-run` を外す。CORS は配布専用 bucket の設定全体であり、既存の異なる利用があれば先に整理する。custom domain が登録済みなら `domains custom update` を使う。

旧 download Worker が同じ hostname を使っている場合、R2 ファイルを転送・ハッシュ照合し、上記の設定を適用できる状態にした後で、その Worker の custom domain を外して R2 へ接続する。この間の配信停止は許容する。API のデータ版を切り替える操作ではない。遠隔の Worker 自体は、直接配信の確認後に削除する。

公開後は GET/HEAD、Range、条件付き GET、CORS、全ファイルのハッシュ、404 がキャッシュされないこと、繰り返し取得時の `CF-Cache-Status`、rate rule の適用を確認する。ローカルの R2 adapter では CDN/WAF を再現できないため、この検証は遠隔で行う。

公式の設定仕様: [R2 の公開 bucket](https://developers.cloudflare.com/r2/buckets/public-buckets/)、[Cache Rules](https://developers.cloudflare.com/cache/how-to/cache-rules/settings/)、[rate limit のプラン別制約](https://developers.cloudflare.com/waf/rate-limiting-rules/)。
