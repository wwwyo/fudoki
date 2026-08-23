-- 歳出を団体をまたいだ共通の形へ揃える。**判断の段の入口。**
-- 中身は macros/budget_core_lines.sql にあり、団体は dbt_project.yml の宣言から来る。
{{ budget_core_lines('expenditure') }}
