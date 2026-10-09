"""Restore the originals selected upstream; conversion never selects another URL."""
import argparse
import json
from pathlib import Path
from ingestion.fiscal.run import originals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--remote', action='store_true')
    args = parser.parse_args()
    print(json.dumps(originals(args.manifest, args.output, remote=args.remote)))


if __name__ == '__main__':
    main()
