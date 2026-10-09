"""Exercise conversion with the private fixed original when restored."""
import hashlib
from importlib import import_module
from pathlib import Path
import tempfile
import unittest

import duckdb
from ingestion.fiscal.manifest import PIPELINE


class EnterpriseStatementTest(unittest.TestCase):
    def test_fixed_original_preserves_wrapped_names_zeros_and_budget_separation(self):
        pdf = PIPELINE / '.cache/objects/fiscal/source-selection/132071/2025/settlement.pdf'
        if not pdf.is_file():
            self.skipTest('Private original is not restored')
        sha = '7d2b4b818e99e43e95c02ef7c33c0022b93e1bab83335004924bd30894bcb280'
        self.assertEqual(hashlib.sha256(pdf.read_bytes()).hexdigest(), sha)
        convert = import_module('ingestion.fiscal.jurisdictions.132071.layouts.enterprise_statement.convert').convert
        source = {'path': pdf, 'sha256': sha, 'format': 'pdf', 'direction': 'expenditure',
                  'target': {'jurisdiction': '132071', 'fiscal_year': 2025, 'document_kind': 'settlement'},
                  'scope': [{'account': '下水道事業会計', 'pages': [[4, 7], [24, 28], [30, 31]]}]}
        options = {'table_prefix': 'test', 'report_pages': [4, 5, 6, 7],
                   'revenue_expense_pages': [24, 25, 26, 27, 28], 'capital_expense_pages': [30, 31]}
        with tempfile.TemporaryDirectory() as temporary:
            tables = convert([source], Path(temporary), options)
            with duckdb.connect() as connection:
                def rows(table):
                    data = connection.execute('SELECT * FROM read_parquet(?)', [str(tables[table]['path'])]).fetchall()
                    return [dict(zip([c[0] for c in connection.description], r)) for r in data]
                report = rows('test-capital-report')
                self.assertEqual(report[1]['区分_項'], '第２項企業債償還金')
                revenue = rows('test-revenue-detail')
                repair = [r for r in revenue if r['目'] == '１管渠維持費' and r['節'] == '修繕費']
                self.assertEqual(len(repair), 1)
                self.assertEqual(repair[0]['金額（円）'], '1,125,000')
                wrapped = [r for r in revenue if r['目'] == '１過年度損益修正損']
                self.assertEqual(wrapped[0]['節'], '過年度損益修正損')
                self.assertEqual(wrapped[0]['金額（円）'], '0')
                wage = [r for r in revenue if r['目'] == '１管渠維持費' and r['節'] == '給料']
                self.assertEqual([r['備考_予算額'] for r in wage], ['17,732,000', '17,732,000'])
                self.assertEqual([r['備考_金額'] for r in wage], ['10,536,300', '0'])
                self.assertTrue(all(isinstance(r['金額（円）'], str) for r in revenue))
                self.assertEqual(len(rows('test-capital-detail')), 24)
