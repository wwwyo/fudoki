# パイプラインは4段 ELT、境界は「fudoki の判断が入るか」

ingestion（Python・無加工）→ staging（dbt・原典と1対1）→ core（dbt・判断あり）→ package（TS・配布物）。staging までの出力は判断を含まないので原典と突き合わせて検証でき、core の出力は自治体が言っていないことを含むので別リソースとして配る。dbt の定石の intermediate 層は置かない — 入れるものが実在しないためで、名寄せの判断が現れた時点で切る。
