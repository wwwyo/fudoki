"""Normal provider export stays lazy for the explicit-objects original-only CLI."""

def get_sources():
    from .registration import get_sources as load
    return load()
