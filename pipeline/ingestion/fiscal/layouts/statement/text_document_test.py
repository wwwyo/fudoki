"""Public whole-document behavior across spread and independent column boundaries."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from ingestion.fiscal.layouts.statement.text_document import build_document, assemble_document

PROFILE = Path(__file__).parents[2] / 'jurisdictions/132071/layouts/budget_spread.json'


def fixture():
    profile = json.loads(PROFILE.read_text())
    root = ET.Element('doc')
    pages = [ET.SubElement(root, 'page') for _ in range(4)]

    def word(page, text, x, y, right=None):
        ET.SubElement(pages[page], 'word', xMin=str(x), yMin=str(y),
                      xMax=str(right or x + 3), yMax=str(y + 3)).text = text

    for pair in (0, 2):
        for r in profile['regions']:
            if r['id'] == 'direction' and pair:
                continue
            text = r['expected'] or {'kan': '第２款総務費', 'kou': '第１項総務管理費',
                    'left_printed_page': f'－{104 + pair}－', 'right_printed_page': f'－{105 + pair}－',
                    'repeated_kan': '２款総務費'}[r['id']]
            word(pair + r['page_side'], text, r['bbox'][0] + 1, r['bbox'][1] + 1)
    for p in (0, 2):
        word(p, '1', 64, 113)
        word(p, '一般管理費', 73, 113)
    word(0, '100', 149, 113)
    word(0, '90', 208, 113)
    word(0, '10', 276, 113)
    word(0, '100', 462, 113)
    word(0, '0', 530, 113)
    word(0, '諸収入', 423, 752)
    word(2, '100', 462, 113)
    word(1, '13', 59.5, 113)
    word(1, '委託料', 73, 113)
    word(1, '100', 177, 113)
    word(1, '第一事業', 197, 113)
    word(1, '100', 521, 113, 535)
    word(1, '委託料', 215, 131)
    word(1, '100', 512, 131, 526)
    word(1, '頁をまたぐ明細', 233, 752)
    word(3, '100', 494, 113, 508)
    word(2, '旧事業', 73, 500)
    word(2, '0', 176, 500)
    word(2, '90', 230, 500)
    word(2, '△90', 280, 500)
    return ET.tostring(root), profile


class DocumentContract(unittest.TestCase):
    def test_formal_layout_options_validate_and_include_the_measured_profile_dependency(self):
        from ingestion.fiscal import manifest
        conversion = {'id': 'text-budget', 'converter': 'fiscal/jurisdictions/132071/layouts/text_budget/convert.py',
                      'inputs': [{'sha256': 'a' * 64}], 'options': {'table_id': 'expenditure', 'detail_pages': [108, 449]},
                      'expected_tables': [{'table_id': 'expenditure'}]}
        document = {'schema_version': 1, 'target': {'jurisdiction': '132071', 'fiscal_year': 2025, 'document_kind': 'initial'},
                    'direction': 'expenditure', 'conversions': [conversion], 'tables': []}
        manifest.validate(document)
        self.assertIn('fiscal/jurisdictions/132071/layouts/budget_spread.json', manifest.dependencies(conversion))
        import jsonschema
        invalid = deepcopy(document)
        invalid['conversions'][0]['options']['profile'] = 'unchecked.json'
        with self.assertRaises(jsonschema.ValidationError):
            manifest.validate(invalid)

    def test_continuations_and_zero_budget_keep_flat_source_rows(self):
        xml, profile = fixture()
        tables, bindings = build_document(xml, origin_id='test', pages=(108, 111), profile=profile)
        rows, metadata = assemble_document(tables, bindings)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['説明3_名称'], '頁をまたぐ明細')
        self.assertEqual(rows[0]['説明3_金額'], '100')
        self.assertEqual(rows[0]['その他_内訳1_金額'], '100')
        self.assertEqual(rows[1]['目'], '旧事業')
        self.assertEqual(rows[1]['本年度予算額'], '0')
        self.assertEqual(rows[1]['比較'], '△90')
        self.assertIsNone(rows[1]['説明3_金額'])
        self.assertEqual(len(tables['words']), len(ET.fromstring(xml).findall('.//word')))
        self.assertTrue(all(v is None or isinstance(v, str) for r in rows for v in r.values()))
        self.assertNotIn('setsu_id', rows[0])
        from ingestion.fiscal.manifest import validate_metadata
        validate_metadata(metadata, list(rows[0]))
        self.assertIn('旧事業', metadata['notes'][-1]['text'])

    def test_name_amount_alignment_and_unknown_headers_stop(self):
        xml, profile = fixture()
        root = ET.fromstring(xml)
        for case in ('amount_alignment', 'header'):
            bad = deepcopy(root)
            if case == 'header':
                next(w for w in bad.findall('.//word') if w.text == '本年度予算額').text = '別年度予算額'
            else:
                bad[-1].find('word').set('xMax', '526')
                amount = next(w for w in bad[-1].findall('word') if w.text == '100')
                amount.set('xMax', '526')
            with self.subTest(case=case), self.assertRaises(ValueError):
                build_document(ET.tostring(bad), origin_id='test', pages=(108, 111), profile=profile)

    def test_unfinished_name_is_not_confirmed_as_a_leaf(self):
        xml, profile = fixture()
        root = ET.fromstring(xml)
        amount = next(w for w in root[-1].findall('word') if w.text == '100')
        root[-1].remove(amount)
        with self.assertRaisesRegex(ValueError, 'Unresolved explanation'):
            build_document(ET.tostring(root), origin_id='test', pages=(108, 111), profile=profile)


if __name__ == '__main__':
    unittest.main()
