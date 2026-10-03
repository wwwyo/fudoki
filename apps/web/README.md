# 公開 web

パイプラインの完成を優先するため、全パスでキャッシュしない HTTP 500 を返す。

```bash
bun run dev:web
bun run build:web
```

ローカルの原典・dbt 検証画面は `pipeline/verify/view/`（`bun run dev`、5174）にある。
