# パイプラインの層を分ける

現行の構成はingestion → staging → intermediate → martsである。層・保存境界・完了条件は [全体設計](../monorepo/design-doc.md) が正本で、旧Extract・Load・Transformと正本／派生の二分構成は使用しない。

取り込みは原典の値と単位を保持する。stagingは原典行と1対1、intermediateは団体間の構造・円単位・共通科目・COFOGを揃え、martsは提供する列と粒度を確定する。系統はdbt manifestから生成し、原典との対応は [ローカル検証画面](../pipeline-verification-view/prd.md) で確認する。
