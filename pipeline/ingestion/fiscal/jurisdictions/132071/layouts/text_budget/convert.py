"""Measured Akishima text statement entry for the existing ingestion manager."""
from importlib import import_module

from ingestion.fiscal.layouts.statement.text_document import convert as convert_text_document
from ingestion.fiscal.manifest import INGESTION


PROFILE = import_module('ingestion.fiscal.jurisdictions.132071.layouts.budget_spread').PROFILE


def convert(inputs, destination, options):
    if any(source['target']['jurisdiction'] != '132071' for source in inputs):
        raise ValueError('This measured layout belongs to Akishima')
    return convert_text_document(inputs, destination, {
        **options, 'profile': str(PROFILE.relative_to(INGESTION)),
    })
