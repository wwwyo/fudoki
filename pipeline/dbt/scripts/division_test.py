"""Exercise the real node model and rows contract with tables printing divisions' shares (ADR 0030)."""
import unittest
from pathlib import Path

import duckdb
from jinja2 import Environment, StrictUndefined

DBT = Path(__file__).resolve().parents[1]
COLUMNS = ('source_table_key', 'node_key', 'parent_node_key', 'division', 'node_id', 'parent_node_id',
           'axis_header', 'node_kind', 'code_text', 'name', 'kan_code', 'kou_code', 'moku_code',
           'amount_yen', 'origin_id', 'physical_page')


def render(path: str) -> str:
    sql = (DBT / path).read_text()
    return Environment(undefined=StrictUndefined).from_string(sql).render(
        ref=lambda name: name, source=lambda _, name: f'fiscal_metadata_{name}')


class DivisionTest(unittest.TestCase):
    def run_model(self, rows, tables):
        con = duckdb.connect()
        typed = ', '.join(f'{c}::bigint as {c}' if c == 'amount_yen' else f'{c}::integer as {c}'
                          if c == 'physical_page' else f'{c}::varchar as {c}' for c in COLUMNS)
        con.execute(f'''create table int_fiscal__settlement_expenditure_rows as select
            {typed}, 'fixture' as jurisdiction_code, 2025 as fiscal_year, 'settlement' as document_kind,
            '一般会計' as account_name, '科目' as subject_axis, null::double as x0, null::double as y0,
            null::double as x1, null::double as y1, physical_page::integer as amount_source_page,
            1.0 as amount_source_x0, 2.0 as amount_source_y0, 3.0 as amount_source_x1, 4.0 as amount_source_y1,
            null::varchar as kan_name, null::varchar as kou_name
            from (values {', '.join(['(' + ', '.join(['?'] * len(COLUMNS)) + ')'] * len(rows))})
            t({', '.join(COLUMNS)})''', [v for row in rows for v in row])
        con.execute('''create table fiscal_metadata_tables as select *, 'fixture' as jurisdiction_code,
            2025 as fiscal_year, 'settlement' as document_kind, 'expenditure' as direction, '一般会計' as account_name,
            1 as nodes_row_count from (values ('a', '甲局'), ('b', '乙局'), ('w', null)) t(source_table_key, division)
            where source_table_key in ({})'''.format(', '.join(f"'{t}'" for t in tables)))
        con.execute('create table stg_fiscal__nodes as select source_table_key, null::varchar as axis_header from fiscal_metadata_tables where false')
        con.execute('create table nodes as ' + render('models/intermediate/fiscal/int_fiscal__settlement_expenditure_nodes.sql'))
        # The node-count line of the contract reads the fixture's own row counts; only the identity checks matter here.
        failures = con.execute(f"select * from ({render('tests/fiscal_rows_contract.sql')}) where failure <> 'missing_or_duplicated_row'").fetchall()
        return con, failures

    def shares(self, kan_a=100, kan_b=50):
        # Two divisions print their share of 款1・目1 and the same 節 under it; 乙局 alone prints 節2.
        return [
            ('a', 'k', None, '甲局', 'K', None, '科目', '款', '1', '総務費', '1', None, None, kan_a, 'o1', 3),
            ('a', 'm', 'k', '甲局', 'M', 'K', '科目', '目', '1', '総務管理費', '1', '1', '1', kan_a, 'o1', 3),
            ('a', 's', 'm', '甲局', 'S1', 'M', '節', '内訳1', '1', '報酬', '1', '1', '1', kan_a, 'o1', 3),
            ('b', 'k', None, '乙局', 'K', None, '科目', '款', '1', '総務費', '1', None, None, kan_b, 'o2', 7),
            ('b', 'm', 'k', '乙局', 'M', 'K', '科目', '目', '1', '総務管理費', '1', '1', '1', kan_b, 'o2', 7),
            ('b', 's', 'm', '乙局', 'S1', 'M', '節', '内訳1', '1', '報酬', '1', '1', '1', 30, 'o2', 7),
            ('b', 't', 'm', '乙局', 'S2', 'M', '節', '内訳1', '2', '給料', '1', '1', '1', kan_b - 30, 'o2', 7),
        ]

    def test_division_shares_add_up_and_lose_the_single_printed_box(self):
        con, failures = self.run_model(self.shares(), ['a', 'b'])
        self.assertEqual(failures, [])
        got = dict(con.execute('select node_id, amount_yen from nodes').fetchall())
        self.assertEqual(got, {'K': 150, 'M': 150, 'S1': 130, 'S2': 20})
        boxes = dict(con.execute('select node_id, amount_source_page from nodes').fetchall())
        self.assertEqual(boxes, {'K': None, 'M': None, 'S1': None, 'S2': 7})

    def test_a_whole_table_stands_for_the_node_and_the_shares_must_add_up_to_it(self):
        whole = [('w', 'k', None, None, 'K', None, '科目', '款', '1', '総務費', '1', None, None, 150, 'o0', 6)]
        con, failures = self.run_model(self.shares() + whole, ['a', 'b', 'w'])
        self.assertEqual(failures, [])
        self.assertEqual(con.execute("select amount_yen, amount_source_page from nodes where node_id = 'K'").fetchone(), (150, 6))
        _, failures = self.run_model(self.shares(kan_b=49) + whole, ['a', 'b', 'w'])
        self.assertEqual([f[1] for f in failures], ['cross_table_subject_disagreement'])

    def test_tables_without_a_division_still_must_agree(self):
        rows = [(t, 'k', None, None, 'K', None, '科目', '款', '1', '総務費', '1', None, None, amount, 'o0', 6)
                for t, amount in (('w', 150), ('a', 140))]
        _, failures = self.run_model([(*r[:3], None, *r[4:]) for r in rows], ['w'])
        self.assertEqual([f[1] for f in failures], ['cross_table_subject_disagreement'])


if __name__ == '__main__':
    unittest.main()
