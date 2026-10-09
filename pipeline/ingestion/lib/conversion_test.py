"""Conversion API preserves original records and returns storage-independent results."""

import csv
import hashlib
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import duckdb

from ingestion.lib.conversion import ConversionContext, OriginReference, convert_csv, verify_csv, write_conversion
from ingestion.lib.parquet import ParquetColumn, write_parquet
from ingestion.lib.pdf_table import (
    Column, Placement, TableLayout, assemble_table, place_tokens, tokens_from_bbox_layout,
)


CONTEXT = ConversionContext("upstream-origin", "expenditure", "extractor@1", "layout@1")


class Conversion(unittest.TestCase):
    def test_csv_preserves_values_duplicates_and_physical_multiline_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "source.csv", root / "table.parquet"
            body = '名称,金額\r\n"改行\r\n名称","1,234"\r\nゼロ,0\r\n空欄,\r\nNULL,NULL\r\nゼロ,0\r\n'
            source.write_bytes(body.encode("cp932"))
            result = convert_csv(source, target, context=CONTEXT, encoding="cp932")
            with duckdb.connect() as connection:
                rows = connection.execute("SELECT * FROM read_parquet(?)", [str(target)]).fetchall()
            self.assertEqual(rows, [("改行\r\n名称", "1,234", 2, 3), ("ゼロ", "0", 4, 4),
                                    ("空欄", "", 5, 5), ("NULL", "NULL", 6, 6), ("ゼロ", "0", 7, 7)])
            self.assertEqual(source.read_bytes(), body.encode("cp932"))
            self.assertEqual(result.context, CONTEXT)
            self.assertEqual(result.row_count, 5)
            self.assertEqual(result.sha256, hashlib.sha256(target.read_bytes()).hexdigest())
            self.assertEqual(result.bytes, target.stat().st_size)
            self.assertEqual(result.path, str(target.resolve()))
            self.assertEqual(json.loads(json.dumps(asdict(result)))["context"]["origin_id"], "upstream-origin")
            self.assertEqual({p.name for p in root.iterdir()}, {"source.csv", "table.parquet"})

    def test_csv_failures_leave_no_partial_parquet_or_declarations(self):
        bodies = ["name,amount\na,1\nb\n", 'name,amount\na,1\n"unterminated,2',
                  "name,name\na,b\n", "name,NAME\na,b\n", "source_line_start,amount\na,1\n",
                  "name,amount\na,1\n\n", "", "\n"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "source.csv", root / "table.parquet"
            for body in bodies:
                with self.subTest(body=body):
                    source.write_text(body, encoding="utf-8")
                    with self.assertRaises((ValueError, csv.Error)):
                        convert_csv(source, target, context=CONTEXT, encoding="utf-8", batch_size=1)
                    self.assertFalse(target.exists())
                    self.assertEqual(list(root.iterdir()), [source])
            source.write_bytes(b"name\n\xff\n")
            with self.assertRaises(UnicodeDecodeError):
                convert_csv(source, target, context=CONTEXT, encoding="utf-8")
            self.assertFalse(target.exists())

    def test_declared_dialect_header_only_and_provenance_column_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "source.csv", root / "table.parquet"
            source.write_text("source_line_start;amount\n", encoding="utf-8")
            result = convert_csv(source, target, context=CONTEXT, encoding="utf-8", delimiter=";",
                                 source_line_columns=("line_first", "line_last"))
            self.assertEqual(result.row_count, 0)
            with duckdb.connect() as connection:
                schema = connection.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(target)]).fetchall()
            self.assertEqual([(r[0], r[1]) for r in schema],
                             [("source_line_start", "VARCHAR"), ("amount", "VARCHAR"),
                              ("line_first", "BIGINT"), ("line_last", "BIGINT")])
            with self.assertRaises(FileExistsError):
                convert_csv(source, target, context=CONTEXT, encoding="utf-8", delimiter=";",
                            source_line_columns=("line_first", "line_last"))

    def test_verification_preserves_bom_dialect_leading_zeros_whitespace_and_quotes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'source.csv', root / 'table.parquet'
            source.write_text('コード;金額;名称\r\n001; 1,000 ;\'引用;符\'\r\n001;;NULL\r\n',
                              encoding='utf-8-sig', newline='')
            convert_csv(source, target, context=CONTEXT, encoding='utf-8-sig',
                        delimiter=';', quotechar="'", source_line_columns=('first', 'last'), batch_size=1)
            summary = verify_csv(source, target, encoding='utf-8-sig', delimiter=';', quotechar="'",
                                 source_line_columns=('first', 'last'), batch_size=1)
            self.assertEqual(summary, {'status': 'passed', 'row_count': 2, 'source_columns': 3})
            with duckdb.connect() as con:
                self.assertEqual(con.execute('SELECT * FROM read_parquet(?)', [str(target)]).fetchall(),
                                 [('001', ' 1,000 ', '引用;符', 2, 2), ('001', '', 'NULL', 3, 3)])

    def test_verification_rejects_corruption_even_when_row_count_and_total_match(self):
        columns = (ParquetColumn('code'), ParquetColumn('amount'),
                   ParquetColumn('source_line_start', 'BIGINT'), ParquetColumn('source_line_end', 'BIGINT'))
        original = [dict(zip([c.name for c in columns], row)) for row in
                    [('001', '10', 2, 2), ('002', '', 3, 3), ('001', '10', 4, 4)]]
        cases = {
            'value': [original[0] | {'code': '1'}, *original[1:]],
            'null': [original[0], original[1] | {'amount': None}, original[2]],
            'order': [original[2], original[1], original[0]],
            'duplicate': [original[0], original[0] | {'source_line_start': 3, 'source_line_end': 3}, original[2]],
            'missing': original[:-1],
            'extra': [*original, original[-1]],
            'position': [original[0] | {'source_line_end': 3}, *original[1:]],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.csv'
            source.write_text('code,amount\n001,10\n002,\n001,10\n')
            for name, rows in cases.items():
                with self.subTest(name=name):
                    table = root / f'{name}.parquet'
                    write_parquet(table, rows, columns=columns)
                    with self.assertRaisesRegex(ValueError, 'CSV preservation failed'):
                        verify_csv(source, table, encoding='utf-8', batch_size=1)
            for name, schema in [('order', columns[::-1]),
                                 ('type', (ParquetColumn('code', 'BIGINT'), *columns[1:]))]:
                with self.subTest(schema=name):
                    table = root / f'schema-{name}.parquet'
                    rows = original if name == 'order' else [row | {'code': int(row['code'])} for row in original]
                    write_parquet(table, rows, columns=schema)
                    with self.assertRaisesRegex(ValueError, 'column names/order/types'):
                        verify_csv(source, table, encoding='utf-8')

    def test_conversion_checks_written_bytes_and_removes_a_rejected_output(self):
        def corrupt_write(path, rows, **kwargs):
            return write_conversion(path, (row | {'code': '1'} for row in rows), **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, table = root / 'source.csv', root / 'table.parquet'
            source.write_text('code\n001\n')
            with patch('ingestion.lib.conversion.write_conversion', side_effect=corrupt_write):
                with self.assertRaisesRegex(ValueError, 'CSV preservation failed'):
                    convert_csv(source, table, context=CONTEXT, encoding='utf-8')
            self.assertFalse(table.exists())
            self.assertEqual(list(root.iterdir()), [source])

    def test_pdf_word_rows_use_the_same_conversion_result_without_metadata_inference(self):
        xml = '<doc><page><word xMin="10" yMin="10" xMax="40" yMax="20">議員報酬</word>' \
              '<word xMin="110" yMin="10" xMax="140" yMax="20">1,234</word></page></doc>'
        tokens = tokens_from_bbox_layout(xml, origin_id=CONTEXT.origin_id, first_page=109)
        table = assemble_table(place_tokens(tokens, {(CONTEXT.origin_id, 109): Placement("page")}),
                               TableLayout((Column("name", 0, 100), Column("amount", 100, 200))))
        rows = [{"name": row.cell("name").text, "amount": row.cell("amount").text,
                 "page": row.cell("amount").tokens[0].token.page} for row in table.rows]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pdf.parquet"
            result = write_conversion(target, rows, context=CONTEXT,
                                      columns=(ParquetColumn("name"), ParquetColumn("amount"),
                                               ParquetColumn("page", "INTEGER")))
            with duckdb.connect() as connection:
                self.assertEqual(connection.execute("SELECT * FROM read_parquet(?)", [str(target)]).fetchall(),
                                 [("議員報酬", "1,234", 109)])
            self.assertEqual(result.context, CONTEXT)
            self.assertEqual(result.row_count, 1)

    def test_unobserved_null_is_not_replaced_by_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "scan.parquet"
            result = write_conversion(target, [{"amount": None}, {"amount": "0"}], context=CONTEXT,
                                      columns=(ParquetColumn("amount"),))
            with duckdb.connect() as connection:
                self.assertEqual(connection.execute("SELECT * FROM read_parquet(?)", [str(target)]).fetchall(),
                                 [(None,), ("0",)])
            self.assertEqual(result.row_count, 2)

    def test_context_requires_references_and_does_not_define_year_or_account(self):
        for arguments in [("", "table", "code"), ("origin", "", "code"), ("origin", "table", " "),
                          ("origin", "table", "code", "")]:
            with self.assertRaises(ValueError):
                ConversionContext(*arguments)
        self.assertEqual(ConversionContext("origin", "table", "code").layout_ref, None)

    def test_output_retains_the_input_byte_identity_when_selection_keys_are_mutable(self):
        origins = (OriginReference("fudoki-inputs", "fiscal/source-selection/132047/2024/initial.pdf", "a" * 64, 100),
                   OriginReference("fudoki-inputs", "fiscal/source-selection/132047/2024/initial-2.pdf", "b" * 64, 200))
        context = ConversionContext("document", "table", "code", selection_ref='["132047",2024,"initial",null]', origins=origins)
        with tempfile.TemporaryDirectory() as directory:
            result = write_conversion(Path(directory) / "table.parquet", [{"value": "0"}],
                                      columns=(ParquetColumn("value"),), context=context)
            serialized = json.loads(json.dumps(asdict(result)))
            self.assertEqual(serialized["context"]["origins"], [asdict(origin) for origin in origins])
            self.assertEqual(serialized["context"]["selection_ref"], context.selection_ref)
        with self.assertRaises(ValueError):
            ConversionContext("origin", "table", "code", origins=(origins[0], origins[0]))
        with self.assertRaises(ValueError):
            OriginReference("bucket", "key", "unknown", 100)


if __name__ == "__main__":
    unittest.main()
