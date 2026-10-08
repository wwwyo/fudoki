"""Regression checks for real PDF failure modes seen in expanded official budgets."""
import json
import tempfile
import unittest
from pathlib import Path

from ingestion.fiscal.layouts.fiscal_general.extract_statement import _PageChars, _location, _write, extract
from ingestion.lib.pdf import deduplicate_offset_words, rows_of


class PdfProvenance(unittest.TestCase):
    def test_right_page_row_does_not_close_a_wrapped_left_page_label(self):
        left = _PageChars([(50, 10, 180, 19, '第１款議会費'),
                           (50, 20, 180, 29, '第１項議会費'),
                           (56, 30, 126, 39, '1自転車対策'),
                           (150, 30, 162, 39, '100'),
                           (66, 34, 76, 43, '費')], {})
        right = _PageChars([(195, 32, 205, 41, '例'),
                            (522, 32, 534, 41, '100')], {})
        spec = {'pages': {'expenditure': [1, 2]}, 'heading_style': 'dai',
                'source_amount_unit': '千円',
                'left_page_columns': {'expenditure': ['moku']},
                'columns': {'expenditure': {'moku': [56, 190], 'setsu_code': [56, 72],
                                           'setsu': [72, 193], 'explanation': [195, 545]}},
                'explanation': {'expenditure': {'model': 'nested', 'levels': {'project': 530},
                                               'tolerance': 2}}}
        rows, _, _ = extract([left, right], spec, 'expenditure')
        self.assertEqual(rows[0]['moku_name'], '自転車対策費')

    def test_repeated_amounts_on_other_rows_do_not_expand_the_bbox(self):
        page = _PageChars([(20, 100, 50, 109, '100'),
                           (20, 200, 50, 209, '100')], {})
        line = rows_of(page)[0]
        self.assertEqual(_location(page, 42, line, (10, 60), line.ys),
                         {'page': 42, 'bbox': [20, 100, 50, 109]})

    def test_declared_duplicate_print_layer_preserves_other_identical_values(self):
        original = (50, 100, 80, 109, '131,733')
        shifted = (52.8346, 100, 82.8346, 109, '131,733')
        separate = (150, 100, 180, 109, '131,733')
        lower = (50, 200, 80, 209, '131,733')
        self.assertEqual(deduplicate_offset_words([original, shifted, separate, lower], 2.8346),
                         [original, separate, lower])

    def test_partial_spread_is_rejected_before_rows_can_be_omitted(self):
        with self.assertRaisesRegex(ValueError, 'incomplete spread'):
            extract([[]], {'pages': {'expenditure': [10, 11]}}, 'expenditure')

    def test_raw_parquet_preserves_original_amount_location_and_scope(self):
        import duckdb
        row = {key: '' for key in ['kan_code', 'kan_name', 'kou_code', 'kou_name',
                                  'moku_code', 'moku_name', 'project_name', 'setsu_code',
                                  'setsu_name', 'detail_name']}
        row.update(amount=131733, moku_reconciled=True, source_location={'page': 34,
                   'bbox': [346.9194, 114.270075, 376.54515, 122.703406]},
                   source_table_id='fund-general', source_amount_unit='千円')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            _write(path, 'revenue', '一般会計', [row], 2024)
            con = duckdb.connect()
            got = con.execute('SELECT "本年度予算額", source_page, source_bbox, '
                              'source_table_id, source_amount_unit, source_fiscal_year '
                              'FROM read_parquet(?)', [str(path / 'data.parquet')]).fetchone()
            con.close()
            self.assertEqual(got[:2], ('131733', 34))
            self.assertEqual(json.loads(got[2]), row['source_location']['bbox'])
            self.assertEqual(got[3:], ('fund-general', '千円', 2024))


if __name__ == '__main__':
    unittest.main()
