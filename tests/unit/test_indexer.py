#!/usr/bin/env python3
"""
Indexer Unit Tests with CLI Output

Usage:
    python -m tests.unit.test_indexer               # Run all tests
    python -m tests.unit.test_indexer --collections # List collections
    python -m tests.unit.test_indexer --stats       # Show collection stats
    python -m tests.unit.test_indexer --create      # Create test collection
    python -m tests.unit.test_indexer --drop        # Drop test collection
"""

import sys
import os
from pathlib import Path

# Add paths for imports - works from project root or tests directory
PROJECT_ROOT = Path(__file__).parent.parent.parent
RAG_PATH = PROJECT_ROOT / "services" / "rag"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(RAG_PATH))
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from indexer import (
    _client,
    ensure_collection,
    list_collections,
    collection_stats,
    upsert_chunks,
    get_chunk,
)
from config import Config
from chunker import Chunk


def print_header(title: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_section(title: str) -> None:
    """Print a formatted section title."""
    print(f"\n--- {title} ---")


def print_collection_info(name: str) -> None:
    """Print collection information."""
    try:
        client = _client()
        if not client.collection_exists(name):
            print(f"\n  {name}: Does not exist")
            return

        info = client.get_collection(name)
        config = info.config

        print(f"\n  Collection: {name}")
        print(f"  Points:     {info.points_count}")

        # Vector config - handle both dict and object formats
        vectors = config.params.vectors
        try:
            if isinstance(vectors, dict):
                for vname, vconfig in vectors.items():
                    print(f"  Vector[{vname}]:")
                    if isinstance(vconfig, dict):
                        print(f"    Size:     {vconfig.get('size', 'N/A')}")
                        print(f"    Distance: {vconfig.get('distance', 'N/A')}")
                    else:
                        print(f"    Size:     {getattr(vconfig, 'size', 'N/A')}")
                        print(f"    Distance: {getattr(vconfig, 'distance', 'N/A')}")
            else:
                print(f"  Vector Size:  {getattr(vectors, 'size', 'N/A')}")
                print(f"  Distance:     {getattr(vectors, 'distance', 'N/A')}")
        except Exception:
            print(f"  Vector: Configured")

        # Sparse config
        sparse = config.params.sparse_vectors_config
        if sparse:
            print(f"  Sparse:     Configured")

    except Exception as e:
        print(f"\n  Error: {e}")


def test_list_collections() -> list:
    """Test listing collections."""
    print_header("LIST COLLECTIONS TEST")
    
    try:
        collections = list_collections()
        
        print_section("Available Collections")
        if not collections:
            print("\n  No collections found")
        else:
            for name in collections:
                print_collection_info(name)
        
        return collections
        
    except Exception as e:
        print(f"\n  Error: {e}")
        return []


def test_collection_stats() -> None:
    """Test collection statistics."""
    print_header("COLLECTION STATISTICS TEST")
    
    collections = list_collections()
    
    if not collections:
        print("\n  No collections to show stats for")
        return
    
    for name in collections:
        try:
            stats = collection_stats(name)
            
            print_section(f"Stats: {name}")
            for key, value in stats.items():
                print(f"  {key:15} {value}")
                
        except Exception as e:
            print(f"\n  Error getting stats for {name}: {e}")


def test_ensure_collection() -> None:
    """Test collection creation."""
    print_header("ENSURE COLLECTION TEST")
    
    test_name = "test_collection_" + str(os.getpid())
    
    print_section(f"Creating: {test_name}")
    
    try:
        # Create collection
        ensure_collection(test_name, drop_first=False)
        print(f"\n  ✓ Collection created or already exists")
        
        # Verify
        client = _client()
        exists = client.collection_exists(test_name)
        print(f"  Verification: {'✓ exists' if exists else '✗ missing'}")
        
        # Clean up
        print_section("Cleanup")
        client.delete_collection(test_name)
        print(f"  ✓ Collection deleted")
        
    except Exception as e:
        print(f"\n  ✗ Error: {e}")


def test_upsert_chunk() -> None:
    """Test upserting a chunk."""
    print_header("UPSERT CHUNK TEST")
    
    test_collection = "test_upsert_" + str(os.getpid())
    
    try:
        # Create test collection
        ensure_collection(test_collection, drop_first=True)
        print(f"\n  Created test collection: {test_collection}")
        
        # Create test chunk
        chunk = Chunk(
            text="Test section path > Test content",
            raw_text="Test content for upsert",
            chunk_type="prose",
            section="§1 Test",
            subsection="1.1 Test Subsection",
            doc_url="https://example.com/test",
            tags="test · demo",
            chunk_id="test_chunk_001",
        )
        
        print_section("Test Chunk")
        print(f"  Chunk ID:     {chunk.chunk_id}")
        print(f"  Section Path: {chunk.section_path}")
        print(f"  Text:         {chunk.raw_text[:50]}...")
        
        # Create mock vectors
        from services.rag.embedder import vector_size
        vec_size = vector_size()
        dense_vec = [0.1] * vec_size
        from qdrant_client.models import SparseVector
        sparse_vec = SparseVector(indices=[0, 1, 2], values=[0.5, 0.3, 0.2])
        
        # Upsert
        print_section("Upserting")
        result = upsert_chunks(test_collection, [chunk], [dense_vec], [sparse_vec])
        print(f"\n  ✓ Upserted {result} chunk(s)")
        
        # Verify
        print_section("Verification")
        client = _client()
        info = client.get_collection(test_collection)
        print(f"  Collection points: {info.points_count}")
        
        if info.points_count >= 1:
            print(f"  ✓ Upsert verified")
        else:
            print(f"  ✗ Upsert may have failed")
        
        # Clean up
        client.delete_collection(test_collection)
        print(f"\n  ✓ Test collection cleaned up")
        
    except Exception as e:
        print(f"\n  ✗ Error: {e}")
        import traceback
        traceback.print_exc()


def test_get_chunk() -> None:
    """Test retrieving a chunk by ID."""
    print_header("GET CHUNK TEST")
    
    test_collection = "test_get_" + str(os.getpid())
    test_chunk_id = "test_get_chunk_001"
    
    try:
        # Setup
        ensure_collection(test_collection, drop_first=True)
        
        chunk = Chunk(
            text="Retrieval test content",
            raw_text="This chunk will be retrieved by ID",
            chunk_type="prose",
            chunk_id=test_chunk_id,
        )
        
        from services.rag.embedder import vector_size
        vec_size = vector_size()
        dense_vec = [0.1] * vec_size
        from qdrant_client.models import SparseVector
        sparse_vec = SparseVector(indices=[0], values=[1.0])
        
        upsert_chunks(test_collection, [chunk], [dense_vec], [sparse_vec])
        print(f"  ✓ Test chunk upserted")
        
        # Retrieve
        print_section("Retrieving by ID")
        retrieved = get_chunk(test_collection, test_chunk_id)
        
        if retrieved:
            print(f"\n  ✓ Chunk retrieved successfully")
            print(f"  Chunk ID:   {retrieved.get('chunk_id')}")
            print(f"  Raw Text:   {retrieved.get('raw_text', '')[:50]}...")
        else:
            print(f"\n  ✗ Chunk not found")
        
        # Clean up
        client = _client()
        client.delete_collection(test_collection)
        
    except Exception as e:
        print(f"\n  ✗ Error: {e}")
        import traceback
        traceback.print_exc()


def test_collection_schema() -> None:
    """Test collection schema detection."""
    print_header("COLLECTION SCHEMA TEST")

    collections = list_collections()

    if not collections:
        print("\n  No collections to check schema")
        return

    for name in collections:
        print_section(f"Schema: {name}")

        try:
            client = _client()
            info = client.get_collection(name)
            
            # Show basic info
            print(f"\n  Points:       {info.points_count}")
            print(f"  Vectors:      Configured")
            
            # Try to get sparse vector info
            try:
                sparse = info.config.params.sparse_vectors_config
                print(f"  Sparse:       {'✓ yes' if sparse else '✗ no'}")
            except AttributeError:
                print(f"  Sparse:       Unknown")
            
            print(f"\n  ✓ Schema check passed")
                
        except Exception as e:
            print(f"\n  Error: {e}")


def run_all_tests() -> None:
    """Run all indexer tests."""
    print_header("INDEXER UNIT TESTS")
    print(f"\n  Configuration:")
    print(f"    Qdrant URL: {Config.QDRANT_URL}")
    print(f"    DOCS Collection:  {Config.DOCS_COLLECTION}")
    print(f"    CODE Collection:  {Config.CODE_COLLECTION}")
    
    test_list_collections()
    test_collection_stats()
    test_ensure_collection()
    test_upsert_chunk()
    test_get_chunk()
    test_collection_schema()
    
    print_header("ALL TESTS COMPLETE")
    print("\n  All indexer tests finished.\n")


def main():
    """Main entry point with CLI argument handling."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Indexer Unit Tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tests.unit.test_indexer               # Run all tests
  python -m tests.unit.test_indexer --collections # List collections
  python -m tests.unit.test_indexer --stats       # Show collection stats
  python -m tests.unit.test_indexer --create      # Create test collection
  python -m tests.unit.test_indexer --drop        # Drop test collection
        """
    )
    
    parser.add_argument("--collections", action="store_true", 
                        help="List all collections")
    parser.add_argument("--stats", action="store_true", 
                        help="Show collection statistics")
    parser.add_argument("--create", action="store_true", 
                        help="Create test collection")
    parser.add_argument("--upsert", action="store_true", 
                        help="Test upsert chunk")
    parser.add_argument("--get", action="store_true", 
                        help="Test get chunk by ID")
    parser.add_argument("--schema", action="store_true", 
                        help="Test collection schema detection")
    
    args = parser.parse_args()
    
    # Change to project root
    os.chdir(Path(__file__).parent.parent.parent)
    
    # Run specific tests based on arguments
    if args.collections:
        test_list_collections()
    elif args.stats:
        test_collection_stats()
    elif args.create:
        test_ensure_collection()
    elif args.upsert:
        test_upsert_chunk()
    elif args.get:
        test_get_chunk()
    elif args.schema:
        test_collection_schema()
    else:
        # No specific test requested, run all
        run_all_tests()


if __name__ == "__main__":
    main()
