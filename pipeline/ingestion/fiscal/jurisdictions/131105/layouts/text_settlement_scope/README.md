# 目黒区 text PDF 決算歳出の会計範囲設定

`convert.py` は既存 `text_settlement/convert.py` の座標観測・款項目節の構築・metadata を再利用する入口。既存の一般会計 converter と options schema は変更せず、新しい会計を設定で追加する。元の書式処理の複製や年度・会計ごとの実装を置かない。

options の `account` は選定にある会計名、`summary_pages` と `detail_pages` は各々昇順で重ならない物理頁の `[start, end]` 配列。設定した全頁が選定の当該会計・歳出 scope と一致する場合だけ構築する。総括頁は正式rawを生成せず、事項別明細だけを既存構築処理へ渡す。指定された明細範囲には歳出合計が1行必要で、合計は節明細へ混ぜない。

介護保険特別会計の2025年度決算は `summary_pages=[[138,139]]`、`detail_pages=[[150,159]]`。同じ見開き1190.55ptの書式で、事業別の説明欄がなく法定節が最細明細。`long-term-care-setsu` は60行60列、7款17項24目の所属を反復する。全金額は円見出しの原表記文字列で、節の予算現額・支出済額・繰越3列・不用額、款項目の予算現額5列・支出済額・繰越3列・不用額を保持する。

物理151・155頁には前頁からの節の続きがある。156頁の基金積立金・159頁の予備費には予備費充用の備考があり、159頁の節の備考には充用先の第4款基金積立金も印字される。所属と文字の独立検査はoperatorが行い、構築観測 `meguro-<table_id>-observations` を合否判断の根拠にしない。観測dirを表IDごとに分け、同じ候補dirでの一般会計との全conversion再構築に対応する。

既存manifestへの追加は現行CLIの `--extend-plan` を使う。plan は既存の conversions をそのまま保持して1つだけ追加し、`tables=[]` とする。既存一般会計の定義・receipt・metadata・key はCLIが保持する。以下はrepo rootから候補を生成する例で、出力dirは未使用の名前にする。

```sh
mise exec -- bun run --cwd pipeline ingestion:convert \
  --manifest ingestion/fiscal/jurisdictions/131105/2025/settlement/expenditure.json \
  --inputs .cache/meguro-2025-settlement-inputs.json \
  --extend-plan ../.agent/2025-text-pdf-ingestion/0011-131105-settlement/extend-plan.json \
  --output .cache/meguro-2025-care-candidate-new
```

正式保存・GET後の確認・再構築・合否判断はoperatorが担当する。変換器は管理JSONやR2を更新しない。
