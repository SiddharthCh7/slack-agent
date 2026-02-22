#!/usr/bin/env python3
"""
RAG Unit Tests Runner

A unified test runner for all RAG component tests.

Usage:
    # Run all tests
    python -m tests.run_all
    
    # Run specific component tests
    python -m tests.run_all chunker
    python -m tests.run_all retriever
    python -m tests.run_all embedder
    python -m tests.run_all indexer
    python -m tests.run_all config
    
    # Run with specific test file
    python -m tests.run_all --file tests/unit/test_chunker.py --args "--stats"
    
    # List available tests
    python -m tests.run_all --list
"""

import sys
import os
import subprocess
from pathlib import Path
from typing import List, Optional


# Test modules mapping
TEST_MODULES = {
    "chunker": "tests.unit.test_chunker",
    "retriever": "tests.unit.test_retriever",
    "embedder": "tests.unit.test_embedder",
    "indexer": "tests.unit.test_indexer",
    "config": "tests.unit.test_config",
}


def print_header(title: str, char: str = "=") -> None:
    """Print a formatted header."""
    width = 70
    print("\n" + char * width)
    print(f"  {title}")
    print(char * width)


def print_section(title: str) -> None:
    """Print a formatted section title."""
    print(f"\n--- {title} ---")


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


def run_test_module(module_name: str, args: Optional[List[str]] = None) -> int:
    """Run a test module with optional arguments."""
    project_root = get_project_root()
    rag_path = project_root / "services" / "rag"
    
    cmd = [
        sys.executable,
        "-m",
        module_name,
    ]
    
    if args:
        cmd.extend(args)
    
    print_section(f"Running: {module_name}")
    print(f"  Command: {' '.join(cmd)}")
    print(f"  Directory: {project_root}")
    
    # Build environment with proper PYTHONPATH
    env = {
        **os.environ,
        "PYTHONPATH": f"{str(project_root)}:{str(rag_path)}",
    }
    
    result = subprocess.run(
        cmd,
        cwd=project_root,
        env=env,
    )
    
    return result.returncode


def list_tests() -> None:
    """List all available test modules."""
    print_header("AVAILABLE TESTS")
    
    print("\n  Component Tests:")
    for name, module in TEST_MODULES.items():
        print(f"\n    {name}:")
        print(f"      Module: {module}")
        print(f"      Run:    python -m tests.run_all {name}")
    
    print("\n  Examples:")
    print("    python -m tests.run_all                    # Run all tests")
    print("    python -m tests.run_all chunker            # Run chunker tests")
    print("    python -m tests.run_all chunker --stats    # Run with args")
    print("    python -m tests.run_all --list             # Show this help")


def run_all_tests() -> int:
    """Run all test modules."""
    print_header("RAG UNIT TESTS - FULL SUITE")
    
    project_root = get_project_root()
    print(f"\n  Project Root: {project_root}")
    print(f"  Python: {sys.executable}")
    print(f"  Python Version: {sys.version.split()[0]}")
    
    results = {}
    
    for name, module in TEST_MODULES.items():
        returncode = run_test_module(module)
        results[name] = returncode
    
    # Summary
    print_header("TEST SUMMARY")
    
    passed = sum(1 for rc in results.values() if rc == 0)
    failed = sum(1 for rc in results.values() if rc != 0)
    total = len(results)
    
    print(f"\n  Total:  {total}")
    print(f"  Passed: {passed} ✓")
    print(f"  Failed: {failed} ✗")
    
    if results:
        print("\n  Results by component:")
        for name, rc in results.items():
            status = "✓ PASS" if rc == 0 else "✗ FAIL"
            print(f"    {name:12} {status}")
    
    if failed == 0:
        print_header("ALL TESTS PASSED", char="✓")
        return 0
    else:
        print_header(f"{failed} TEST(S) FAILED", char="✗")
        return 1


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="RAG Unit Tests Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tests.run_all                     # Run all tests
  python -m tests.run_all chunker             # Run chunker tests
  python -m tests.run_all retriever config    # Run multiple components
  python -m tests.run_all --list              # List available tests
        """
    )
    
    parser.add_argument(
        "components",
        nargs="*",
        default=None,
        help="Test components to run: chunker, retriever, embedder, indexer, config (default: all)"
    )
    
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available tests"
    )
    
    parser.add_argument(
        "--file",
        type=str,
        help="Run specific test file"
    )
    
    parser.add_argument(
        "--args",
        type=str,
        nargs="*",
        help="Arguments to pass to test file"
    )
    
    args = parser.parse_args()
    
    # Change to project root
    os.chdir(get_project_root())
    sys.path.insert(0, str(get_project_root()))
    sys.path.insert(0, str(get_project_root() / "services" / "rag"))
    
    # Handle --list
    if args.list:
        list_tests()
        return 0
    
    # Handle --file
    if args.file:
        module = args.file.replace("/", ".").replace(".py", "")
        return run_test_module(module, args.args)
    
    # Validate components if provided
    if args.components:
        for comp in args.components:
            if comp not in TEST_MODULES:
                print(f"Error: Unknown component '{comp}'")
                print(f"Valid components: {', '.join(TEST_MODULES.keys())}")
                return 1
    
    # Run specified components or all
    if args.components is not None and len(args.components) > 0:
        results = []
        for component in args.components:
            module = TEST_MODULES[component]
            rc = run_test_module(module)
            results.append(rc)
        return 0 if all(r == 0 for r in results) else 1
    else:
        # No components specified, run all
        return run_all_tests()


if __name__ == "__main__":
    sys.exit(main())
