#!/usr/bin/env python3
"""
Clear Qdrant collections utility.

Usage:
  python clear_qdrant.py              # Clear both collections
  python clear_qdrant.py --collection docs  # Clear only docs collection
  python clear_qdrant.py --collection code  # Clear only code collection
  python clear_qdrant.py --list         # List all collections
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from indexer import _client, list_collections


def clear_collection(name: str) -> bool:
    """Delete a collection if it exists."""
    client = _client()
    if client.collection_exists(name):
        client.delete_collection(name)
        print(f"✓ Deleted collection: {name}")
        return True
    else:
        print(f"  Collection does not exist: {name}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Clear Qdrant collections")
    parser.add_argument(
        "--collection", "-c",
        type=str,
        choices=["docs", "code", "both"],
        default="both",
        help="Which collection(s) to clear (default: both)",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        dest="list_only",
        help="List all collections without deleting",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt",
    )

    args = parser.parse_args()

    # List collections
    if args.list_only:
        collections = list_collections()
        print(f"Found {len(collections)} collection(s):")
        for name in collections:
            try:
                info = _client().get_collection(name)
                count = info.points_count
                print(f"  - {name}: {count:,} points")
            except Exception as e:
                print(f"  - {name}: error - {e}")
        return

    # Clear collections
    collections_to_clear = []
    if args.collection in ("both", "docs"):
        collections_to_clear.append(Config.DOCS_COLLECTION)
    if args.collection in ("both", "code"):
        collections_to_clear.append(Config.CODE_COLLECTION)

    if not args.yes:
        print(f"About to delete the following collections:")
        for name in collections_to_clear:
            print(f"  - {name}")
        response = input("\nAre you sure? This will permanently delete all data. (y/N): ")
        if response.lower() != 'y':
            print("Aborted.")
            sys.exit(0)

    print()
    deleted_count = 0
    for name in collections_to_clear:
        if clear_collection(name):
            deleted_count += 1

    print(f"\n✓ Cleared {deleted_count} collection(s)")


if __name__ == "__main__":
    main()
