"""Convert raw rows to local Parquet and return references to the caller."""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from ingestion.lib.parquet import ParquetColumn, write_parquet


@dataclass(frozen=True)
class OriginReference:
    bucket: str
    key: str
    sha256: str
    bytes: int

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value.strip() for value in (self.bucket, self.key)):
            raise ValueError("Origin bucket and key must be nonempty strings")
        if not isinstance(self.sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", self.sha256):
            raise ValueError("Origin SHA-256 must be a lowercase hex digest")
        if type(self.bytes) is not int or self.bytes < 0:
            raise ValueError("Origin byte count must be a nonnegative integer")


@dataclass(frozen=True)
class ConversionContext:
    origin_id: str
    table_id: str
    extractor_ref: str
    layout_ref: str | None = None
    selection_ref: str | None = None
    origins: tuple[OriginReference, ...] = ()

    def __post_init__(self) -> None:
        for value in (self.origin_id, self.table_id, self.extractor_ref):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Origin, table and extractor references must be nonempty strings")
        if self.layout_ref is not None and (not isinstance(self.layout_ref, str) or not self.layout_ref.strip()):
            raise ValueError("Layout reference must be a nonempty string or None")
        if self.selection_ref is not None and (not isinstance(self.selection_ref, str) or not self.selection_ref.strip()):
            raise ValueError("Selection reference must be a nonempty string or None")
        if not isinstance(self.origins, tuple) or any(not isinstance(origin, OriginReference) for origin in self.origins):
            raise TypeError("origins must be a tuple of OriginReference objects")
        if len({origin.sha256 for origin in self.origins}) != len(self.origins):
            raise ValueError("Duplicate original byte identities")


@dataclass(frozen=True)
class ConversionResult:
    context: ConversionContext
    path: str
    sha256: str
    bytes: int
    row_count: int


def write_conversion(path: Path, rows: Iterable[Mapping[str, object]], *,
                     columns: Sequence[ParquetColumn], context: ConversionContext,
                     batch_size: int = 1000) -> ConversionResult:
    """Write a new local table without registering inputs or contacting storage.

    PDF adapters supply assembled rows, including original positions and any
    unresolved observations. Supplied references are returned unchanged.
    """
    if not isinstance(context, ConversionContext):
        raise TypeError("context must be a ConversionContext")
    path = Path(path)
    count = write_parquet(path, rows, columns=columns, batch_size=batch_size)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return ConversionResult(context, str(path.resolve()), digest.hexdigest(), size, count)


def convert_csv(source: Path, destination: Path, *, context: ConversionContext,
                encoding: str, delimiter: str = ",", quotechar: str = '"',
                source_line_columns: tuple[str, str] = ("source_line_start", "source_line_end"),
                batch_size: int = 1000) -> ConversionResult:
    """Convert a headered CSV without type inference or discarded records.

    Empty fields remain empty strings. Physical line ranges include quoted
    multiline fields. Re-read the original and compare every stored value before
    returning. The caller declares decoding and CSV dialect settings.
    Headerless CSVs and other formats use write_conversion with explicit rows.
    """
    if len(source_line_columns) != 2:
        raise ValueError("Specify start and end source-line column names")
    with Path(source).open("r", encoding=encoding, errors="strict", newline="") as stream:
        reader = csv.reader(stream, delimiter=delimiter, quotechar=quotechar, strict=True)
        try:
            header = next(reader)
        except StopIteration as error:
            raise ValueError("CSV header is required") from error
        if not header:
            raise ValueError("CSV header is required")
        columns = tuple(ParquetColumn(name) for name in header) + tuple(
            ParquetColumn(name, "BIGINT", nullable=False) for name in source_line_columns)

        def records():
            previous_end = reader.line_num
            for fields in reader:
                start, end = previous_end + 1, reader.line_num
                previous_end = end
                if len(fields) != len(header):
                    raise ValueError(f"CSV lines {start}-{end}: expected {len(header)} fields, got {len(fields)}")
                row = dict(zip(header, fields, strict=True))
                row[source_line_columns[0]] = start
                row[source_line_columns[1]] = end
                yield row

        result = write_conversion(destination, records(), columns=columns,
                                  context=context, batch_size=batch_size)
    try:
        verify_csv(source, destination, encoding=encoding, delimiter=delimiter,
                   quotechar=quotechar, source_line_columns=source_line_columns,
                   batch_size=batch_size)
    except BaseException:
        # The output was created by this invocation; a rejected conversion must
        # not leave a table that a caller could mistake for a verified result.
        Path(destination).unlink(missing_ok=True)
        raise
    return result


def verify_csv(source: Path, table: Path, *, encoding: str,
               delimiter: str = ",", quotechar: str = '"',
               source_line_columns: tuple[str, str] = ("source_line_start", "source_line_end"),
               batch_size: int = 1000) -> dict:
    """Compare a CSV with Parquet, including order, duplicates and line ranges.

    This checks preservation under the declared encoding/dialect, without
    interpreting amounts or deciding whether the original itself is correct.
    Compare in batches without loading all rows into Python.
    """
    import duckdb

    if len(source_line_columns) != 2:
        raise ValueError("Specify start and end source-line column names")
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    with Path(source).open("r", encoding=encoding, errors="strict", newline="") as stream, \
            duckdb.connect(config={"threads": 1, "preserve_insertion_order": True}) as con:
        reader = csv.reader(stream, delimiter=delimiter, quotechar=quotechar, strict=True)
        header = next(reader, None)
        if not header:
            raise ValueError("CSV header is required")
        columns = [ParquetColumn(name) for name in header] + [
            ParquetColumn(name, "BIGINT", nullable=False) for name in source_line_columns]
        names = [column.name for column in columns]
        if len({name.lower() for name in names}) != len(names):
            raise ValueError("CSV and source-line columns must be distinct")
        schema = con.execute(
            "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false)", [str(table)]).fetchall()
        if [(row[0], row[1]) for row in schema] != [(column.name, column.type) for column in columns]:
            raise ValueError("CSV preservation failed: Parquet column names/order/types differ")
        cursor = con.execute("SELECT * FROM read_parquet(?, hive_partitioning=false)", [str(table)])
        previous_end = reader.line_num
        count = 0
        while batch := cursor.fetchmany(batch_size):
            for stored in batch:
                fields = next(reader, None)
                if fields is None:
                    raise ValueError("CSV preservation failed: Parquet contains extra rows")
                start, end = previous_end + 1, reader.line_num
                previous_end = end
                if len(fields) != len(header):
                    raise ValueError(f"CSV lines {start}-{end}: expected {len(header)} fields, got {len(fields)}")
                count += 1
                expected = (*fields, start, end)
                for name, value, actual in zip(names, expected, stored, strict=True):
                    if value != actual:
                        raise ValueError(f"CSV preservation failed: record {count}, lines {start}-{end}, column {name!r} differs")
        if next(reader, None) is not None:
            raise ValueError("CSV preservation failed: Parquet is missing CSV rows")
    return {"status": "passed", "row_count": count, "source_columns": len(header)}
