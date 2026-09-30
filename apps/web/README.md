# 公開 web

公開 API から団体・収録文書・金額段階を読み、選択した dataset/release に固定して集計と明細を表示する。Vite + React + TypeScript。ローカル検証画面は `pipeline/verify/view/` に分離している。

```bash
bun run dev:web
bun run build:web
bun run deploy:web
```

API の RPC URL は `VITE_API_RPC_URL`（既定は公開 API）。ローカル Worker を使う場合は `VITE_API_RPC_URL=http://127.0.0.1:8787/rpc`。公開 web は5173、検証 view は5174で動かす。

画面は `pipeline.json`・原典・OCR・ローカル middleware を読まない。build/deploy に dbt や原典の全量生成は不要。COFOG の各階層の金額は API の SQL 集計を表示し、親の金額を子の合計で作り直さない。明細の続きは問い合わせと保持中の release に署名された cursor を使う。

web と view の UI・色・表示形式は独立している。分類名称と集計規則は `packages/fiscal/`、API 型は公開契約から参照する。内部報告の型を公開画面へコピーしない。
