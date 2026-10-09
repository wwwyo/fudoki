"""Shared dbt staging normalization."""

import re
import unicodedata

from dbt.adapters.duckdb.plugins import BasePlugin


def normalize_text(value: str) -> str:
    return unicodedata.normalize('NFKC', value).strip()


def normalize_amount(value: str) -> int:
    text = normalize_text(value).removesuffix('円').strip().replace(',', '')
    text = text.replace('△', '-').replace('−', '-')
    if not re.fullmatch(r'[+-]?[0-9]+', text):
        raise ValueError(f'Invalid integer amount: {value!r}')
    return int(text)


class Plugin(BasePlugin):
    def configure_connection(self, conn):
        conn.create_function('staging_text', normalize_text)
        conn.create_function('staging_amount', normalize_amount)
