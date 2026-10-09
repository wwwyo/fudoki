"""Keep migration table identities distinct only for confirmed separate accounts."""
import unittest

from ingestion.fiscal.migrate import distinct_table_id, table_id


class RelocationTest(unittest.TestCase):
    def test_separate_accounts_keep_existing_ids_and_do_not_disambiguate_same_account(self):
        entry = {'path': 'statement/jurisdiction=132047/year=2024/edition=first/table=setsu',
                 'source': {'fund_label': '一般会計'}}
        general = [{'account': '一般会計'}]
        ident = distinct_table_id(entry, general, {})
        self.assertEqual(ident, table_id(entry, general))
        owners = {ident: {'一般会計'}}
        second = {'path': entry['path'].replace('edition=first', 'edition=second'),
                  'source': {'fund_label': '国民健康保険特別会計'}}
        special = [{'account': '国民健康保険特別会計'}]
        other = distinct_table_id(second, special, owners)
        self.assertIsNotNone(other)
        self.assertNotEqual(other, ident)
        self.assertEqual(distinct_table_id(entry, general, owners), None)
        self.assertEqual(distinct_table_id(second, general, owners), None)
        self.assertEqual(distinct_table_id(second, special, {**owners, other: {'国民健康保険特別会計'}}), None)


if __name__ == '__main__':
    unittest.main()
