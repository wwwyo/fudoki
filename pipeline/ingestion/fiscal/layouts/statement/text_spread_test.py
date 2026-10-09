"""Observable header binding, independent tables and boundary-safe hierarchy."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

from ingestion.fiscal.layouts.statement.text_spread import (
    assemble_raw_expenditure, build_spread, project_raw_tables, reconcile,
    raw_expenditure_metadata, raw_expenditure_schema, verify_raw_expenditure, verify_raw_tables, verify_spread,
)

PROFILE = Path(__file__).parents[2] / 'jurisdictions/132071/layouts/budget_spread.json'


def fixture():
    profile=json.loads(PROFILE.read_text())
    root=ET.Element('doc')
    pages=[ET.SubElement(root,'page') for _ in range(2)]
    def word(side,text,x,y,right=None):
        ET.SubElement(pages[side],'word',xMin=str(x),yMin=str(y),xMax=str(right or x+3),yMax=str(y+3)).text=text
    for region in profile['regions']:
        text=region['expected'] or {'kan':'第２款総務費','kou':'第１項総務管理費',
            'left_printed_page':'－104－','right_printed_page':'－105－','repeated_kan':'２款総務費'}[region['id']]
        x,y,_,_=region['bbox']
        word(region['page_side'],text,x+1,y+1)
    def body(key,row,text,left=None,right=None):
        c=next(c for c in profile['columns'] if c['key']==key)
        word(c['page_side'],text,left if left is not None else c['left']+1,
            profile['body_top']+(row-1)*profile['row_height']+4,right)
    for key,text in {'moku':'1一般管理費','current':'100','previous':'90','difference':'10','other':'100','general':'0'}.items():
        body(key,1,text)
    body('other',2,'諸収入'); body('other',3,'100')
    body('setsu_code',1,'13'); body('setsu_name',1,'使用料及び賃'); body('setsu_amount',1,'100')
    body('setsu_name',2,'借料')
    for row,depth,name in [(1,0,'第一事業'),(2,1,'使用料及び賃借料'),(3,2,'内訳明細'),(4,0,'第二事業')]:
        lv=profile['explanation_levels'][depth]
        body('explanation_name',row,name,left=lv['name_left'])
        body('explanation_amount',row,'0' if row==4 else '100',left=lv['amount_right']-3,right=lv['amount_right'])
    return ET.tostring(root),profile


class SpreadContract(unittest.TestCase):
    def setUp(self):
        self.xml,self.profile=fixture()
        self.spread=build_spread(self.xml,origin_id='sha',pages=(108,109),profile=self.profile)

    def check(self,tables):
        return verify_spread(tables,xml=self.xml,spread=self.spread)

    def test_original_headers_and_units_bind_every_raw_field(self):
        result=self.check(self.spread.tables)
        self.assertEqual(result['unassigned_words'],0)
        m=self.spread.tables['moku'][0]
        binding=json.loads(m['header_bindings'])['other_raw']
        self.assertEqual(binding['header_texts'],['本年度予算額の財源内訳','特定財源','その他'])
        self.assertEqual(binding['unit'],'千円')
        self.assertEqual(m['kan_raw'],'第２款総務費')
        self.assertEqual(m['general_raw'],'0')
        self.assertIsNone(m['national_raw'])
        pages=[r['printed_page'] for r in self.spread.tables['context'] if r['kind']=='printed_page']
        self.assertEqual(pages,[104,105])

    def test_setsu_wrapping_does_not_merge_independent_explanation_rows(self):
        setsu=self.spread.tables['setsu']
        self.assertEqual(len(setsu),1)
        self.assertEqual(setsu[0]['name_raw'],'使用料及び賃借料')
        self.assertEqual(json.loads(setsu[0]['source_rows']),[1,2])
        self.assertEqual(len(self.spread.tables['explanation']),4)
        self.assertNotIn('parent_id',setsu[0])
        self.assertNotIn('setsu_id',self.spread.tables['explanation'][0])
        self.assertEqual(self.check(self.spread.tables)['status'],'passed')

    def test_target_metadata_cannot_be_added_to_raw_tables(self):
        for name, rows in self.spread.tables.items():
            for field, value in [('jurisdiction_code','132071'), ('fiscal_year',2025)]:
                bad=deepcopy(self.spread.tables)
                bad[name][0][field]=value
                with self.subTest(table=name,field=field),self.assertRaisesRegex(ValueError,'Raw table columns'):
                    self.check(bad)

    def test_closed_hierarchy_reconciles_but_last_project_stays_open(self):
        nodes=self.spread.tables['explanation']
        self.assertEqual([n['parent_id'] for n in nodes],[None,'explanation:1','explanation:2',None])
        self.assertEqual([n['closure'] for n in nodes],['closed_in_scope']*3+['open_at_scope_end'])
        checks=reconcile(self.spread.tables)
        self.assertFalse(any(c['status']=='mismatch' for c in checks))
        self.assertEqual(sum(c['status']=='deferred_scope_end' for c in checks),1)

    def test_raw_output_retains_original_headers_and_components_without_unit_suffixes(self):
        raw=project_raw_tables(self.spread.tables)
        m=raw['moku'][0]
        self.assertEqual(m['本年度予算額'],'100')
        self.assertEqual(m['一般財源'],'0')
        self.assertIsNone(m['国都支出金'])
        self.assertEqual(raw['setsu'][0]['区分'],{'_code':'13','_text':'使用料及び賃借料'})
        self.assertEqual(len(raw['explanation']),4)
        for name, rows in raw.items():
            for field, value in [('unit_raw','千円'), ('context_json','{}')]:
                bad=deepcopy(raw)
                bad[name][0][field]=value
                with self.subTest(table=name,field=field),self.assertRaises(ValueError):
                    verify_raw_tables(bad,tables=self.spread.tables,xml=self.xml,spread=self.spread)

    def test_detail_rows_preserve_section_path_funding_scope_and_open_frontier(self):
        rows=assemble_raw_expenditure(self.spread.tables)
        self.assertEqual(len(rows),1)
        detail=rows[0]
        self.assertFalse({'区分','区分_コード','区分_名称','金額','_source_region','_scope_end'} & detail.keys())
        self.assertEqual(detail['説明3_名称'],'内訳明細')
        self.assertEqual([detail['説明1_名称'],detail['説明2_名称']],['第一事業','使用料及び賃借料'])
        self.assertFalse(any(name.startswith('_') for name in detail))
        self.assertTrue(all(value is None or isinstance(value,str) for value in detail.values()))
        self.assertEqual(detail['その他_内訳1_名称'],'諸収入')
        self.assertEqual(detail['その他'],'100')
        self.assertTrue(any(n['closure']=='open_at_scope_end' for n in self.spread.tables['explanation']))
        self.assertEqual(len(self.spread.tables['setsu']),1)
        metadata=raw_expenditure_metadata(self.spread.tables)
        large=next(c for c in metadata['column_contexts'] if '説明1_名称' in c['columns'])
        self.assertEqual(large['semantic_role'],'project')
        middle=next(c for c in metadata['column_contexts'] if '説明2_名称' in c['columns'])
        self.assertEqual(middle['semantic_role'],'setsu')
        self.assertEqual(middle['grain_columns'],['款','項','目','説明1_名称','説明2_名称'])
        verify_raw_expenditure(rows,tables=self.spread.tables,xml=self.xml,spread=self.spread,metadata=metadata)
        for case in ('section','path','funding','missing','duplicate','unit','frontier','summary','project_role','setsu_role','inspection_status'):
            bad=deepcopy(rows); meta=deepcopy(metadata)
            if case=='section':bad[0]['区分_コード']='01'
            elif case=='path':bad[0]['説明1_名称']='第二事業'
            elif case=='funding':bad[0]['その他_細目配分額']='100'
            elif case=='missing':bad.pop()
            elif case=='duplicate':bad.append(deepcopy(bad[0]))
            elif case=='frontier':
                pending=next(n for n in self.spread.tables['explanation'] if n['closure']=='open_at_scope_end')
                extra=deepcopy(bad[0]); extra['説明1_名称']=pending['name_raw']; bad.append(extra)
            elif case=='summary':
                extra=deepcopy(bad[0]); extra['説明3_名称']=None
                bad.append(extra)
            elif case=='inspection_status':bad[0]['_scope_end']='closed_in_scope'
            elif case in ('project_role','setsu_role'):
                next(c for c in meta['column_contexts'] if c.get('semantic_role') == case.removesuffix('_role')).pop('semantic_role')
            else:meta['units'][0]['text']='円'
            with self.subTest(case=case),self.assertRaises(ValueError):
                verify_raw_expenditure(bad,tables=self.spread.tables,xml=self.xml,spread=self.spread,metadata=meta)

    def test_multiple_funding_annotations_do_not_multiply_terminal_rows(self):
        tables=deepcopy(self.spread.tables)
        tables['funding'][0]['amount_raw']='60'
        second=deepcopy(tables['funding'][0])
        second.update(row_id='funding:2',name_raw='寄附金',amount_raw='40')
        tables['funding'].append(second)
        rows=assemble_raw_expenditure(tables)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['その他'],'100')
        self.assertEqual((rows[0]['その他_内訳1_金額'],rows[0]['その他_内訳2_金額']),('60','40'))
        self.assertEqual(rows[0]['その他_内訳2_名称'],'寄附金')
        metadata=raw_expenditure_metadata(tables)
        from ingestion.fiscal.manifest import validate_metadata
        validate_metadata(metadata,list(rows[0]))

    def test_actual_parquet_roundtrip_preserves_flat_details_nulls_and_metadata(self):
        import tempfile
        import duckdb
        from ingestion.lib.parquet import write_parquet
        rows=assemble_raw_expenditure(self.spread.tables)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'raw.parquet'
            write_parquet(path,rows,columns=raw_expenditure_schema(rows))
            with duckdb.connect() as con:
                cur=con.execute('select * from read_parquet(?)',[str(path)])
                saved=[dict(zip([c[0] for c in cur.description],row,strict=True)) for row in cur.fetchall()]
            self.assertEqual(saved,rows)
            self.assertTrue(all(c.type=='VARCHAR' for c in raw_expenditure_schema(rows)))
            verify_raw_expenditure(saved,tables=self.spread.tables,xml=self.xml,spread=self.spread,
                                   metadata=raw_expenditure_metadata(self.spread.tables))

    def test_unknown_header_or_repeated_context_stops_conversion(self):
        root=ET.fromstring(self.xml)
        for label,replacement in [('本年度予算額','別年度予算額'),('２款総務費','３款民生費')]:
            bad=deepcopy(root)
            next(w for w in bad.findall('.//word') if w.text==label).text=replacement
            with self.subTest(label=label),self.assertRaises(ValueError):
                build_spread(ET.tostring(bad),origin_id='sha',pages=(108,109),profile=self.profile)

    def test_cell_header_exchange_is_rejected_even_when_all_words_survive(self):
        bad=deepcopy(self.spread.tables)
        row=bad['moku'][0]
        refs=json.loads(row['cell_token_ids']); bindings=json.loads(row['header_bindings'])
        for mapping in (row,refs,bindings):
            mapping['current_raw'],mapping['previous_raw']=mapping['previous_raw'],mapping['current_raw']
        row['cell_token_ids']=json.dumps(refs); row['header_bindings']=json.dumps(bindings)
        with self.assertRaisesRegex(ValueError,'header binding'):
            self.check(bad)

    def test_column_cannot_be_bound_to_a_header_over_another_column(self):
        profile=deepcopy(self.profile)
        next(c for c in profile['columns'] if c['key']=='current')['header']='previous'
        with self.assertRaisesRegex(ValueError,'header span'):
            build_spread(self.xml,origin_id='sha',pages=(108,109),profile=profile)

    def test_corrupted_header_parent_text_span_and_unit_are_rejected(self):
        for field,value in [('parent_id','general'),('raw_text','百万円'),('bbox','[0,0,1,1]')]:
            bad=deepcopy(self.spread.tables)
            next(r for r in bad['headers'] if r['region_id']=='other_unit')[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.check(bad)

    def test_amount_missing_and_duplicate_words_are_rejected(self):
        for case in ('amount','missing','duplicate'):
            bad=deepcopy(self.spread.tables)
            row=bad['setsu'][0]
            if case=='amount':row['amount_raw']='0100'
            else:
                refs=json.loads(row['cell_token_ids'])
                if case=='missing':refs['name_raw']=refs['name_raw'][:1]; row['name_raw']='使用料及び賃'
                else:refs['name_raw']+=refs['name_raw'][:1]
                row['cell_token_ids']=json.dumps(refs)
            with self.subTest(case=case),self.assertRaises(ValueError):
                self.check(bad)

    def test_equal_amounts_do_not_hide_wrong_parent_or_scope_state(self):
        for field,value in [('parent_id','explanation:1'),('depth',1),('closure','open_at_scope_end')]:
            bad=deepcopy(self.spread.tables)
            bad['explanation'][2][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.check(bad)

    def test_statutory_explanation_relationship_is_rejected(self):
        for table,field,value in [('setsu','explanation_id','explanation:1'),('explanation','setsu_id','setsu:1')]:
            bad=deepcopy(self.spread.tables)
            bad[table][0][field]=value
            with self.subTest(table=table),self.assertRaises(ValueError):
                self.check(bad)

    def test_outside_and_inconsistent_geometry_cannot_be_silently_dropped(self):
        for case in ('outside','indent'):
            root=ET.fromstring(self.xml)
            if case=='outside':
                ET.SubElement(root[1],'word',xMin='550',yMin='120',xMax='560',yMax='125').text='未分類'
            else:
                w=next(w for w in root.findall('.//word') if w.text=='使用料及び賃借料')
                w.set('xMin','197'); w.set('xMax','200')
            with self.subTest(case=case),self.assertRaises(ValueError):
                build_spread(ET.tostring(root),origin_id='sha',pages=(108,109),profile=self.profile)


if __name__=='__main__':
    unittest.main()
