#!/usr/bin/env python3
"""
Embedder Unit Tests with CLI Output

Usage:
    python -m tests.unit.test_embedder              # Run all tests
    python -m tests.unit.test_embedder --test-doc   # Test document embedding
    python -m tests.unit.test_embedder --test-query # Test query embedding
    python -m tests.unit.test_embedder --test-sparse # Test sparse embedding
    python -m tests.unit.test_embedder --batch      # Test batch embedding
    python -m tests.unit.test_embedder --similarity # Test similarity calculation
"""

import sys
import os
from pathlib import Path
from typing import List

# Add paths for imports - works from project root or tests directory
PROJECT_ROOT = Path(__file__).parent.parent.parent
RAG_PATH = PROJECT_ROOT / "services" / "rag"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(RAG_PATH))
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from embedder import embed_documents, embed_queries, vector_size, _get_model
from config import Config


def print_header(title: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_section(title: str) -> None:
    """Print a formatted section title."""
    print(f"\n--- {title} ---")


def print_vector_stats(vectors: List[List[float]], label: str = "Vectors") -> None:
    """Print statistics about vectors."""
    if not vectors:
        print(f"  {label}: Empty")
        return
    
    dims = [len(v) for v in vectors]
    magnitudes = [sum(x*x for x in v) ** 0.5 for v in vectors]
    
    print(f"\n  {label}:")
    print(f"    Count:      {len(vectors)}")
    print(f"    Dimensions: {dims[0]} (consistent: {len(set(dims)) == 1})")
    print(f"    Magnitude:  min={min(magnitudes):.4f}, max={max(magnitudes):.4f}, avg={sum(magnitudes)/len(magnitudes):.4f}")
    
    # Show first vector preview
    if vectors:
        first = vectors[0]
        preview = first[:10]
        print(f"    First vec:  [{', '.join(f'{x:.4f}' for x in preview)}...]")


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    dot = sum(a * b for a, b in zip(v1, v2))
    mag1 = sum(x * x for x in v1) ** 0.5
    mag2 = sum(x * x for x in v2) ** 0.5
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


def test_model_loading() -> None:
    """Test embedding model loading."""
    print_header("MODEL LOADING TEST")
    
    print_section("Loading Model")
    print(f"  Model: {Config.EMBED_MODEL}")
    print(f"  Device: {Config.EMBED_DEVICE}")
    print(f"  Batch Size: {Config.EMBED_BATCH_SIZE}")
    
    try:
        model = _get_model()
        print(f"\n  ✓ Model loaded successfully")
        print(f"\n  Model Architecture:")
        print(f"    {model}")
        
        # Check vector size
        vec_size = vector_size()
        print(f"\n  Vector Size: {vec_size} dimensions")
        
    except Exception as e:
        print(f"\n  ✗ Model loading failed: {e}")
        raise


def test_document_embedding() -> None:
    """Test document embedding."""
    print_header("DOCUMENT EMBEDDING TEST")
    
    test_docs = [
        "OLake is a blazing-fast, open-source ELT framework written in Golang.",
        "PostgreSQL CDC uses pgoutput for logical replication.",
        "Iceberg tables support ACID transactions and schema evolution.",
    ]
    
    print_section("Test Documents")
    for i, doc in enumerate(test_docs, 1):
        print(f"\n  {i}. {doc}")
    
    print_section("Embedding Documents")
    try:
        vectors = embed_documents(test_docs)
        
        print(f"\n  ✓ Embedded {len(vectors)} documents")
        print_vector_stats(vectors, "Document Vectors")
        
        # Verify all vectors have same dimension
        dims = set(len(v) for v in vectors)
        if len(dims) == 1:
            print(f"\n  ✓ All vectors have consistent dimensions ({dims.pop()})")
        else:
            print(f"\n  ✗ Inconsistent dimensions: {dims}")
        
        return vectors
        
    except Exception as e:
        print(f"\n  ✗ Embedding failed: {e}")
        return []


def test_query_embedding() -> None:
    """Test query embedding."""
    print_header("QUERY EMBEDDING TEST")
    
    test_queries = [
        "How do I set up PostgreSQL CDC?",
        "What is schema evolution?",
    ]
    
    print_section("Test Queries")
    for i, query in enumerate(test_queries, 1):
        print(f"\n  {i}. {query}")
    
    print_section("Embedding Queries")
    try:
        vectors = embed_queries(test_queries)
        
        print(f"\n  ✓ Embedded {len(vectors)} queries")
        print_vector_stats(vectors, "Query Vectors")
        
        return vectors
        
    except Exception as e:
        print(f"\n  ✗ Embedding failed: {e}")
        return []


def test_sparse_embedding() -> None:
    """Test sparse (BM25) embedding."""
    print_header("SPARSE EMBEDDING TEST (BM25)")
    
    from services.rag.retriever import embed_sparse_for_index, embed_sparse_query, sparse_is_ready
    
    print_section("Sparse Vector Status")
    ready = sparse_is_ready()
    print(f"  BM25 Ready: {ready}")
    
    if not ready:
        print("\n  Note: Sparse vectors disabled or fastembed not available")
        print("  This is optional - dense vectors will be used for retrieval")
        return
    
    test_docs = [
        "PostgreSQL wal_level must be set to logical for CDC.",
        "MySQL binlog_format should be ROW for OLake replication.",
    ]
    
    print_section("Test Documents")
    for i, doc in enumerate(test_docs, 1):
        print(f"\n  {i}. {doc}")
    
    print_section("Embedding Documents (Sparse)")
    try:
        sparse_vecs = embed_sparse_for_index(test_docs)
        
        print(f"\n  ✓ Embedded {len(sparse_vecs)} documents")
        
        for i, vec in enumerate(sparse_vecs, 1):
            if vec:
                print(f"\n  Document {i}:")
                print(f"    Indices: {len(vec.indices)}")
                print(f"    Values:  {len(vec.values)}")
                print(f"    Sparsity: {100 * (1 - len(vec.indices) / 10000):.2f}% (estimated)")
            else:
                print(f"\n  Document {i}: No sparse vector (fallback)")
        
    except Exception as e:
        print(f"\n  ✗ Sparse embedding failed: {e}")


def test_batch_embedding() -> None:
    """Test batch embedding performance."""
    print_header("BATCH EMBEDDING TEST")
    
    # Generate test documents
    num_docs = 20
    test_docs = [
        f"Document {i}: OLake supports {connector} for data replication with {mode} sync."
        for i in range(num_docs)
        for connector in ["PostgreSQL", "MySQL", "MongoDB", "Oracle", "Kafka"]
        for mode in ["CDC", "incremental", "full refresh"]
    ][:num_docs]
    
    print_section(f"Batch Test ({num_docs} documents)")
    print(f"  Batch size config: {Config.EMBED_BATCH_SIZE}")
    
    import time
    start = time.time()
    
    try:
        vectors = embed_documents(test_docs)
        elapsed = time.time() - start
        
        print(f"\n  ✓ Embedded {len(vectors)} documents in {elapsed:.2f}s")
        print(f"  Throughput: {num_docs / elapsed:.1f} docs/sec")
        
        print_vector_stats(vectors, "Batch Vectors")
        
    except Exception as e:
        print(f"\n  ✗ Batch embedding failed: {e}")


def test_similarity_calculation() -> None:
    """Test cosine similarity between embeddings."""
    print_header("SIMILARITY CALCULATION TEST")
    
    # Create semantically related and unrelated texts
    texts = {
        "postgres_cdc_1": "PostgreSQL CDC setup requires wal_level=logical and a replication slot.",
        "postgres_cdc_2": "To enable CDC in Postgres, set wal_level to logical and create a slot.",
        "mysql_binlog": "MySQL uses binlog with ROW format for change data capture.",
        "iceberg_info": "Apache Iceberg is an open table format for analytics workloads.",
    }
    
    print_section("Test Texts")
    for key, text in texts.items():
        print(f"\n  {key}:")
        print(f"    {text}")
    
    print_section("Computing Embeddings")
    try:
        keys = list(texts.keys())
        vectors = embed_documents(list(texts.values()))
        
        print(f"\n  ✓ Computed {len(vectors)} embeddings")
        
        # Calculate pairwise similarities
        print_section("Cosine Similarity Matrix")
        
        # Header
        header = " " * 20
        for key in keys:
            header += f" {key[:12]:>14}"
        print(f"\n  {header}")
        
        # Rows
        for i, key1 in enumerate(keys):
            row = f"  {key1:20}"
            for j, key2 in enumerate(keys):
                sim = cosine_similarity(vectors[i], vectors[j])
                if i == j:
                    row += f" {1.0:>14.4f}"
                else:
                    row += f" {sim:>14.4f}"
            print(row)
        
        # Analysis
        print_section("Analysis")
        
        # Similar pair (postgres_cdc_1 vs postgres_cdc_2)
        sim_cdc = cosine_similarity(vectors[0], vectors[1])
        print(f"\n  PostgreSQL CDC texts similarity: {sim_cdc:.4f}")
        if sim_cdc > 0.7:
            print(f"    ✓ High similarity expected (semantically similar)")
        else:
            print(f"    ⚠ Lower than expected similarity")
        
        # Dissimilar pair (postgres vs iceberg)
        sim_diff = cosine_similarity(vectors[0], vectors[3])
        print(f"\n  PostgreSQL vs Iceberg similarity: {sim_diff:.4f}")
        if sim_diff < 0.5:
            print(f"    ✓ Low similarity expected (different topics)")
        else:
            print(f"    ⚠ Higher than expected similarity")
        
    except Exception as e:
        print(f"\n  ✗ Similarity test failed: {e}")


def test_prefix_handling() -> None:
    """Test that document/query prefixes are applied correctly."""
    print_header("PREFIX HANDLING TEST")
    
    print("\n  Model: nomic-ai/nomic-embed-text-v1.5")
    print("  Document prefix: 'search_document: '")
    print("  Query prefix: 'search_query: '")
    
    text = "Test embedding with prefixes"
    
    try:
        doc_vec = embed_documents([text])[0]
        query_vec = embed_queries([text])[0]
        
        # They should be different due to different prefixes
        sim = cosine_similarity(doc_vec, query_vec)
        
        print_section("Results")
        print(f"\n  Document vector magnitude: {sum(x*x for x in doc_vec) ** 0.5:.4f}")
        print(f"  Query vector magnitude:    {sum(x*x for x in query_vec) ** 0.5:.4f}")
        print(f"  Similarity (same text):    {sim:.4f}")
        
        if sim < 0.99:
            print(f"\n  ✓ Prefixes create distinct embeddings (as expected)")
        else:
            print(f"\n  ⚠ Embeddings nearly identical - prefixes may not be applied")
        
    except Exception as e:
        print(f"\n  ✗ Prefix test failed: {e}")


def run_all_tests() -> None:
    """Run all embedder tests."""
    print_header("EMBEDDER UNIT TESTS")
    print(f"\n  Configuration:")
    print(f"    Model:      {Config.EMBED_MODEL}")
    print(f"    Device:     {Config.EMBED_DEVICE}")
    print(f"    Batch Size: {Config.EMBED_BATCH_SIZE}")
    
    test_model_loading()
    test_document_embedding()
    test_query_embedding()
    test_sparse_embedding()
    test_batch_embedding()
    test_similarity_calculation()
    test_prefix_handling()
    
    print_header("ALL TESTS COMPLETE")
    print("\n  All embedder tests finished.\n")


def main():
    """Main entry point with CLI argument handling."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Embedder Unit Tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tests.unit.test_embedder              # Run all tests
  python -m tests.unit.test_embedder --test-doc   # Test document embedding
  python -m tests.unit.test_embedder --test-query # Test query embedding
  python -m tests.unit.test_embedder --test-sparse # Test sparse embedding
  python -m tests.unit.test_embedder --batch      # Test batch embedding
  python -m tests.unit.test_embedder --similarity # Test similarity calculation
        """
    )
    
    parser.add_argument("--test-doc", action="store_true", 
                        help="Test document embedding")
    parser.add_argument("--test-query", action="store_true", 
                        help="Test query embedding")
    parser.add_argument("--test-sparse", action="store_true", 
                        help="Test sparse (BM25) embedding")
    parser.add_argument("--batch", action="store_true", 
                        help="Test batch embedding")
    parser.add_argument("--similarity", action="store_true", 
                        help="Test similarity calculation")
    parser.add_argument("--prefix", action="store_true", 
                        help="Test prefix handling")
    
    args = parser.parse_args()
    
    # Change to project root
    os.chdir(Path(__file__).parent.parent.parent)
    
    # Run specific tests based on arguments
    if args.test_doc:
        test_document_embedding()
    elif args.test_query:
        test_query_embedding()
    elif args.test_sparse:
        test_sparse_embedding()
    elif args.batch:
        test_batch_embedding()
    elif args.similarity:
        test_similarity_calculation()
    elif args.prefix:
        test_prefix_handling()
    else:
        # No specific test requested, run all
        run_all_tests()


if __name__ == "__main__":
    main()
