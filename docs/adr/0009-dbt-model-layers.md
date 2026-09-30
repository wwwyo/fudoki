# dbt のモデル層と配布処理を分ける

## 決定

①予算のモデルを `staging → intermediate → marts` に分け、原典の取得・取り込みと配布パッケージの生成は dbt の外に置く。ADR 0003 の層名と責務を更新する。

- staging：原典ごとの列名・型の整形。原典の行と1対1の対応と金額単位を保つ。
- intermediate：提供用データのための中間処理。団体間の構造統一、円換算、共通科目への対応、COFOG 分類を行う。
- marts：利用者向けの列・粒度を確定する。風土記では団体別 CSV に書き出す。
- export / 配布：`fdp/build.py` が CSV に列の定義・出典・利用条件・証跡を添える。

全リソースに intermediate を強制しない。原典由来の支出・歳入は staging から marts へ進み、分類などのリソースは intermediate を経る。

## 理由とトレードオフ

「正規化（staging）」「判断（core）」は処理の性質とモデル層を混同させる。円換算は実際には core にあり、利用者向けデータを作る中間処理も存在する。画面の表示名だけ変えると実際の置き場と系統図がずれるため、core ディレクトリを intermediate、package ディレクトリを marts に移す。

モデルの参照名（`core_*` / `pkg_*`）は維持する。接頭辞は旧名称が残るが、SQL の参照・テスト・報告の問い合わせまで一斉に変更するリスクを避け、配布物の同一性を検証できる範囲に変更を絞る。

判断の有無は、dbt の層の定義とは別の情報として残す。規則表の役割と下流への伝播を報告し、原典由来の値と風土記が付与した分類は別リソースで提供する。

## 参照

dbt の層は強制仕様ではなく推奨構成。[Staging](https://docs.getdbt.com/best-practices/how-we-structure/2-staging) は原典ごとの準備、[Intermediate](https://docs.getdbt.com/best-practices/how-we-structure/3-intermediate) は最終モデルを作る中間処理として整理されている。配布ファイルを書き出すこと自体を marts の定義にはしない。
