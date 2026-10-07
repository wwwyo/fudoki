# packages

- `fiscal/`（`@fudoki/fiscal`）: 歳出・歳入の純粋な型と名称。`detail` / `cofog` / `cofog-master` / `setsu-master` / `types` を export する。歳出の節マスタ（地方自治法施行規則の区分と適用期間）の Git 定義を持つ
- `jurisdictions/`（`@fudoki/jurisdictions`）: 団体コードと自治体の名称を対応付ける団体マスタ。`jurisdictions.json` の registry を export する

pipeline・verify 系の package がここに依存する。副作用・I/O は持たせず、型と名称の定義に留める。
