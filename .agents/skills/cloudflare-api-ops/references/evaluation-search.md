# 事業の評価の検索（search_evaluations）の運用

設計は `docs/prd/evaluation-search/dd.md`。実装は `apps/api/src/evaluations.ts` と `evaluation-quota.ts`。

- **止める・上限を変える（デプロイ不要）**: D1 の `control` 表の値を更新する。`evaluation_search`（`on` 以外・行が無いなら評価の検索だけ 503。初期値 `off`）、`evaluation_search_per_minute`（既定 30）、`evaluation_search_per_day`（既定 1000）は全利用者の合計。上限の値が無い・正の整数でないときは 503（閉じる側）。Worker は検索のたびに読むので、更新はすぐ効く。
  - How to apply: 公開の直後に `per_day` を小さくして 429 が返ることを確かめ、値を戻す。`serving` が `off` なら評価の検索も止まる。
- **migration は自動で適用されない**: `apps/api/migrations/0002_evaluation_search.sql` は `control` に 3 行を足すだけ。本番の D1 への適用は手動で、適用前に `evaluation_search` の行が無いので評価の検索は 503。
- **索引の built-in storage でも 6 時間ごとの同期が走る（2026-10-14 実測）**: `source: null`（built-in storage）でも `Scheduled sync` が走り、変更の無い item まで `queued` に戻して `File reindexed successfully` を記録する。公式文書の「built-in storage には同期ジョブが無い」と食い違うので、`items list` の `queued` を異常と読まない。再処理を避けたいときは `sync_interval` を 86400 に延ばす。**`paused: true` は新規アップロードの取り込みまで止める**（5分待っても queued のまま）ので、同期だけを止める目的で pause を使わない。
- **回数は検索の前に数える**: Durable Object `EvaluationSearchQuota` が UTC の分と日の固定の窓で数え、storage に書いてから AI Search を呼ぶ。失敗・時間切れの検索も数え、拒んだ要求は数えない。上限の値は DO ではなく `control` に置くので、数え直しはせず値で調整する。
- **遅いときは埋め込みを疑う（2026-10-20 実測、ADR 0033）**: v1（`qwen3-embedding-0.6b`）は本番の検索の4件に1件が8秒の打ち切りに届いた。Worker の中は中央値82ms で、AI Search の中でも keyword 単独は0.5秒、vector 単独が2.5秒（最大8秒超）だった。同じモデルを `cf ai run` で直接呼ぶと検索文1つの埋め込みが最大20秒で、時間帯ではなく1回ごとに裾が重い。索引の大きさは主因ではない（246 item の頃も2〜6秒）。
  - How to apply: 切り分けは Workers Observability の log の `ms` と DO `POST /take` の開始時刻・wallTime を traceId で突き合わせる（span は無効）。広い期間の events は標本になるので1時間ずつ引く。AI Search の中は `retrieval_type` を vector・keyword に分けて直接引き、埋め込みは `cf ai run <model>` で別に測る。AI Gateway のログには AI Search の埋め込みは残らない。
- **`cf ai-search search` の `--body` は位置引数の query を上書きする**: body に `query` が無いと 400（`One of 'messages' or 'query' must be provided`）、位置引数が無いと CLI が help を出して止まる（API に届かない）。query は両方に入れる。
- **AI Search の binding は中断できない**: `search(params)` に timeout も `AbortSignal` も無い。Worker は 8 秒で応答だけを打ち切り（503）、検索は裏で続き得る。
- **本文が空になる出典は頁の文字を `.md` の item にする（ADR 0031）**: 埋め込みの無い CID フォント（`UniJIS-UCS2-HW-H`・`UniJIS-UTF16-H`、ToUnicode なし）の PDF は、AI Search の変換後が1〜5字になる（手元では2,000字前後）。頁の PDF に ToUnicode を足しても2字のままで効かなかった（2026-10-19 実測）。出典ごとに config（`instance.json` の `text_origins`）で宣言し、pdfium で抜き出した頁の文字を `<origin_sha256>_p<頁4桁>.md` の item として登録する（2026-10-19 に60出典を登録し直した）。
- **新しいインスタンスは `file_content_empty` を多く出す（2026-10-20〜21、v2、ADR 0033）**: v1 では completed だった頁が、v2 では頁の PDF で172頁（72出典）、見出しの無い md でも和文の65頁と文字の無い54頁が `error: file_content_empty` になった。送り直しても、key を変えても同じ頁が落ちる。中身の何が引き金かは特定できていない（ASCII の割合が低い頁に多いが、それだけでは決まらない）。
  - How to apply: 頁の PDF で落ちた出典は `text_origins` に足して md にする。md は頁の PDF の変換と同じ見出し（`# <key>`・`## Contents`・`### Page 1`）を付けて送ると取り込まれる（`index.py` の `text_item`、Worker の `stripHeader` が見出しを除く）。それでも落ちた調布市の1頁は本文を NFKC にそろえると通ったので、その出典だけ `nfkc_origins` に宣言した。
- **`text_origins` に足すと、その出典の pdf の item を1件ずつ消す**: 削除は 429・timeout が続き、3,928件に約7時間かかった（2026-10-21）。消し損ねは「余分」になり、次の実行で消し直す。
- **全件の一覧は1回10分〜1時間半かかる**: `items list` は50件ずつなので、4万件で800回あまり呼ぶ。`index.py` は既定で変わった出典の item だけを `--metadata-filter`（`origin_sha256`）で、待ちは `--status queued`・`running` で絞って一覧する。状態の数だけなら `cf ai-search stats <id> --namespace default` がすぐ返る。cf 1.0.0-beta.18 で `--name`・`--id` は `--namespace`・`--instance-id` に変わった（古い引数は usage を出して失敗する）。
- **登録の前にディスクの空きを確保する**: `evaluation:index` は取り出した出典の PDF を `pipeline/.cache/evaluation-search/origins/` に残す（sha256 を確かめて再利用し、壊れていれば R2 から取り直す）ので、1,033出典で数 GB になる。空き381MB で全件の登録が ENOSPC で止まった（2026-10-21）。終わったらこの dir を消してよく、次回は取り直す。登録は一度で終わらず何回かに分かれるので、各回の後に `stats` で状態を見る。
- **登録済み**: `operations.ts` の末尾に入れてあり、REST・OpenAPI・MCP の tool に出る。外すのは切り戻し（再デプロイが要る。まず `evaluation_search` を `off` にする）。
- **ローカルの `cf dev` で AI Search を呼ぶ**（2026-10-14 に確かめた）:
  - AI Search の binding は simulation が無く、そのままだと検索が `Binding EVALUATION_SEARCH needs to be run remotely` で失敗し 503 になる。`cloudflare.config.ts` の `bindings.aiSearch({...})` に `dev: { remote: true }` を一時的に足す（コミットしない。D1・DO・rate limit はローカルのまま）。remote proxy の接続に Cloudflare の認証とネットワークが要る（sandbox の外）。検索は本番の索引を読むので、回数は数十回までにする。1回5〜7秒かかり、8秒の打ち切りに近い（remote proxy 越し）。
  - ローカル D1 は空で、`serving` の行も無く全部 503 になる。`cf dev` が出す Local Explorer API の `POST http://127.0.0.1:8787/cdn-cgi/local/explorer/api/d1/database/<D1 の id>/raw`（body `{"sql": "…"}`）で、`migrations/0001_init.sql`・`0002_evaluation_search.sql` を流す。`evaluation_search` を `on` にし、`per_day` を小さくして 429 を確かめたら戻す。`--persist-to` は作業用の dir にして、既定の共有 state（`~/.config/cloudflare/state`）を使わない。
  - 流量（IP あたり）の確かめは、ローカルでは IP が `unknown` の1つの key になる。同時に12件送ると10件が通り2件が 429（`Retry-After: 60`）。
- **config が import したファイルは `cf dev` の Worker から読めない**: `@cloudflare/vite-plugin` が config の依存を `server.fs.deny` に入れるため、Worker のコードがそれを import すると `Failed to load url … Does the file exist?` で起動しない（`cf deploy` の build は通る）。`cloudflare.config.ts` と `src/evaluation-limits.ts` が流量の値を二重に持つのはこのため。`evaluations.test.ts` が2つの一致を照合する。
