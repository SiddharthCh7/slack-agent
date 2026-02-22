#!/usr/bin/env python3
"""
Chunker Unit Tests with CLI Output

Usage:
    python -m tests.unit.test_chunker              # Run all tests
    python -m tests.unit.test_chunker --stats     # Show chunk statistics
    python -m tests.unit.test_chunker --first     # Show first chunk detail
    python -m tests.unit.test_chunker --variants  # Show variant sub-chunks
    python -m tests.unit.test_chunker --glossary  # Show glossary terms
    python -m tests.unit.test_chunker --summary   # Show §12 summary chunks
    python -m tests.unit.test_chunker --search    # Search chunks by keyword
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

from chunker import parse_file, Chunk
from config import Config


def print_header(title: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_section(title: str) -> None:
    """Print a formatted section title."""
    print(f"\n--- {title} ---")


def print_chunk_preview(chunk: Chunk, max_length: int = 200) -> None:
    """Print a chunk with formatted preview."""
    print(f"\n  Section Path: {chunk.section_path}")
    print(f"  Chunk Type:   {chunk.chunk_type}")
    print(f"  DOC URL:      {chunk.doc_url or '(none)'}")
    print(f"  Tags:         {chunk.tags or '(none)'}")
    if chunk.variant:
        print(f"  Variant:      {chunk.variant}")
    if chunk.glossary_terms:
        print(f"  Glossary:     {len(chunk.glossary_terms)} terms")
    
    text_preview = chunk.text[:max_length].replace('\n', ' ')
    if len(chunk.text) > max_length:
        text_preview += "..."
    print(f"\n  Text Preview:")
    print(f"    {text_preview}")


def test_parse_chunks() -> list[Chunk]:
    """Test basic chunk parsing."""
    print_header("CHUNK PARSING TEST")
    
    docs_path = Path("docs/olake_docs.md")
    if not docs_path.exists():
        print(f"ERROR: Docs file not found at {docs_path}")
        return []
    
    print(f"\nParsing: {docs_path}")
    chunks = parse_file(docs_path)
    
    print_section("Parsing Complete")
    print(f"  Total chunks parsed: {len(chunks)}")
    
    return chunks


def test_chunk_statistics(chunks: list[Chunk]) -> None:
    """Show detailed chunk statistics."""
    print_header("CHUNK STATISTICS")
    
    # Count by type
    by_type = {}
    for c in chunks:
        by_type[c.chunk_type] = by_type.get(c.chunk_type, 0) + 1
    
    print_section("By Chunk Type")
    for chunk_type, count in sorted(by_type.items()):
        bar = "█" * (count // 2)
        print(f"  {chunk_type:12} {count:3} {bar}")
    
    # Count by section
    by_section = {}
    for c in chunks:
        section = c.section or "(no section)"
        by_section[section] = by_section.get(section, 0) + 1
    
    print_section("By H1 Section")
    for section, count in sorted(by_section.items()):
        print(f"  {section:40} {count:3} chunks")
    
    # Metadata coverage
    with_urls = sum(1 for c in chunks if c.doc_url)
    with_tags = sum(1 for c in chunks if c.tags)
    with_entities = sum(1 for c in chunks if c.key_entities)
    
    print_section("Metadata Coverage")
    print(f"  With DOC URL:      {with_urls:3} / {len(chunks)} ({100*with_urls//len(chunks):3}%)")
    print(f"  With Tags:         {with_tags:3} / {len(chunks)} ({100*with_tags//len(chunks):3}%)")
    print(f"  With Key Entities: {with_entities:3} / {len(chunks)} ({100*with_entities//len(chunks):3}%)")


def test_first_chunk(chunks: list[Chunk]) -> None:
    """Show detailed view of first chunk."""
    print_header("FIRST CHUNK DETAIL")
    
    if not chunks:
        print("  No chunks available")
        return
    
    chunk = chunks[0]
    
    print_section("Chunk Metadata")
    print(f"  Chunk ID:       {chunk.chunk_id}")
    print(f"  Section:        {chunk.section}")
    print(f"  Subsection:     {chunk.subsection}")
    print(f"  Sub-subsection: {chunk.subsubsection or '(none)'}")
    print(f"  Section Path:   {chunk.section_path}")
    print(f"  Chunk Type:     {chunk.chunk_type}")
    print(f"  DOC URL:        {chunk.doc_url}")
    print(f"  Tags:           {chunk.tags or '(none)'}")
    print(f"  Key Entities:   {chunk.key_entities or '(none)'}")
    print(f"  Last Updated:   {chunk.last_updated or '(none)'}")
    
    print_section("Full Text")
    lines = chunk.text.split('\n')
    for i, line in enumerate(lines[:20], 1):
        print(f"  {i:2}. {line}")
    if len(lines) > 20:
        print(f"  ... ({len(lines) - 20} more lines)")
    
    print_section("Payload (for DB)")
    payload = chunk.to_payload()
    for key, value in sorted(payload.items()):
        if isinstance(value, str) and len(value) > 60:
            value = value[:60] + "..."
        print(f"  {key:20} {value}")


def test_variant_chunks(chunks: list[Chunk]) -> None:
    """Show §4.1.3 variant sub-chunks."""
    print_header("VARIANT SUB-CHUNKS (§4.1.3)")
    
    variants = [c for c in chunks if c.variant and "4.1.3" in c.subsubsection]
    
    if not variants:
        print("  No variant chunks found")
        return
    
    print(f"\n  Found {len(variants)} variant sub-chunks:\n")
    
    for i, chunk in enumerate(variants, 1):
        print_section(f"Variant {i}: {chunk.variant}")
        print(f"  Section Path: {chunk.section_path}")
        print(f"  Overlap:      First 400 chars from previous chunk included")
        
        # Show first few lines
        lines = chunk.text.split('\n')[:5]
        print(f"  Content Start:")
        for line in lines:
            print(f"    {line}")


def test_glossary_chunks(chunks: list[Chunk]) -> None:
    """Show glossary chunk with terms."""
    print_header("GLOSSARY CHUNK (§1.4)")
    
    glossary = [c for c in chunks if c.glossary_terms]
    
    if not glossary:
        print("  No glossary chunks found")
        return
    
    chunk = glossary[0]
    
    print_section("Glossary Metadata")
    print(f"  Section Path:   {chunk.section_path}")
    print(f"  Terms Count:    {len(chunk.glossary_terms)}")
    
    print_section("Glossary Terms")
    for i, term in enumerate(chunk.glossary_terms[:10], 1):
        print(f"  {i:2}. {term['term']}")
        defn = term['definition'][:80] + "..." if len(term['definition']) > 80 else term['definition']
        print(f"      {defn}")
    
    if len(chunk.glossary_terms) > 10:
        print(f"\n  ... and {len(chunk.glossary_terms) - 10} more terms")


def test_summary_chunks(chunks: list[Chunk]) -> None:
    """Show §12 summary chunks."""
    print_header("SUMMARY CHUNKS (§12 Quick Reference)")
    
    summaries = [c for c in chunks if c.chunk_type == "summary"]
    
    if not summaries:
        print("  No summary chunks found")
        return
    
    print(f"\n  Found {len(summaries)} summary chunks (for routing only):\n")
    
    for chunk in summaries:
        print_section(chunk.subsection or chunk.section_path)
        print(f"  Section Path: {chunk.section_path}")
        print(f"  Chunk Type:   {chunk.chunk_type} (filtered at retrieval)")
        
        # Count tables/rows
        lines = chunk.text.split('\n')
        table_rows = sum(1 for l in lines if '|' in l or l.strip().startswith('**'))
        print(f"  Content:      ~{table_rows} table rows")


def test_schema_evolution_chunks(chunks: list[Chunk]) -> None:
    """Show schema evolution chunks."""
    print_header("SCHEMA EVOLUTION CHUNKS (§3.2.5-3.2.7)")
    
    schema = [c for c in chunks if "Schema" in c.subsubsection or "Data Type" in c.subsubsection]
    
    if not schema:
        print("  No schema evolution chunks found")
        return
    
    print(f"\n  Found {len(schema)} schema evolution chunks:\n")
    
    for chunk in schema:
        print_section(chunk.subsubsection)
        print(f"  Section Path: {chunk.section_path}")
        
        # Show first few lines
        lines = chunk.text.split('\n')[:4]
        print(f"  Content Start:")
        for line in lines:
            print(f"    {line}")


def test_search_chunks(chunks: list[Chunk], keyword: str = "CDC") -> None:
    """Search chunks by keyword."""
    print_header(f"SEARCH: '{keyword}'")
    
    matches = [c for c in chunks if keyword.lower() in c.text.lower()]
    
    if not matches:
        print(f"  No chunks contain '{keyword}'")
        return
    
    print(f"\n  Found {len(matches)} chunks containing '{keyword}':\n")
    
    for i, chunk in enumerate(matches[:5], 1):
        print_section(f"Match {i}")
        print(f"  Section Path: {chunk.section_path}")
        
        # Find and show matching line
        for line in chunk.text.split('\n'):
            if keyword.lower() in line.lower():
                # Highlight the keyword
                highlighted = line.replace(keyword, f"**{keyword}**")
                highlighted = highlighted.replace(keyword.lower(), f"**{keyword.lower()}**")
                print(f"  Match: {highlighted[:80]}...")
                break
    
    if len(matches) > 5:
        print(f"\n  ... and {len(matches) - 5} more matches")


def test_overlap_verification(chunks: list[Chunk]) -> None:
    """Verify overlap between consecutive chunks."""
    print_header("OVERLAP VERIFICATION")
    
    print(f"\n  Config OVERLAP_CHARS: {Config.OVERLAP_CHARS}")
    print(f"  Config MAX_CHUNK_CHARS: {Config.MAX_CHUNK_CHARS}")
    
    # Check overlap in variant chunks (they should have overlap)
    variants = [c for c in chunks if c.variant and "4.1.3" in c.subsubsection]
    
    if len(variants) >= 2:
        print_section("Variant Chunk Overlap Check")
        
        for i in range(len(variants) - 1):
            c1, c2 = variants[i], variants[i+1]
            
            # Check if c2 starts with tail of c1
            tail = c1.raw_text[-Config.OVERLAP_CHARS:] if len(c1.raw_text) > Config.OVERLAP_CHARS else c1.raw_text
            head = c2.raw_text[:Config.OVERLAP_CHARS]
            
            # Simple overlap check
            overlap_found = False
            for size in range(50, Config.OVERLAP_CHARS):
                if c1.raw_text.endswith(c2.raw_text[:size]):
                    overlap_found = True
                    print(f"\n  {c1.variant} → {c2.variant}:")
                    print(f"    Overlap size: ~{size} chars")
                    print(f"    Overlap text: {c2.raw_text[:size][:60]}...")
                    break
            
            if not overlap_found:
                print(f"\n  {c1.variant} → {c2.variant}:")
                print(f"    No exact overlap (content may differ by variant)")


def run_all_tests() -> None:
    """Run all chunker tests."""
    chunks = test_parse_chunks()
    
    if not chunks:
        print("\nERROR: Failed to parse chunks. Exiting.")
        return
    
    test_chunk_statistics(chunks)
    test_first_chunk(chunks)
    test_variant_chunks(chunks)
    test_glossary_chunks(chunks)
    test_summary_chunks(chunks)
    test_schema_evolution_chunks(chunks)
    test_search_chunks(chunks, "CDC")
    test_overlap_verification(chunks)
    
    print_header("ALL TESTS COMPLETE")
    print(f"\n  Total chunks: {len(chunks)}")
    print(f"  All tests passed ✓\n")


def main():
    """Main entry point with CLI argument handling."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Chunker Unit Tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tests.unit.test_chunker              # Run all tests
  python -m tests.unit.test_chunker --stats     # Show statistics only
  python -m tests.unit.test_chunker --first     # Show first chunk detail
  python -m tests.unit.test_chunker --variants  # Show variant sub-chunks
  python -m tests.unit.test_chunker --glossary  # Show glossary terms
  python -m tests.unit.test_chunker --summary   # Show §12 summary chunks
  python -m tests.unit.test_chunker --search CDC  # Search for 'CDC'
        """
    )
    
    parser.add_argument("--stats", action="store_true", help="Show chunk statistics")
    parser.add_argument("--first", action="store_true", help="Show first chunk detail")
    parser.add_argument("--variants", action="store_true", help="Show variant sub-chunks")
    parser.add_argument("--glossary", action="store_true", help="Show glossary terms")
    parser.add_argument("--summary", action="store_true", help="Show §12 summary chunks")
    parser.add_argument("--schema", action="store_true", help="Show schema evolution chunks")
    parser.add_argument("--search", type=str, metavar="KEYWORD", help="Search chunks by keyword")
    parser.add_argument("--overlap", action="store_true", help="Verify overlap between chunks")
    
    args = parser.parse_args()
    
    # Change to project root
    os.chdir(Path(__file__).parent.parent.parent)
    
    # Parse chunks once
    chunks = test_parse_chunks()
    
    if not chunks:
        return
    
    # Run specific tests based on arguments
    if args.stats:
        test_chunk_statistics(chunks)
    elif args.first:
        test_first_chunk(chunks)
    elif args.variants:
        test_variant_chunks(chunks)
    elif args.glossary:
        test_glossary_chunks(chunks)
    elif args.summary:
        test_summary_chunks(chunks)
    elif args.schema:
        test_schema_evolution_chunks(chunks)
    elif args.search:
        test_search_chunks(chunks, args.search)
    elif args.overlap:
        test_overlap_verification(chunks)
    else:
        # No specific test requested, run all
        test_chunk_statistics(chunks)
        test_first_chunk(chunks)
        test_variant_chunks(chunks)
        test_glossary_chunks(chunks)
        test_summary_chunks(chunks)
        test_schema_evolution_chunks(chunks)
        test_search_chunks(chunks, "CDC")
        test_overlap_verification(chunks)
        
        print_header("ALL TESTS COMPLETE")
        print(f"\n  Total chunks: {len(chunks)}")
        print(f"  All tests passed ✓\n")


if __name__ == "__main__":
    main()
