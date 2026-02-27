"""
CLI interface for the code documentation system.

Provides commands for:
- Manual sync operations
- Search and retrieval
- Cache management
- Status and health checks
- Configuration validation

Usage Examples:
    # Start with detailed logging
    uv run python -m services.codeparse.cli start --verbose

    # Sync a specific codebase
    uv run python -m services.codeparse.cli sync --codebase myproject --verbose

    # Search with pretty output
    uv run python -m services.codeparse.cli search "authentication" --codebase myproject
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from .config import Config
from .utils import setup_logging, setup_detailed_logging, check_qdrant_health, check_github_connectivity, check_cache_health
from .cache import CodeParseCache

app = typer.Typer(
    name="codeparse",
    help="Incremental Code Documentation System CLI",
    add_completion=False,
)

console = Console()


# =============================================================================
# Sync Commands
# =============================================================================

@app.command("sync")
def sync_codebase(
    config_path: Optional[Path] = typer.Option(
        None,
        "--config", "-c",
        help="Path to sync_config.yaml",
    ),
    codebase: Optional[str] = typer.Option(
        None,
        "--codebase", "-b",
        help="Specific codebase to sync (name from config)",
    ),
    all_codebases: bool = typer.Option(
        False,
        "--all", "-a",
        help="Sync all enabled codebases",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Enable verbose output",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable debug logging (most detailed)",
    ),
    fresh: bool = typer.Option(
        False,
        "--fresh", "-f",
        help="Force fresh clone (clear existing data first)",
    ),
):
    """
    Sync code from GitHub repositories to Qdrant.

    Performs incremental sync, processing only changed files.
    For new repos: clones with git clone --depth 1 (efficient)
    For existing repos: uses GitHub API for incremental updates
    """
    # Setup logging
    if debug:
        setup_detailed_logging(level="DEBUG")
    else:
        setup_logging(level="DEBUG" if verbose else "INFO", verbose=not verbose)
    
    try:
        config = Config.load(config_path)
    except Exception as e:
        console.print(f"[red]Error loading config: {e}[/red]")
        raise typer.Exit(1)

    # Import here to avoid circular imports
    from agent.embedding import embed_texts, embed_query

    from .sync import CodeSyncEngine
    from .git_clone_sync import GitCloneSync
    
    if fresh:
        # Use git clone-based sync (efficient for initial sync)
        console.print("[blue]Using git clone for efficient initial sync[/blue]")
        
        with CodeSyncEngine(config, embed_texts) as engine:
            git_sync = GitCloneSync(
                cache=engine.cache,
                qdrant=engine.qdrant,
                parser=engine.parser,
                embed_fn=embed_texts,
                config=config,
            )
            
            if codebase:
                cb_config = config.get_codebase_by_name(codebase)
                if not cb_config:
                    console.print(f"[red]Codebase not found: {codebase}[/red]")
                    raise typer.Exit(1)

                console.print(f"[blue]Fresh sync: {codebase}[/blue]")
                
                # Clear existing data if requested
                if fresh:
                    console.print("[yellow]Clearing existing data...[/yellow]")
                    git_sync.clear_codebase_data(cb_config)
                
                result = git_sync.sync_codebase(cb_config)
                
                console.print(Panel(
                    f"[green]Fresh Sync Complete[/green]\n\n"
                    f"Files processed: {result.files_processed}\n"
                    f"Files skipped: {result.files_skipped}\n"
                    f"Symbols: {result.symbols_count}\n"
                    f"Vectors upserted: {result.vectors_upserted}\n"
                    f"Errors: {result.errors}",
                    title="Fresh Sync Results",
                    box=box.ROUNDED,
                ))
                
            elif all_codebases:
                console.print("[blue]Fresh syncing all enabled codebases[/blue]")
                
                for cb_config in config.get_enabled_codebases():
                    console.print(f"\n[blue]Fresh syncing: {cb_config.name}[/blue]")
                    
                    # Clear existing data
                    git_sync.clear_codebase_data(cb_config)
                    
                    result = git_sync.sync_codebase(cb_config)
                    
                    if result.errors == 0:
                        console.print(
                            f"[green]✓ {result.files_processed} files, "
                            f"{result.symbols_count} symbols[/green]"
                        )
                    else:
                        console.print(f"[red]✗ {result.errors} errors[/red]")
            else:
                console.print("[yellow]Specify --codebase NAME or --all[/yellow]")
                raise typer.Exit(1)
    
    else:
        # Use standard API-based sync
        with CodeSyncEngine(config, embed_texts) as engine:
            if codebase:
                # Sync specific codebase
                cb_config = config.get_codebase_by_name(codebase)
                if not cb_config:
                    console.print(f"[red]Codebase not found: {codebase}[/red]")
                    raise typer.Exit(1)

                console.print(f"[blue]Syncing codebase: {codebase}[/blue]")
                result = engine.sync_codebase(cb_config)

            elif all_codebases:
                # Sync all enabled codebases
                console.print("[blue]Syncing all enabled codebases[/blue]")

                for cb_config in config.get_enabled_codebases():
                    console.print(f"\n[blue]Syncing: {cb_config.name}[/blue]")
                    result = engine.sync_codebase(cb_config)

                    if result.success:
                        console.print(
                            f"[green]✓ {result.stats.files_changed} files, "
                            f"{result.stats.vectors_upserted} vectors[/green]"
                        )
                    else:
                        console.print(f"[red]✗ {result.message}[/red]")
            else:
                console.print("[yellow]Specify --codebase NAME or --all[/yellow]")
                raise typer.Exit(1)

            if result.success:
                console.print(Panel(
                    f"[green]Sync Complete[/green]\n\n"
                    f"Files checked: {result.stats.files_checked}\n"
                    f"Files changed: {result.stats.files_changed}\n"
                    f"Symbols new: {result.stats.symbols_new}\n"
                    f"Symbols updated: {result.stats.symbols_updated}\n"
                    f"Symbols reused: {result.stats.symbols_reused}\n"
                    f"Symbols deleted: {result.stats.symbols_deleted}\n"
                    f"Vectors upserted: {result.stats.vectors_upserted}\n"
                    f"Vectors deleted: {result.stats.vectors_deleted}\n"
                    f"Duration: {result.stats.duration_seconds:.2f}s",
                    title="Sync Results",
                    box=box.ROUNDED,
                ))
            else:
                console.print(f"[red]Sync failed: {result.message}[/red]")
                raise typer.Exit(1)


@app.command("fresh-sync")
def fresh_sync(
    config_path: Optional[Path] = typer.Option(
        None,
        "--config", "-c",
        help="Path to sync_config.yaml",
    ),
    codebase: Optional[str] = typer.Option(
        None,
        "--codebase", "-b",
        help="Specific codebase to fresh sync",
    ),
    all_codebases: bool = typer.Option(
        False,
        "--all", "-a",
        help="Fresh sync all enabled codebases",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Enable verbose output",
    ),
):
    """
    Fresh sync using git clone (efficient for initial sync).
    
    Clears all existing data and clones the repository fresh.
    Uses git clone --depth 1 for speed and efficiency.
    Automatically deletes cloned repo after processing.
    
    Perfect for:
    - Initial sync of large repositories
    - Resetting corrupted data
    - Avoiding GitHub API rate limits
    """
    setup_logging(level="DEBUG" if verbose else "INFO", verbose=not verbose)
    
    try:
        config = Config.load(config_path)
    except Exception as e:
        console.print(f"[red]Error loading config: {e}[/red]")
        raise typer.Exit(1)

    from agent.embedding import embed_texts
    from .sync import CodeSyncEngine
    from .git_clone_sync import GitCloneSync
    
    console.print("[blue]Starting fresh sync (git clone method)[/blue]")

    with CodeSyncEngine(config, embed_texts) as engine:
        git_sync = GitCloneSync(
            cache=engine.cache,
            qdrant=engine.qdrant,
            parser=engine.parser,
            embed_fn=embed_texts,
            config=config,
        )

        if codebase:
            cb_config = config.get_codebase_by_name(codebase)
            if not cb_config:
                console.print(f"[red]Codebase not found: {codebase}[/red]")
                raise typer.Exit(1)

            console.print(f"[blue]Fresh syncing: {codebase}[/blue]")
            console.print("[yellow]Clearing existing data...[/yellow]")
            git_sync.clear_codebase_data(cb_config)
            
            result = git_sync.sync_codebase(cb_config)
            
            console.print(Panel(
                f"[green]Fresh Sync Complete[/green]\n\n"
                f"Files processed: {result.files_processed}\n"
                f"Files skipped: {result.files_skipped}\n"
                f"Symbols: {result.symbols_count}\n"
                f"Vectors upserted: {result.vectors_upserted}\n"
                f"Errors: {result.errors}",
                title="Fresh Sync Results",
                box=box.ROUNDED,
            ))
            
        elif all_codebases:
            console.print("[blue]Fresh syncing all enabled codebases[/blue]")
            
            total_files = 0
            total_symbols = 0
            total_errors = 0
            
            for cb_config in config.get_enabled_codebases():
                console.print(f"\n[blue]Fresh syncing: {cb_config.name}[/blue]")
                
                # Clear existing data
                git_sync.clear_codebase_data(cb_config)
                
                result = git_sync.sync_codebase(cb_config)
                
                total_files += result.files_processed
                total_symbols += result.symbols_count
                total_errors += result.errors
                
                if result.errors == 0:
                    console.print(
                        f"[green]✓ {result.files_processed} files, "
                        f"{result.symbols_count} symbols[/green]"
                    )
                else:
                    console.print(f"[red]✗ {result.errors} errors[/red]")
            
            console.print(Panel(
                f"[green]All Fresh Syncs Complete[/green]\n\n"
                f"Total files: {total_files}\n"
                f"Total symbols: {total_symbols}\n"
                f"Total errors: {total_errors}",
                title="Summary",
                box=box.ROUNDED,
            ))
        else:
            console.print("[yellow]Specify --codebase NAME or --all[/yellow]")
            raise typer.Exit(1)


@app.command("full-refresh")
def full_refresh(
    config_path: Optional[Path] = typer.Option(
        None,
        "--config", "-c",
        help="Path to sync_config.yaml",
    ),
    codebase: Optional[str] = typer.Option(
        None,
        "--codebase", "-b",
        help="Specific codebase to refresh",
    ),
    all_codebases: bool = typer.Option(
        False,
        "--all", "-a",
        help="Full refresh all enabled codebases",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Enable verbose output",
    ),
    force: bool = typer.Option(
        False,
        "--force", "-f",
        help="Skip confirmation prompt",
    ),
):
    """
    Full refresh: Clear ALL data and re-clone from scratch.
    
    This command:
    1. Clears all cached data (SQLite)
    2. Deletes Qdrant collection
    3. Re-clones repository with git clone --depth 1
    4. Processes all files fresh
    5. Stores everything anew
    
    Use this when:
    - You want a completely fresh start
    - Data is corrupted
    - Schema changed
    - You modified the config significantly
    """
    setup_logging(level="DEBUG" if verbose else "INFO", verbose=not verbose)
    
    try:
        config = Config.load(config_path)
    except Exception as e:
        console.print(f"[red]Error loading config: {e}[/red]")
        raise typer.Exit(1)

    from agent.embedding import embed_texts
    from .sync import CodeSyncEngine
    from .git_clone_sync import GitCloneSync
    
    # Confirmation prompt
    if not force:
        if codebase:
            cb_config = config.get_codebase_by_name(codebase)
            if not cb_config:
                console.print(f"[red]Codebase not found: {codebase}[/red]")
                raise typer.Exit(1)
            
            proceed = typer.confirm(
                f"This will DELETE all data for '{codebase}' and re-clone from scratch. "
                f"Continue?"
            )
        elif all_codebases:
            proceed = typer.confirm(
                f"This will DELETE all data for ALL codebases and re-clone from scratch. "
                f"Continue?"
            )
        else:
            console.print("[yellow]Specify --codebase NAME or --all[/yellow]")
            raise typer.Exit(1)
        
        if not proceed:
            console.print("[blue]Operation cancelled[/blue]")
            raise typer.Exit(0)
    
    console.print("[red]Starting full refresh...[/red]")

    with CodeSyncEngine(config, embed_texts) as engine:
        git_sync = GitCloneSync(
            cache=engine.cache,
            qdrant=engine.qdrant,
            parser=engine.parser,
            embed_fn=embed_texts,
            config=config,
        )

        if codebase:
            cb_config = config.get_codebase_by_name(codebase)
            
            console.print(f"\n[yellow]Step 1/4: Clearing cache for {codebase}...[/yellow]")
            git_sync.cache.clear_repo_data(cb_config.repo_url)
            
            console.print(f"[yellow]Step 2/4: Deleting Qdrant collection...[/yellow]")
            git_sync.qdrant.delete_collection(cb_config.collection_name)
            
            console.print(f"[yellow]Step 3/4: Cloning and processing...[/yellow]")
            result = git_sync.sync_codebase(cb_config)
            
            console.print(f"[yellow]Step 4/4: Complete![/yellow]")
            
            console.print(Panel(
                f"[green]Full Refresh Complete[/green]\n\n"
                f"Files processed: {result.files_processed}\n"
                f"Files skipped: {result.files_skipped}\n"
                f"Symbols: {result.symbols_count}\n"
                f"Vectors upserted: {result.vectors_upserted}\n"
                f"Errors: {result.errors}",
                title=f"Refresh Results: {codebase}",
                box=box.ROUNDED,
            ))
            
        elif all_codebases:
            console.print("[blue]Full refreshing all enabled codebases[/blue]")
            
            total_files = 0
            total_symbols = 0
            total_vectors = 0
            total_errors = 0
            
            for i, cb_config in enumerate(config.get_enabled_codebases(), 1):
                console.print(f"\n[bold]Codebase {i}/{len(config.get_enabled_codebases())}: {cb_config.name}[/bold]")
                
                # Clear cache
                console.print(f"  [yellow]Clearing cache...[/yellow]")
                git_sync.cache.clear_repo_data(cb_config.repo_url)
                
                # Delete collection
                console.print(f"  [yellow]Deleting collection...[/yellow]")
                git_sync.qdrant.delete_collection(cb_config.collection_name)
                
                # Fresh sync
                console.print(f"  [yellow]Cloning and processing...[/yellow]")
                result = git_sync.sync_codebase(cb_config)
                
                total_files += result.files_processed
                total_symbols += result.symbols_count
                total_vectors += result.vectors_upserted
                total_errors += result.errors
                
                if result.errors == 0:
                    console.print(
                        f"  [green]✓ {result.files_processed} files, "
                        f"{result.symbols_count} symbols[/green]"
                    )
                else:
                    console.print(f"  [red]✗ {result.errors} errors[/red]")
            
            console.print(Panel(
                f"[green]All Full Refreshes Complete[/green]\n\n"
                f"Total files: {total_files}\n"
                f"Total symbols: {total_symbols}\n"
                f"Total vectors: {total_vectors}\n"
                f"Total errors: {total_errors}",
                title="Summary",
                box=box.ROUNDED,
            ))
        else:
            console.print("[yellow]Specify --codebase NAME or --all[/yellow]")
            raise typer.Exit(1)


@app.command("start")
def start_scheduler(
    config_path: Optional[Path] = typer.Option(
        None,
        "--config", "-c",
        help="Path to sync_config.yaml",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Enable verbose output",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable debug logging (most detailed)",
    ),
):
    """
    Start the background scheduler for continuous sync.

    Monitors GitHub repositories and syncs changes automatically.
    """
    # Setup logging
    if debug:
        setup_detailed_logging(level="DEBUG")
    else:
        setup_logging(level="DEBUG" if verbose else "INFO", verbose=not verbose)

    try:
        config = Config.load(config_path)
    except Exception as e:
        console.print(f"[red]Error loading config: {e}[/red]")
        raise typer.Exit(1)

    from agent.embedding import embed_texts

    from .scheduler import create_scheduler

    console.print("[blue]Starting code documentation scheduler...[/blue]")

    scheduler = create_scheduler(config_path, embed_texts)

    console.print(Panel(
        f"[green]Scheduler Started[/green]\n\n"
        f"Monitoring {len(config.get_enabled_codebases())} codebases\n"
        f"Press Ctrl+C to stop",
        title="Scheduler Status",
        box=box.ROUNDED,
    ))

    scheduler.start()
    scheduler.wait()


# =============================================================================
# Search Commands
# =============================================================================

@app.command("search")
def search_code(
    query: str = typer.Argument(..., help="Search query"),
    codebase: Optional[str] = typer.Option(
        None,
        "--codebase", "-b",
        help="Specific codebase to search",
    ),
    top_k: int = typer.Option(5, "--top-k", "-k", help="Number of results"),
    language: Optional[str] = typer.Option(
        None,
        "--language", "-l",
        help="Filter by language",
    ),
    chunk_type: Optional[str] = typer.Option(
        None,
        "--type", "-t",
        help="Filter by chunk type (function, class, import)",
    ),
    config_path: Optional[Path] = typer.Option(
        None,
        "--config", "-c",
        help="Path to sync_config.yaml",
    ),
):
    """
    Search code documentation semantically.
    """
    setup_logging(level="INFO")
    
    try:
        config = Config.load(config_path)
    except Exception as e:
        console.print(f"[red]Error loading config: {e}[/red]")
        raise typer.Exit(1)
    
    from agent.embedding import embed_query
    
    from .search import CodeSearcher
    
    # Determine collection name
    if codebase:
        cb_config = config.get_codebase_by_name(codebase)
        if not cb_config:
            console.print(f"[red]Codebase not found: {codebase}[/red]")
            raise typer.Exit(1)
        collection_name = cb_config.collection_name
    else:
        # Use first enabled codebase
        enabled = config.get_enabled_codebases()
        if not enabled:
            console.print("[red]No codebases configured[/red]")
            raise typer.Exit(1)
        collection_name = enabled[0].collection_name
        codebase = enabled[0].name
    
    with CodeSearcher(config, embed_query) as searcher:
        results = searcher.search_code(
            query=query,
            collection_name=collection_name,
            top_k=top_k,
            language=language,
            chunk_type=chunk_type,
        )
        
        if not results:
            console.print("[yellow]No results found[/yellow]")
            return
        
        console.print(f"\n[blue]Found {len(results)} results in {codebase}[/blue]\n")
        
        for i, result in enumerate(results, 1):
            console.print(Panel(
                f"[green]{result.fully_qualified_name}[/green]\n\n"
                f"File: {result.file_path}:{result.start_line}-{result.end_line}\n"
                f"Type: {result.chunk_type} | Language: {result.language}\n"
                f"Score: {result.score:.3f}\n\n"
                f"[dim]{result.code_text[:500]}{'...' if len(result.code_text) > 500 else ''}[/dim]",
                title=f"Result {i}",
                box=box.ROUNDED,
            ))


# =============================================================================
# Cache Commands
# =============================================================================

@app.command("cache-stats")
def cache_stats(
    config_path: Optional[Path] = typer.Option(
        None,
        "--config", "-c",
        help="Path to sync_config.yaml",
    ),
):
    """Show cache statistics."""
    setup_logging(level="INFO")
    
    try:
        config = Config.load(config_path)
    except Exception as e:
        console.print(f"[red]Error loading config: {e}[/red]")
        raise typer.Exit(1)
    
    cache = CodeParseCache(config.cache.path)
    stats = cache.get_stats()
    
    table = Table(title="Cache Statistics", box=box.ROUNDED)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Files cached", str(stats["file_count"]))
    table.add_row("Symbols cached", str(stats["symbol_count"]))
    table.add_row("Repositories", str(stats["repo_count"]))
    table.add_row("Database size", f"{stats['db_size_bytes'] / 1024:.1f} KB")
    
    console.print(table)
    cache.close()


@app.command("cache-clear")
def cache_clear(
    repo_url: Optional[str] = typer.Option(
        None,
        "--repo", "-r",
        help="Clear cache for specific repo URL",
    ),
    all_cache: bool = typer.Option(
        False,
        "--all", "-a",
        help="Clear entire cache",
    ),
    config_path: Optional[Path] = typer.Option(
        None,
        "--config", "-c",
        help="Path to sync_config.yaml",
    ),
    force: bool = typer.Option(
        False,
        "--force", "-f",
        help="Skip confirmation",
    ),
):
    """Clear cache entries."""
    setup_logging(level="INFO")
    
    try:
        config = Config.load(config_path)
    except Exception as e:
        console.print(f"[red]Error loading config: {e}[/red]")
        raise typer.Exit(1)
    
    if not force:
        if repo_url:
            confirm = typer.confirm(f"Clear cache for {repo_url}?")
        elif all_cache:
            confirm = typer.confirm("Clear entire cache?")
        else:
            console.print("[yellow]Specify --repo URL or --all[/yellow]")
            raise typer.Exit(1)
        
        if not confirm:
            console.print("[blue]Cancelled[/blue]")
            raise typer.Exit(0)
    
    cache = CodeParseCache(config.cache.path)
    
    if all_cache:
        # Clear all - drop and recreate tables
        import sqlite3
        conn = sqlite3.connect(str(cache.db_path))
        conn.execute("DROP TABLE IF EXISTS file_registry")
        conn.execute("DROP TABLE IF EXISTS symbol_registry")
        conn.execute("DROP TABLE IF EXISTS commit_state")
        conn.commit()
        conn.close()
        cache._init_db()
        console.print("[green]Cache cleared[/green]")
    elif repo_url:
        cache.clear_repo_data(repo_url)
        console.print(f"[green]Cache cleared for {repo_url}[/green]")
    
    cache.close()


# =============================================================================
# Status Commands
# =============================================================================

@app.command("status")
def show_status(
    config_path: Optional[Path] = typer.Option(
        None,
        "--config", "-c",
        help="Path to sync_config.yaml",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Show detailed status",
    ),
):
    """Show system status and health."""
    setup_logging(level="INFO")
    
    try:
        config = Config.load(config_path)
    except Exception as e:
        console.print(f"[red]Error loading config: {e}[/red]")
        raise typer.Exit(1)
    
    console.print(Panel("[blue]Code Documentation System Status[/blue]"))
    
    # Health checks
    console.print("\n[bold]Health Checks[/bold]")
    
    # Qdrant
    qdrant_health = check_qdrant_health(config.qdrant.host, config.qdrant.port)
    status = "[green]✓[/green]" if qdrant_health.healthy else "[red]✗[/red]"
    console.print(f"  {status} Qdrant ({config.qdrant.host}:{config.qdrant.port}): {qdrant_health.message}")
    
    # GitHub
    github_health = check_github_connectivity()
    status = "[green]✓[/green]" if github_health.healthy else "[red]✗[/red]"
    console.print(f"  {status} GitHub API: {github_health.message}")
    
    # Cache
    cache_health = check_cache_health(config.cache.path)
    status = "[green]✓[/green]" if cache_health.healthy else "[red]✗[/red]"
    console.print(f"  {status} Cache ({config.cache.path}): {cache_health.message}")
    
    # Codebases
    console.print("\n[bold]Configured Codebases[/bold]")
    
    table = Table(box=box.ROUNDED)
    table.add_column("Name", style="cyan")
    table.add_column("Repository", style="green")
    table.add_column("Branch", style="yellow")
    table.add_column("Interval", style="magenta")
    table.add_column("Collection", style="blue")
    table.add_column("Status", style="white")
    
    for cb in config.codebases:
        status = "[green]enabled[/green]" if cb.enabled else "[dim]disabled[/dim]"
        table.add_row(
            cb.name,
            cb.repo_url,
            cb.branch,
            f"{cb.poll_interval}s",
            cb.collection_name,
            status,
        )
    
    console.print(table)
    
    if verbose:
        # Show collection stats
        console.print("\n[bold]Collection Statistics[/bold]")
        
        from .qdrant_client import QdrantCodeStore
        
        qdrant = QdrantCodeStore(
            host=config.qdrant.host,
            port=config.qdrant.port,
        )
        
        for cb in config.get_enabled_codebases():
            info = qdrant.get_collection_info(cb.collection_name)
            if info:
                console.print(
                    f"  {cb.name}: {info['points_count']} chunks, "
                    f"{info['vectors_count']} vectors"
                )
            else:
                console.print(f"  {cb.name}: [yellow]Collection not found[/yellow]")
        
        qdrant.close()


@app.command("validate-config")
def validate_config(
    config_path: Optional[Path] = typer.Option(
        None,
        "--config", "-c",
        help="Path to sync_config.yaml",
    ),
):
    """Validate configuration file."""
    setup_logging(level="INFO")
    
    try:
        config = Config.load(config_path)
    except Exception as e:
        console.print(f"[red]Error loading config: {e}[/red]")
        raise typer.Exit(1)
    
    errors = config.validate()
    
    if errors:
        console.print("[red]Configuration errors:[/red]")
        for error in errors:
            console.print(f"  • {error}")
        raise typer.Exit(1)
    else:
        console.print("[green]✓ Configuration is valid[/green]")
        console.print(f"\nLoaded {len(config.codebases)} codebases "
                     f"({len(config.get_enabled_codebases())} enabled)")


# =============================================================================
# Entry Point
# =============================================================================

def main():
    """CLI entry point."""
    app()


if __name__ == "__main__":
    main()
