"""Retained tables are imported byte-for-byte; they are not a fresh extraction."""
def convert(inputs, destination, options):
    raise ValueError('Retained table: restore its current Parquet, or specify an extraction layout before re-converting')
