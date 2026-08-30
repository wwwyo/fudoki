{#
  和暦（令和）と西暦の対応。**元号の変換であって団体固有の知識ではない。**

  ⚠️ 検査の中に書いていたのを出した。多摩市の年度列が `R4` の形をしていたので
  `dbt/tests/source_year_matches_partition.sql` に変換式を直書きしたが、
  和暦表記は東京の自治体資料では主流なので、次の団体で必ず2箇所目にコピーされる。
  検査という「見る側」に domain の知識を埋めない。

  令和元年 = 2019年度。`R1` から数える（`R01` のようなゼロ埋めは実測で見ていないので扱わない）。
#}
{% macro western_to_reiwa_abbrev(year_expr) %}
'R' || cast(cast({{ year_expr }} as integer) - 2018 as varchar)
{%- endmacro %}
