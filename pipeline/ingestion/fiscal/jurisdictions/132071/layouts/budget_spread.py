"""Keep the measured layout file in the ingestion dependency fingerprint."""
from pathlib import Path

PROFILE = Path(__file__).with_name('budget_spread.json')
