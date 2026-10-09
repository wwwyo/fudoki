"""Write explicitly typed raw rows, preserving strings, nulls and duplicates."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Iterable, Mapping, Sequence


_PYTHON_TYPES = {"VARCHAR": (str,), "BIGINT": (int,), "INTEGER": (int,),
                 "DOUBLE": (int, float), "BOOLEAN": (bool,)}


@dataclass(frozen=True)
class ParquetColumn:
    name: str
    type: str = "VARCHAR"
    nullable: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name or "\0" in self.name:
            raise ValueError("Column name must be nonempty and contain no null byte")
        if self.type not in _PYTHON_TYPES or type(self.nullable) is not bool:
            raise ValueError("Choose an explicit supported column type and nullability")

    def validate(self, value: object) -> None:
        if value is None:
            if not self.nullable:
                raise ValueError(f"{self.name} does not allow NULL")
            return
        if type(value) not in _PYTHON_TYPES[self.type]:
            raise ValueError(f"{self.name} requires {self.type}; implicit coercion is disabled")


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def write_parquet(path: Path, rows: Iterable[Mapping[str, object]], *,
                  columns: Sequence[ParquetColumn], batch_size: int = 1000) -> int:
    """Create a new Parquet file atomically; never overwrite an existing input.

    Every record must specify every column, including explicit NULLs. Input
    order and duplicate rows are retained. Failure leaves no partial output.
    """
    import duckdb

    names = tuple(column.name for column in columns)
    name_set = set(names)
    folded_names = {name.lower() for name in names}
    # DuckDB identifiers are case-insensitive, even when quoted.
    if not names or len(folded_names) != len(names):
        raise ValueError("Parquet columns must be nonempty and distinct")
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    order_column = "_ingestion_order"
    while order_column.lower() in folded_names:
        order_column += "_"
    declarations = [f"{_quote(c.name)} {c.type}" + ("" if c.nullable else " NOT NULL") for c in columns]
    placeholders = ",".join("?" for _ in range(len(names) + 1))
    source = iter(rows)
    count = 0
    handle, temporary_name = tempfile.mkstemp(prefix=".parquet-", suffix=".parquet", dir=path.parent)
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        with duckdb.connect() as connection:
            connection.execute(f"CREATE TABLE data ({_quote(order_column)} BIGINT, {', '.join(declarations)})")
            while batch := list(islice(source, batch_size)):
                values = []
                for row in batch:
                    if set(row) != name_set:
                        raise ValueError("Record columns differ from declared schema")
                    for column in columns:
                        column.validate(row[column.name])
                    values.append((count, *(row[name] for name in names)))
                    count += 1
                connection.executemany(f"INSERT INTO data VALUES ({placeholders})", values)
            selection = ",".join(_quote(name) for name in names)
            connection.execute(
                f"COPY (SELECT {selection} FROM data ORDER BY {_quote(order_column)}) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                [str(temporary)])
        # link is an atomic create-if-absent; replace would clobber a concurrent writer.
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return count
