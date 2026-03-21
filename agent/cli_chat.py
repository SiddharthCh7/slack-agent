#!/usr/bin/env python3
"""
Interactive CLI for OLake Deep Research Agent

Pretty-formatted input/output with conversation threading.
"""

import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
import json
import threading

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from rich.console import Console, Group
from rich.panel import Panel
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.live import Live
from rich.text import Text
from rich.spinner import Spinner
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich.box import ROUNDED
from rich.tree import Tree

import logging
import readline  # For better input handling

# Disable console logging for CLI mode BEFORE importing other agent modules
# This must happen before importing any modules that use get_logger()
from agent.logger import get_logger
get_logger(enable_console=False)

# Now import other agent modules
from agent.state import create_initial_state
from agent.cli_graph import get_cli_agent_graph
from agent.github_repo_tracker import GitHubRepoTracker

# Configure Rich console
console = Console(width=120)

# Configure logging - disable Rich handler to avoid duplicate logs
# Only use the structured logger from agent.logger
logging.basicConfig(
    level=logging.WARNING,  # Only show warnings and above
    format="%(message)s",
    datefmt="[%X]",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)


class Colors:
    """ANSI color codes for terminal output."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    # Foreground colors
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"
    
    # Background
    BG_BLUE = "\033[44m"
    BG_DARK = "\033[48;5;236m"


class ConversationThread:
    """Maintains conversation state and history."""
    
    def __init__(self):
        self.messages: List[Dict[str, str]] = []
        self.state: Optional[Dict[str, Any]] = None
        self.graph = None
        self.thread_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.start_time = datetime.now()
        
    def add_message(self, role: str, content: str):
        """Add a message to the conversation history."""
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })
    
    def get_context(self) -> str:
        """Get conversation context for the LLM."""
        if not self.messages:
            return ""
        
        context_lines = []
        for msg in self.messages[-10:]:  # Last 10 messages
            context_lines.append(f"{msg['role']}: {msg['content']}")
        
        return "\n".join(context_lines)


def _build_progress_display(events: List[Dict], still_running: bool, console: Console):
    """Build Rich renderable for live progress (streamed thinking, search_intent, commands, files)."""
    parts = []
    # Per-iteration streamed text (thinking_chunk deltas)
    streamed_by_iter: Dict[int, str] = {}
    for ev in events:
        if ev.get("type") == "thinking_chunk":
            it = ev.get("iteration", 0)
            streamed_by_iter[it] = streamed_by_iter.get(it, "") + (ev.get("delta") or "")

    started_iters = [ev["iteration"] for ev in events if ev.get("type") == "thinking_start"]
    done_iters = {ev["iteration"] for ev in events if ev.get("type") == "thinking_done"}
    current_iter = next((it for it in reversed(started_iters) if it not in done_iters), None)
    if still_running and current_iter is not None:
        parts.append(Group(Spinner("dots"), Text("  Thinking…", style="cyan")))

    tree = Tree("[bold]Research progress[/bold]", expanded=True)
    for ev in events:
        t = ev.get("type")
        if t == "thinking_done":
            it = ev.get("iteration", 0)
            preview = ev.get("preview", "")
            full = ev.get("thinking", "")
            branch = tree.add(
                f"[dim]▸[/dim] [magenta]Thinking (iteration {it}):[/magenta] {preview}",
                expanded=False,
            )
            branch.add(Text(full, style="dim"))
        elif t == "search_intent":
            text = ev.get("text", "")
            tree.add(f"[dim]▸[/dim] [blue]Search intent:[/blue] {text}")
        elif t == "commands_ran":
            cmds = ev.get("commands", [])
            branch = tree.add("[dim]▸[/dim] [yellow]Commands ran:[/yellow]", expanded=False)
            for c in cmds:
                branch.add(Text(c, style="dim"))
        elif t == "files_found":
            count = ev.get("count", 0)
            paths = ev.get("paths", [])
            summary = ", ".join(paths[:3])
            if len(paths) > 3:
                summary += f" (+{len(paths) - 3} more)"
            if not summary:
                summary = "(none)"
            branch = tree.add(
                f"[dim]▸[/dim] [green]Files found ({count}):[/green] {summary}",
                expanded=False,
            )
            for p in paths[:15]:
                branch.add(Text(p, style="dim"))
            if len(paths) > 15:
                branch.add(Text(f"... and {len(paths) - 15} more", style="dim"))

    # In-progress streamed thinking (one branch, updated each refresh)
    if current_iter is not None:
        streamed = streamed_by_iter.get(current_iter, "")
        preview = (streamed[:80] + "…") if len(streamed) > 80 else (streamed or "…")
        branch = tree.add(
            f"[dim]▸[/dim] [magenta]Thinking (iteration {current_iter}):[/magenta] {preview}",
            expanded=False,
        )
        branch.add(Text(streamed or "Waiting for model…", style="dim"))

    if parts:
        parts.append(tree)
        return Group(*parts)
    return tree


class CLIAgent:
    """Interactive CLI Agent with pretty formatting."""

    def __init__(self):
        self.console = console
        self.thread = ConversationThread()
        self.tracker = GitHubRepoTracker()
        self.setup_complete = False
        
    def print_banner(self):
        """Print welcome banner."""
        from agent.github_repo_tracker import GitHubRepoTracker
        
        # Get repo path info
        tracker = GitHubRepoTracker()
        repo_path = tracker.repos_dir
        
        banner = f"""
╔═══════════════════════════════════════════════════════════╗
║           OLake Deep Research Agent                       ║
║           Interactive CLI                                 ║
╚═══════════════════════════════════════════════════════════╝

📂 Repositories: {repo_path}

Type your question below. Type 'quit' or 'exit' to end.
Type 'thinking' to see last reasoning trace.
Type 'files' to see retrieved files.
Type 'commands' to see executed commands (coming soon).
        """
        self.console.print(Panel(
            banner,
            style="cyan",
            box=ROUNDED,
        ))
    
    def setup_repositories(self) -> bool:
        """Setup and clone repositories if needed."""
        self.console.print("\n[yellow]⚙️  Setting up repositories...[/yellow]\n")
        
        if not self.tracker.repos:
            self.console.print("[yellow]⚠️  No repositories configured in github_repos.yaml[/yellow]")
            self.console.print("[dim]Add repos to github_repos.yaml to enable codebase search[/dim]\n")
            return True
        
        # Clone any missing repos
        cloned_count = 0
        for name, repo in self.tracker.repos.items():
            if not repo.enabled:
                continue
            
            repo_path = self.tracker.get_repo_path(name)
            if repo_path:
                self.console.print(f"[green]✓[/green] {name}: Already cloned")
            else:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    console=self.console,
                ) as progress:
                    task = progress.add_task(f"[cyan]Cloning {name}...", total=None)
                    result = self.tracker.clone_repo(name)
                    progress.remove_task(task)
                
                if result["success"]:
                    self.console.print(f"[green]✓[/green] {name}: Cloned to {result.get('path', 'unknown')}")
                    cloned_count += 1
                else:
                    self.console.print(f"[red]✗[/red] {name}: {result['message']}")
        
        if cloned_count > 0:
            self.console.print(f"\n[green]✓ Setup complete: {cloned_count} repo(s) cloned[/green]\n")
        
        return True
    
    def setup_sync(self) -> bool:
        """Setup background sync if not already configured."""
        # Check if cron is already set up
        import subprocess
        try:
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
            )
            if "sync_github_repos.py" in result.stdout:
                self.console.print("[dim]✓ Background sync already configured[/dim]\n")
                return True
        except Exception:
            pass
        
        # Ask user if they want to setup sync
        self.console.print("\n[yellow]💡 Tip: Setup automatic repo sync in background?[/yellow]")
        self.console.print("[dim]This keeps your local repos updated daily at 3 AM[/dim]\n")
        
        try:
            response = input("Setup auto-sync? [y/N]: ").strip().lower()
            if response in ["y", "yes"]:
                self.console.print("\n[dim]Running: ./setup_github_sync.sh daily[/dim]\n")
                import subprocess
                subprocess.run(
                    [str(project_root / "setup_github_sync.sh"), "daily"],
                    cwd=str(project_root),
                )
                self.console.print("[green]✓ Auto-sync configured[/green]\n")
        except KeyboardInterrupt:
            pass
        
        return True
    
    def initialize(self) -> bool:
        """Initialize the agent (setup repos, load graph, etc.)."""
        self.print_banner()

        # Setup repositories
        if not self.setup_repositories():
            return False

        # Skip sync setup in CLI mode (user can run manually if needed)
        # self.setup_sync()

        # Load agent graph
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
        ) as progress:
            task = progress.add_task("[cyan]Loading agent...", total=None)
            try:
                self.thread.graph = get_cli_agent_graph()
                progress.remove_task(task)
                self.console.print("[green]✓ Agent loaded[/green]\n")
            except Exception as e:
                progress.remove_task(task)
                self.console.print(f"[red]✗ Failed to load agent: {e}[/red]\n")
                return False

        self.setup_complete = True
        return True
    
    def print_thinking(self, thinking: str):
        """Print thinking trace in a styled panel."""
        if not thinking:
            return
        
        self.console.print(Panel(
            thinking,
            title="[bold magenta]🧠 Thinking Process[/bold magenta]",
            style="magenta",
            box=ROUNDED,
        ))
    
    def print_files(self, files: List[Any]):
        """Print retrieved files in a formatted list."""
        if not files:
            return

        self.console.print(Rule("[bold blue]📁 Retrieved Files[/bold blue]"))

        for i, file in enumerate(files[:10], 1):  # Show top 10
            self.console.print(f"\n[bold cyan]{i}.[/bold cyan] [yellow]{file.path}[/yellow]")
            self.console.print(f"   [dim]Matches: {len(file.matches)}[/dim]")
            self.console.print(f"   [dim]Why: {file.retrieval_reason}[/dim]")

            if file.matches:
                self.console.print(f"   [dim]Matches:[/dim]")
                for match in file.matches[:3]:
                    display_match = match[:100] if len(match) > 100 else match
                    self.console.print(f"     [gray]• {display_match}[/gray]")

            # Show content preview for small files
            if file.content and len(file.content) < 2000:
                self.console.print(f"   [dim]Content preview:[/dim]")
                self.console.print(f"     [gray]{file.content[:500]}[/gray]")

        if len(files) > 10:
            self.console.print(f"\n[dim]... and {len(files) - 10} more files[/dim]")
    
    def print_research_summary(self, state: Dict[str, Any]):
        """Print research summary after agent processing."""
        thinking_log = state.get("thinking_log", [])
        research_files = state.get("research_files", [])

        # Print thinking log
        if thinking_log:
            self.console.print("\n")
            for entry in thinking_log:
                if ": " in entry:
                    thinking = entry.split(": ", 1)[1]
                    self.print_thinking(thinking)

        # Print files
        if research_files:
            self.console.print("\n")
            self.print_files(research_files)

        # Print summary
        self.console.print(f"\n[bold green]✓ Research Complete[/bold green]")
        self.console.print(
            f"   [dim]Iterations: {len(state.get('search_history') or [])} | "
            f"Files: {len(research_files)}[/dim]\n"
        )
    
    def process_message(self, message: str) -> Optional[str]:
        """Process a user message through the agent."""
        if not self.thread.graph:
            return "Agent not initialized. Please restart."
        
        # Create state for this message
        state = create_initial_state({
            "event": {
                "channel": "cli_channel",
                "user": "cli_user",
                "text": message,
                "ts": datetime.now().isoformat(),
            }
        })
        
        # Add conversation context
        context = self.thread.get_context()
        if context:
            state["user_query"] = f"{context}\n\nUser: {message}"

        # Shared progress events for live CLI display (deep_researcher calls _cli_progress_callback)
        progress_events: List[Dict] = []
        progress_lock = threading.Lock()

        def on_progress(ev: dict) -> None:
            with progress_lock:
                progress_events.append(ev)

        state["_cli_progress_callback"] = on_progress

        result_holder: List[Optional[Dict]] = [None]
        exc_holder: List[Optional[Exception]] = [None]

        def run_graph() -> None:
            try:
                result_holder[0] = self.thread.graph.invoke(state)
            except Exception as e:
                exc_holder[0] = e

        graph_thread = threading.Thread(target=run_graph)
        graph_thread.start()

        def make_display() -> Any:
            with progress_lock:
                events_snapshot = list(progress_events)
            return _build_progress_display(
                events_snapshot, graph_thread.is_alive(), self.console
            )

        with Live(
            make_display,
            refresh_per_second=4,
            console=self.console,
        ) as live:
            graph_thread.join()

        if exc_holder[0] is not None:
            self.console.print(f"[red]Error: {exc_holder[0]}[/red]")
            log.exception("Agent error")
            return None

        result = result_holder[0]
        if result is None:
            return None

        # Store state for later reference
        self.thread.state = result

        # Short summary; full thinking/files available via 'thinking' and 'files' commands
        research_files = result.get("research_files", [])
        self.console.print(f"\n[bold green]✓ Research complete[/bold green]")
        self.console.print(
            f"   [dim]Iterations: {len(result.get('search_history') or [])} | "
            f"Files: {len(research_files)}[/dim]"
        )
        self.console.print(
            "[dim]Type [cyan]thinking[/cyan] or [cyan]files[/cyan] for full details.[/dim]\n"
        )
        
        # Get response
        response = result.get("response_text")
        
        if response:
            return response
        else:
            # Generate a response from research context
            files = result.get("research_files", [])
            if files:
                return self._generate_response_from_files(message, files)
            return "I wasn't able to find enough information to answer your question."
    
    def _generate_response_from_files(self, query: str, files: List[Any]) -> str:
        """Generate a response based on retrieved files."""
        # Simple response generation based on file content
        response_parts = [
            "Based on my research in the codebase, here's what I found:\n",
        ]
        
        # Summarize files
        for i, file in enumerate(files[:5], 1):
            response_parts.append(f"\n**{i}. {file.path}**")
            response_parts.append(f"- {file.retrieval_reason}")
            
            # Add relevant matches
            if file.matches:
                response_parts.append(f"- Key content: `{file.matches[0][:100]}...`")
        
        response_parts.append("\n\nWould you like me to search for anything specific in these files?")
        
        return "\n".join(response_parts)
    
    def print_response(self, response: str):
        """Print agent response in a styled panel."""
        if not response:
            return
        
        self.console.print(Panel(
            Markdown(response),
            title="[bold green]🤖 Agent Response[/bold green]",
            style="green",
            box=ROUNDED,
        ))
    
    def print_input(self, message: str):
        """Print user input in a styled format."""
        self.console.print(f"\n[bold blue]👤 You:[/bold blue] {message}\n")
    
    def run(self):
        """Main CLI loop."""
        if not self.initialize():
            self.console.print("[red]Failed to initialize agent[/red]")
            sys.exit(1)
        
        self.console.print(Rule("[bold]Start chatting[/bold]"))
        
        while True:
            try:
                # Get user input
                try:
                    user_input = input(f"{Colors.CYAN}┌─{Colors.RESET}\n{Colors.CYAN}│{Colors.RESET}  ").strip()
                except EOFError:
                    break
                
                if not user_input:
                    continue
                
                # Handle commands
                if user_input.lower() in ["quit", "exit", "q"]:
                    self.console.print("\n[yellow]Goodbye! 👋[/yellow]\n")
                    break
                
                if user_input.lower() == "thinking":
                    if self.thread.state:
                        thinking_log = self.thread.state.get("thinking_log", [])
                        if thinking_log:
                            for entry in thinking_log:
                                if ": " in entry:
                                    self.print_thinking(entry.split(": ", 1)[1])
                        else:
                            self.console.print("[dim]No thinking trace available[/dim]")
                    continue
                
                if user_input.lower() == "files":
                    if self.thread.state:
                        files = self.thread.state.get("research_files", [])
                        if files:
                            self.print_files(files)
                        else:
                            self.console.print("[dim]No files retrieved yet[/dim]")
                    continue
                
                if user_input.lower() == "help":
                    self.console.print("""
[bold]Commands:[/bold]
  [cyan]thinking[/cyan]  - Show last reasoning trace
  [cyan]files[/cyan]     - Show retrieved files
  [cyan]help[/cyan]      - Show this help
  [cyan]quit/exit[/cyan] - End conversation
                    """)
                    continue
                
                # Print user input
                self.print_input(user_input)
                
                # Add to conversation history
                self.thread.add_message("User", user_input)
                
                # Process message
                response = self.process_message(user_input)
                
                if response:
                    # Add to conversation history
                    self.thread.add_message("Agent", response)
                    
                    # Print response
                    self.print_response(response)
                
            except KeyboardInterrupt:
                self.console.print("\n[yellow]Interrupted. Type 'quit' to exit.[/yellow]")
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")
                log.exception("CLI error")


def main():
    """Entry point for CLI."""
    console.print(f"\n[dim]Starting OLake Deep Research Agent CLI...[/dim]\n")
    
    try:
        agent = CLIAgent()
        agent.run()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"[red]Fatal error: {e}[/red]")
        log.exception("Fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main()
