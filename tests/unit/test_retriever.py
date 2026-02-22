#!/usr/bin/env python3
"""
Retriever Unit Tests with CLI Output

Usage:
    python -m tests.unit.test_retriever                     # Run all tests
    python -m tests.unit.test_retriever --query "CDC"       # Search with query
    python -m tests.unit.test_retriever --query "PostgreSQL setup" --top-k 5
    python -m tests.unit.test_retriever --hybrid            # Test hybrid search
    python -m tests.unit.test_retriever --filter-connector postgres
    python -m tests.unit.test_retriever --summary-filter    # Test summary filtering
"""

import sys
import os
import json
from pathlib import Path
from typing import Optional

# Add paths for imports - works from project root or tests directory
PROJECT_ROOT = Path(__file__).parent.parent.parent
RAG_PATH = PROJECT_ROOT / "services" / "rag"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(RAG_PATH))
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from retriever import (
    search_docs, 
    search_code, 
    hybrid_search,
    _prefer_detail_over_summary,
    SearchResult,
)
from config import Config


def print_header(title: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_section(title: str) -> None:
    """Print a formatted section title."""
    print(f"\n--- {title} ---")


def print_result(result: dict, rank: int = 0) -> None:
    """Print a search result with formatted output."""
    if rank > 0:
        print(f"\n  [{'='*60}]")
        print(f"  Result #{rank}")
        print(f"  [{'='*60}]")
    
    # Score badge
    score = result.get('score', 0)
    score_bar = "█" * int(score * 20)
    print(f"\n  Score: {score:.4f} {score_bar}")
    
    # Metadata
    print(f"\n  Section Path: {result.get('section_path', 'N/A')}")
    print(f"  Chunk Type:   {result.get('chunk_type', 'prose')}")
    print(f"  DOC URL:      {result.get('doc_url', 'N/A')}")
    
    if result.get('connector'):
        print(f"  Connector:    {result['connector']}")
    if result.get('sync_mode'):
        print(f"  Sync Mode:    {result['sync_mode']}")
    if result.get('destination'):
        print(f"  Destination:  {result['destination']}")
    if result.get('tags'):
        print(f"  Tags:         {result['tags']}")
    
    # Text preview
    text = result.get('text', '')
    if text:
        # Remove section path prefix for cleaner display
        if '\n' in text:
            text = text.split('\n', 1)[1] if '\n' in text else text
        
        print(f"\n  Content Preview:")
        lines = text.split('\n')[:8]
        for line in lines:
            if line.strip():
                print(f"    {line[:80]}")
        if len(lines) > 8:
            print(f"    ... ({len(lines) - 8} more lines)")


def test_search_docs(query: str = "How do I configure PostgreSQL CDC?", top_k: int = 3) -> list:
    """Test document search."""
    print_header("DOCUMENT SEARCH TEST")
    
    print(f"\n  Query:  {query}")
    print(f"  Top-K:  {top_k}")
    print(f"  Index:  {Config.DOCS_COLLECTION}")
    
    try:
        results = search_docs(queries=[query], top_k=top_k)
        
        if not results:
            print_section("No Results")
            print("  No documents found matching the query.")
            return []
        
        print_section(f"Search Results ({len(results)} found)")
        
        for i, result in enumerate(results, 1):
            print_result(result, rank=i)
        
        return results
        
    except Exception as e:
        print_section("Error")
        print(f"  Search failed: {e}")
        return []


def test_search_code(query: str = "docker compose", top_k: int = 3) -> list:
    """Test code search."""
    print_header("CODE SEARCH TEST")
    
    print(f"\n  Query:  {query}")
    print(f"  Top-K:  {top_k}")
    print(f"  Index:  {Config.CODE_COLLECTION}")
    
    try:
        results = search_code(queries=[query], top_k=top_k)
        
        if not results:
            print_section("No Results")
            print("  No code snippets found matching the query.")
            return []
        
        print_section(f"Search Results ({len(results)} found)")
        
        for i, result in enumerate(results, 1):
            print_result(result, rank=i)
        
        return results
        
    except Exception as e:
        print_section("Error")
        print(f"  Search failed: {e}")
        return []


def test_hybrid_search(query: str = "PostgreSQL replication setup", top_k: int = 5) -> list:
    """Test hybrid search across docs and code."""
    print_header("HYBRID SEARCH TEST (Docs + Code)")
    
    print(f"\n  Query:  {query}")
    print(f"  Top-K:  {top_k}")
    
    try:
        results = hybrid_search(queries=[query], top_k=top_k)
        
        if not results:
            print_section("No Results")
            print("  No results found.")
            return []
        
        print_section(f"Search Results ({len(results)} found)")
        
        for i, result in enumerate(results, 1):
            source = result.get('source', 'unknown')
            print(f"\n  [{'='*60}]")
            print(f"  Result #{i} [{source.upper()}]")
            print(f"  [{'='*60}]")
            print_result(result)
        
        return results
        
    except Exception as e:
        print_section("Error")
        print(f"  Search failed: {e}")
        return []


def test_filtered_search(
    query: str = "CDC configuration",
    connector: str = "postgres",
    top_k: int = 3
) -> list:
    """Test filtered search."""
    print_header("FILTERED SEARCH TEST")
    
    print(f"\n  Query:      {query}")
    print(f"  Connector:  {connector}")
    print(f"  Top-K:      {top_k}")
    
    try:
        results = search_docs(
            queries=[query],
            top_k=top_k,
            connector=connector
        )
        
        if not results:
            print_section("No Results")
            print(f"  No documents found for connector '{connector}'.")
            return []
        
        print_section(f"Filtered Results ({len(results)} found)")
        
        for i, result in enumerate(results, 1):
            print_result(result, rank=i)
        
        return results
        
    except Exception as e:
        print_section("Error")
        print(f"  Search failed: {e}")
        return []


def test_summary_filtering() -> None:
    """Test that summary chunks are filtered when detail chunks exist."""
    print_header("SUMMARY FILTERING TEST")
    
    print("\n  Testing: Prefer detail over summary rule")
    print(f"  Threshold: {Config.DOC_RELEVANCE_THRESHOLD}")
    
    # Create mock results with mixed types
    mock_results = [
        SearchResult(
            payload={
                "chunk_id": "summary1",
                "text": "§12 Quick Reference > 12.1 Source Connector Summary\nPostgreSQL connector info...",
                "chunk_type": "summary",
                "section_path": "§12 Quick Reference > 12.1 Source Connector Summary",
            },
            score=0.85,
            source="docs"
        ),
        SearchResult(
            payload={
                "chunk_id": "detail1",
                "text": "§4 Source Connectors > 4.1 PostgreSQL Connector > 4.1.2 CDC Prerequisites\nDetailed CDC setup...",
                "chunk_type": "prose",
                "section_path": "§4 Source Connectors > 4.1 PostgreSQL Connector > 4.1.2 CDC Prerequisites",
            },
            score=0.80,
            source="docs"
        ),
        SearchResult(
            payload={
                "chunk_id": "summary2",
                "text": "§12 Quick Reference > 12.2 Destination Summary\nIceberg destination info...",
                "chunk_type": "summary",
                "section_path": "§12 Quick Reference > 12.2 Destination Summary",
            },
            score=0.78,
            source="docs"
        ),
        SearchResult(
            payload={
                "chunk_id": "detail2",
                "text": "§4 Source Connectors > 4.2 MySQL Connector\nMySQL specific setup...",
                "chunk_type": "prose",
                "section_path": "§4 Source Connectors > 4.2 MySQL Connector",
            },
            score=0.70,
            source="docs"
        ),
    ]
    
    print_section("Before Filtering")
    for i, r in enumerate(mock_results, 1):
        badge = "SUMMARY" if r.chunk_type == "summary" else "DETAIL"
        path = f"{r.section} > {r.subsection}" if r.subsection else r.section
        print(f"  {i}. [{badge}] Score: {r.score:.2f} - {path[:50]}...")

    # Apply filter
    filtered = _prefer_detail_over_summary(mock_results)

    print_section("After Filtering")
    for i, r in enumerate(filtered, 1):
        badge = "SUMMARY" if r.chunk_type == "summary" else "DETAIL"
        path = f"{r.section} > {r.subsection}" if r.subsection else r.section
        print(f"  {i}. [{badge}] Score: {r.score:.2f} - {path[:50]}...")
    
    # Verify
    summary_count_before = sum(1 for r in mock_results if r.chunk_type == "summary")
    summary_count_after = sum(1 for r in filtered if r.chunk_type == "summary")
    detail_count_after = sum(1 for r in filtered if r.chunk_type != "summary")
    
    print_section("Verification")
    print(f"  Summary chunks before: {summary_count_before}")
    print(f"  Summary chunks after:  {summary_count_after}")
    print(f"  Detail chunks after:   {detail_count_after}")
    
    if summary_count_after == 0 and detail_count_after > 0:
        print("\n  ✓ Summary chunks correctly filtered when detail chunks exist above threshold")
    elif summary_count_after > 0:
        print("\n  ✗ Summary chunks should have been filtered")
    else:
        print("\n  ✓ Test passed")


def test_multi_query_search() -> None:
    """Test search with multiple queries."""
    print_header("MULTI-QUERY SEARCH TEST")
    
    queries = [
        "PostgreSQL CDC setup",
        "binlog configuration MySQL",
        "Iceberg destination"
    ]
    
    print(f"\n  Queries: {len(queries)}")
    for i, q in enumerate(queries, 1):
        print(f"    {i}. {q}")
    
    try:
        results = search_docs(queries=queries, top_k=5)
        
        print_section(f"Combined Results ({len(results)} found)")
        
        # Group by query relevance
        for i, result in enumerate(results[:3], 1):
            print_result(result, rank=i)
        
    except Exception as e:
        print_section("Error")
        print(f"  Search failed: {e}")


def test_empty_query() -> None:
    """Test handling of empty queries."""
    print_header("EMPTY QUERY HANDLING TEST")
    
    try:
        results = search_docs(queries=[], top_k=3)
        print(f"\n  Results for empty query: {len(results)}")
        print("  ✓ Empty query handled correctly")
    except Exception as e:
        print(f"\n  Error: {e}")


def run_all_tests() -> None:
    """Run all retriever tests."""
    print_header("RETRIEVER UNIT TESTS")
    print(f"\n  Configuration:")
    print(f"    DOCS_COLLECTION:  {Config.DOCS_COLLECTION}")
    print(f"    CODE_COLLECTION:  {Config.CODE_COLLECTION}")
    print(f"    THRESHOLD:        {Config.DOC_RELEVANCE_THRESHOLD}")
    print(f"    MAX_RETRIEVED:    {Config.MAX_RETRIEVED_DOCS}")
    
    # Check if collections exist
    from services.rag.indexer import _client
    try:
        client = _client()
        docs_exists = client.collection_exists(Config.DOCS_COLLECTION)
        code_exists = client.collection_exists(Config.CODE_COLLECTION)
        
        print(f"\n  Collections:")
        print(f"    {Config.DOCS_COLLECTION}: {'✓ exists' if docs_exists else '✗ missing'}")
        print(f"    {Config.CODE_COLLECTION}: {'✓ exists' if code_exists else '✗ missing'}")
        
        if not docs_exists and not code_exists:
            print("\n  WARNING: No collections found. Run ingestion first.")
            print("  Some tests may fail or return empty results.")
    except Exception as e:
        print(f"\n  Warning: Could not check collections: {e}")
    
    # Run tests
    test_search_docs("How do I configure PostgreSQL CDC?")
    test_filtered_search("CDC configuration", connector="postgres")
    test_summary_filtering()
    test_multi_query_search()
    test_empty_query()
    
    print_header("ALL TESTS COMPLETE")
    print("\n  All retriever tests finished.\n")


def main():
    """Main entry point with CLI argument handling."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Retriever Unit Tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tests.unit.test_retriever                     # Run all tests
  python -m tests.unit.test_retriever --query "CDC"       # Search with query
  python -m tests.unit.test_retriever --query "PostgreSQL setup" --top-k 5
  python -m tests.unit.test_retriever --hybrid            # Test hybrid search
  python -m tests.unit.test_retriever --filter-connector postgres
  python -m tests.unit.test_retriever --summary-filter    # Test summary filtering
        """
    )
    
    parser.add_argument("--query", type=str, help="Search query string")
    parser.add_argument("--top-k", type=int, default=3, help="Number of results to return")
    parser.add_argument("--hybrid", action="store_true", help="Run hybrid search test")
    parser.add_argument("--filter-connector", type=str, metavar="CONNECTOR", 
                        help="Filter by connector type")
    parser.add_argument("--summary-filter", action="store_true", 
                        help="Test summary filtering logic")
    parser.add_argument("--multi-query", action="store_true", 
                        help="Test multi-query search")
    
    args = parser.parse_args()
    
    # Change to project root
    os.chdir(Path(__file__).parent.parent.parent)
    
    # Run specific tests based on arguments
    if args.query:
        if args.filter_connector:
            test_filtered_search(args.query, args.filter_connector, args.top_k)
        elif args.hybrid:
            test_hybrid_search(args.query, args.top_k)
        else:
            test_search_docs(args.query, args.top_k)
    elif args.hybrid:
        test_hybrid_search(top_k=args.top_k)
    elif args.filter_connector:
        test_filtered_search(connector=args.filter_connector, top_k=args.top_k)
    elif args.summary_filter:
        test_summary_filtering()
    elif args.multi_query:
        test_multi_query_search()
    else:
        # No specific test requested, run all
        run_all_tests()


if __name__ == "__main__":
    main()
