"""Ensure migration relocates code without changing already canonical references."""
import unittest

from ingestion.fiscal.migrate import relocated_declaration, distinct_table_id, table_id


class RelocationTest(unittest.TestCase):
    def test_existing_canonical_paths_and_jurisdiction_notes_are_stable(self):
        path = 'pipeline/ingestion/fiscal/jurisdictions/132241/layouts/tama_ordinary_history/contracts.py'
        self.assertEqual(relocated_declaration(path), path)
        note = 'pipeline/ingestion/fiscal/jurisdictions/131016.md'
        self.assertEqual(relocated_declaration(note),
                         'pipeline/ingestion/fiscal/jurisdictions/131016/README.md')
        package = 'pipeline/ingestion/fiscal/tama_ordinary_history/contracts.py'
        self.assertEqual(relocated_declaration(package), path)
        self.assertEqual(relocated_declaration(relocated_declaration(package)), path)

    def test_separate_accounts_keep_existing_ids_and_do_not_disambiguate_same_account(self):
        entry = {'path': 'statement/jurisdiction=132047/year=2024/edition=first/table=setsu',
                 'source': {'fund_label': '一般会計'}}
        general = [{'account': '一般会計'}]
        ident = distinct_table_id(entry, general, [])
        self.assertEqual(ident, table_id(entry, general))
        owners = [{'id': ident, 'inputs': [{'scope': general}]}]
        second = {'path': entry['path'].replace('edition=first', 'edition=second'),
                  'source': {'fund_label': '国民健康保険特別会計'}}
        special = [{'account': '国民健康保険特別会計'}]
        other = distinct_table_id(second, special, owners)
        self.assertIsNotNone(other)
        self.assertNotEqual(other, ident)
        self.assertEqual(distinct_table_id(entry, general, owners), None)
        self.assertEqual(distinct_table_id(second, general, owners), None)
        self.assertEqual(distinct_table_id(second, special, owners + [{'id': other, 'inputs': [{'scope': special}]}]), None)


if __name__ == '__main__':
    unittest.main()
