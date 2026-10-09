"""Public table assembly and Parquet boundaries, including unresolved data."""

import tempfile
import unittest
from pathlib import Path

import duckdb

from ingestion.lib.parquet import ParquetColumn, write_parquet
from ingestion.lib.pdf_table import (
    Box, Column, Heading, HierarchyContext, Placement, RowBand, TableLayout,
    Token, assemble_table, join_wrapped_rows, place_tokens,
    tokens_from_bbox_layout, tokens_from_vision,
)


def positioned(text, box, *, id="word", page=1):
    token = Token(id, "origin", page, text, Box(*box) if box else None)
    return place_tokens([token], {("origin", page): Placement("table")})[0]


class TableAssembly(unittest.TestCase):
    def test_spread_coordinates_join_one_row_and_keep_source_pages(self):
        xml = '''<html xmlns="http://www.w3.org/1999/xhtml"><body><doc>
        <page><word xMin="10" yMin="10" xMax="40" yMax="20">議員報酬</word></page>
        <page><word xMin="5" yMin="12" xMax="40" yMax="22">1,234</word></page>
        </doc></body></html>'''
        tokens = tokens_from_bbox_layout(xml, origin_id="sha", first_page=109)
        placed = place_tokens(tokens, {("sha", 109): Placement("spread"),
            ("sha", 110): Placement("spread", offset_x=100, offset_y=-2)})
        table = assemble_table(placed, TableLayout((Column("name", 0, 100), Column("amount", 100, 200))))
        self.assertEqual(len(table.rows), 1)
        row = table.rows[0]
        self.assertEqual((row.cell("name").text, row.cell("amount").text), ("議員報酬", "1,234"))
        amount = row.cell("amount").tokens[0]
        self.assertEqual(amount.token.page, 110)
        self.assertEqual(amount.token.bbox, Box(5, 12, 40, 22))
        self.assertEqual(amount.bbox, Box(105, 10, 140, 20))

    def test_row_clustering_does_not_chain_separate_baselines(self):
        tokens = [positioned(str(i), (0, y, 5, y + 1), id=str(i))
                  for i, y in enumerate((0, 0.8, 1.6))]
        table = assemble_table(tokens, TableLayout((Column("name", 0, 10),), row_tolerance=1))
        self.assertEqual([r.cell("name").text for r in table.rows], ["01", "2"])

    def test_declared_empty_row_and_zero_are_distinct(self):
        tokens = [positioned("0", (0, 0, 5, 5), id="zero"),
                  positioned("", (0, 20, 5, 25), id="empty-text")]
        table = assemble_table(tokens, TableLayout((Column("amount", 0, 10),),
            row_bands=(RowBand(0, 10), RowBand(10, 20), RowBand(20, 30))))
        cells = [r.cell("amount") for r in table.rows]
        self.assertEqual([(c.text, c.status) for c in cells],
                         [("0", "observed"), (None, "unobserved"), ("", "observed")])

    def test_ambiguous_columns_unavailable_boxes_and_outside_rows_are_retained(self):
        tokens = [positioned("wide name", (0, 0, 150, 5), id="wide"),
                  positioned("no box", None, id="null"),
                  positioned("outside", (0, 30, 5, 35), id="outside")]
        layout = TableLayout((Column("left", 0, 100, anchor="left"),
                              Column("right", 100, 200, anchor="right")),
                             row_bands=(RowBand(0, 10),))
        table = assemble_table(tokens, layout)
        self.assertEqual({t.token.id for t in table.unassigned}, {"wide", "null", "outside"})
        self.assertTrue(all(c.status == "unobserved" for c in table.rows[0].cells))

    def test_right_anchor_retains_name_that_crosses_column_boundary(self):
        name = positioned("long name", (0, 0, 130, 5))
        table = assemble_table([name], TableLayout((Column("name", 0, 100, anchor="left"),
                                                   Column("amount", 150, 200, anchor="right"))))
        self.assertEqual(table.rows[0].cell("name").text, "long name")
        self.assertFalse(table.unassigned)

    def test_distinct_duplicate_prints_are_not_silently_removed(self):
        words = [positioned("0", (0, 0, 5, 5), id=id) for id in ("a", "b")]
        table = assemble_table(words, TableLayout((Column("amount", 0, 10, separator=" "),)))
        self.assertEqual(table.rows[0].cell("amount").text, "0 0")
        with self.assertRaises(ValueError):
            assemble_table([words[0], words[0]], TableLayout((Column("amount", 0, 10),)))

    def test_confirmed_name_continuations_preserve_amount_and_all_boxes(self):
        layout = TableLayout((Column("name", 0, 100), Column("amount", 100, 200)), row_tolerance=1)
        words = [positioned("償還金・利子", (0, 0, 80, 5), id="name1"),
                 positioned("1,234", (110, 0, 150, 5), id="amount"),
                 positioned("及び割引料", (0, 10, 80, 15), id="name2")]
        table = assemble_table(words, layout)
        row = join_wrapped_rows(table.rows, columns=("name",))
        self.assertEqual(row.cell("name").text, "償還金・利子及び割引料")
        self.assertEqual(row.cell("amount").text, "1,234")
        self.assertEqual(len(row.cell("name").tokens), 2)
        self.assertEqual(row.source_rows, (1, 2))
        second_amount = positioned("5,678", (110, 10, 150, 15), id="other-amount")
        conflicting = assemble_table([*words, second_amount], layout)
        with self.assertRaises(ValueError):
            join_wrapped_rows(conflicting.rows, columns=("name",))

    def test_canvas_and_unit_boundaries_cannot_be_silently_combined(self):
        tokens = [Token("a", "origin", 1, "name", Box(0, 0, 10, 10)),
                  Token("b", "origin", 2, "money", Box(0, 0, 10, 10))]
        placed = place_tokens(tokens, {("origin", 1): Placement("page1"), ("origin", 2): Placement("page2")})
        with self.assertRaises(ValueError):
            assemble_table(placed, TableLayout((Column("name", 0, 100),)))
        with self.assertRaises(ValueError):
            place_tokens(tokens[:1], {("origin", 1): Placement("page1", input_unit="px")})
        scaled = place_tokens(tokens[:1], {("origin", 1): Placement("page1", output_unit="px", scale_x=2, scale_y=2)})
        self.assertEqual(scaled[0].bbox, Box(0, 0, 20, 20))
        self.assertEqual(scaled[0].token.unit, "pt")


class OcrAdapter(unittest.TestCase):
    def test_one_observation_level_keeps_unavailable_boxes(self):
        result = {"origin": {"sha256": "sha"}, "pages": [{"page_number": 2,
            "displayed_pdf_size_pt": [100, 200], "regions": [{"id": "column", "observations": [
                {"id": "parent", "kind": "region", "raw_text": "0", "bbox_pdf_pt": [1, 2, 3, 4]},
                {"id": "child", "parent_id": "parent", "kind": "word", "raw_text": "0", "bbox_pdf_pt": None},
                {"id": "number", "kind": "number", "raw_text": "0", "bbox_pdf_pt": [1, 2, 3, 4]}]}]}]}
        tokens = tokens_from_vision(result, kind="word", region_ids=["column"])
        self.assertEqual(len(tokens), 1)
        self.assertEqual((tokens[0].id, tokens[0].raw_text, tokens[0].bbox), ("child", "0", None))
        self.assertEqual(tokens[0].parent_id, "parent")
        with self.assertRaises(ValueError):
            tokens_from_vision(result, kind="word", region_ids=["missing"])


class HierarchyInheritance(unittest.TestCase):
    def test_repeated_heading_keeps_descendants_and_parent_change_clears_them(self):
        context = HierarchyContext(("kan", "kou", "moku", "project"))
        context.update("kan", Heading("2 総務費", ("p1-kan",)))
        context.update("kou", Heading("1 総務管理費"))
        context.update("moku", Heading("1 一般管理費"))
        context.update("project", Heading("職員給与費"))
        snapshot = context.snapshot()
        context.update("kan", Heading("2 総務費", ("p2-kan",)))
        self.assertEqual(context.snapshot()["project"].value, "職員給与費")
        context.update("kou", Heading("2 徴税費"))
        self.assertIsNone(context.snapshot()["moku"])
        self.assertIsNone(context.snapshot()["project"])
        self.assertEqual(snapshot["moku"].value, "1 一般管理費")
        context.reset()
        self.assertTrue(all(value is None for value in context.snapshot().values()))


class ParquetBoundaries(unittest.TestCase):
    def test_roundtrip_keeps_raw_strings_null_empty_zero_and_duplicate_order(self):
        columns = (ParquetColumn("name"), ParquetColumn("amount"), ParquetColumn("page", "INTEGER"))
        rows = [{"name": "01 議員報酬", "amount": "1,234", "page": 109},
                {"name": "empty", "amount": "", "page": None},
                {"name": "missing", "amount": None, "page": 110},
                {"name": "zero", "amount": "0", "page": 110}]
        rows.append(rows[0].copy())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.parquet"
            self.assertEqual(write_parquet(path, iter(rows), columns=columns, batch_size=2), 5)
            with duckdb.connect() as connection:
                actual = connection.execute("SELECT * FROM read_parquet(?)", [str(path)]).fetchall()
            self.assertEqual(actual, [(r["name"], r["amount"], r["page"]) for r in rows])
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                write_parquet(path, [], columns=columns)
            self.assertEqual(path.read_bytes(), before)

    def test_bad_later_record_leaves_no_partial_file(self):
        columns = (ParquetColumn("amount", nullable=False),)
        for invalid in [{"amount": 0}, {"amount": None}, {"amount": "0", "extra": "lost"}, {}]:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "data.parquet"
                with self.assertRaises(ValueError):
                    write_parquet(path, [{"amount": "1,234"}, invalid], columns=columns, batch_size=1)
                self.assertFalse(path.exists())
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_empty_table_keeps_schema_and_quoted_names(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.parquet"
            columns = (ParquetColumn('a"b'), ParquetColumn("_ingestion_order", "INTEGER"))
            self.assertEqual(write_parquet(path, [], columns=columns), 0)
            with duckdb.connect() as connection:
                schema = connection.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()
            self.assertEqual([(r[0], r[1]) for r in schema], [('a"b', 'VARCHAR'), ('_ingestion_order', 'INTEGER')])
            with self.assertRaises(ValueError):
                write_parquet(Path(directory) / "bad.parquet", [], columns=(ParquetColumn("name"), ParquetColumn("NAME")))


if __name__ == "__main__":
    unittest.main()
