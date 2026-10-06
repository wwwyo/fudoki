"""Materialize positional CSV candidates without adopting or interpreting fiscal rows.

Tama settlement attachments include empty/duplicate header cells, layout rows,
blank records, and headerless masters. Keep every record and its lexical syntax;
the declared header count never implies that the remaining records are amounts.
This helper writes only to the caller's candidate directory, never the input lock.
"""
from __future__ import annotations
from ingestion.inputs import record_input, save_object

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

import duckdb


def materialize(original: Path, output: Path, *, expected_sha256: str,
                encoding: str, header_records: int,
                metadata: dict | None = None) -> dict:
    body = original.read_bytes()
    sha = hashlib.sha256(body).hexdigest()
    if sha != expected_sha256:
        raise ValueError(f"Original SHA differs: {sha}")
    text = body.decode(encoding)
    if text.encode(encoding) != body:
        raise ValueError("CSV encoding is not reversible")
    lines = io.StringIO(text, newline="").readlines()
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    cells, records = [], []
    previous = 0
    for row in reader:
        cells.append(row)
        records.append("".join(lines[previous:reader.line_num]))
        previous = reader.line_num
    if "".join(records) != text:
        raise ValueError("Lexical CSV records do not reconstruct original text")
    if not 0 <= header_records <= len(records):
        raise ValueError("Invalid declared header record count")
    width = max(map(len, cells), default=0)
    columns = [f"cell_{i + 1:03}" for i in range(width)]
    output.mkdir(parents=True, exist_ok=True)
    db = duckdb.connect()
    db.execute("create table records(source_record bigint, record_role varchar, "
               "cell_count bigint, cells_json varchar, csv_record varchar)")
    if records:
        db.executemany("insert into records values (?,?,?,?,?)", [
            (i + 1, "header" if i < header_records else "data", len(row),
             json.dumps(row, ensure_ascii=False), records[i])
            for i, row in enumerate(cells)
        ])
    schema = ("source_row bigint, source_record bigint, cell_count bigint, "
              "cells_json varchar, csv_record varchar"
              + "".join(f", {name} varchar" for name in columns))
    db.execute(f"create table data({schema})")
    data = [(i + 1 - header_records, i + 1, len(row),
             json.dumps(row, ensure_ascii=False), records[i],
             *row, *([None] * (width - len(row))))
            for i, row in enumerate(cells) if i >= header_records]
    if data:
        db.executemany("insert into data values ("
                       + ",".join("?" for _ in range(5 + width)) + ")", data)
    for name in ["records", "data"]:
        db.execute(f"copy {name} to ? (format parquet)", [str(output / f"{name}.parquet")])
    # Read materialized records/cells, not the in-memory insert values.
    readback = db.execute("select source_record,cell_count,cells_json,csv_record "
                          "from read_parquet(?, hive_partitioning=false) order by source_record",
                          [str(output / "records.parquet")]).fetchall()
    if [json.loads(r[2]) for r in readback] != cells:
        raise ValueError("Materialized cells differ from the original CSV")
    restored = "".join(r[3] for r in readback).encode(encoding)
    if restored != body:
        raise ValueError("Materialized records do not reconstruct original bytes")
    read_data = db.execute("select * from read_parquet(?, hive_partitioning=false) order by source_row",
                           [str(output / "data.parquet")]).fetchall()
    if read_data != data:
        raise ValueError("Materialized positional data differs from original records")
    header_text = "".join(records[:header_records])
    if (header_text + "".join(row[4] for row in read_data)).encode(encoding) != body:
        raise ValueError("Data table and lexical header do not reconstruct original bytes")
    schema_readback = db.execute("describe select * from read_parquet(?, hive_partitioning=false)",
                                [str(output / "data.parquet")]).fetchall()
    hashes = {name: dict(sha256=hashlib.sha256((output / name).read_bytes()).hexdigest(),
                         bytes=(output / name).stat().st_size)
              for name in ["data.parquet", "records.parquet"]}
    provenance = dict(metadata or {}, sha256=sha, bytes=len(body), encoding=encoding,
                      raw_form="verbatim", header_records=header_records,
                      header=cells[:header_records], rows=len(data), records=len(records),
                      csv_layout=dict(header_record=header_text, trailing_records="",
                                      record_column="csv_record", bom_in_encoding=encoding == "utf-8-sig"),
                      positional_width=width,
                      observed_width_counts={str(w): sum(len(r) == w for r in cells[header_records:])
                                             for w in sorted(set(map(len, cells[header_records:])))},
                      empty_record_count=sum(not any(c.strip() for c in row)
                                             for row in cells[header_records:]),
                      helper="materialize_tama_settlement_candidates@1",
                      helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      verification="encoding + lexical-byte-roundtrip + positional-cell-readback",
                      roundtrip_verified=True, schema=[dict(name=r[0], type=r[1])
                                                       for r in schema_readback], tables=hashes)
    save_object('origin', body)
    if metadata and all(k in metadata for k in ['jurisdiction_code', 'fiscal_year', 'request_url']):
        record_input(output, provenance)
    db.close()
    return provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True,
                        help="JSON array with original/output/expected_sha256/encoding/header_records/metadata")
    args = parser.parse_args()
    for candidate in json.loads(args.manifest.read_text()):
        result = materialize(Path(candidate["original"]), Path(candidate["output"]),
                             expected_sha256=candidate["expected_sha256"],
                             encoding=candidate["encoding"],
                             header_records=candidate["header_records"],
                             metadata=candidate.get("metadata"))
        print(json.dumps(dict(output=candidate["output"], sha256=result["sha256"],
                              records=result["records"], rows=result["rows"],
                              tables=result["tables"]), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
