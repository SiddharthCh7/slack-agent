"""
GitHub Repository Tracker

Manages cloning and syncing of GitHub repositories for codebase search.
- Clones repos to hidden .github_repos directory
- Provides interface to add/remove/list tracked repos
- Syncs repos in background via cron
"""

import os
import yaml
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime
import logging

from agent.terminal_tool import TerminalTool, TerminalToolConfig

log = logging.getLogger(__name__)


@dataclass
class RepoConfig:
    """Configuration for a tracked repository."""
    name: str
    url: str
    branch: Optional[str] = None
    enabled: bool = True
    last_sync: Optional[datetime] = None
    sync_frequency: str = "daily"  # hourly, daily, weekly


class GitHubRepoTracker:
    """
    Tracks and syncs GitHub repositories for local codebase search.
    
    Repos are stored in .github_repos/ directory (hidden from casual view).
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize the tracker.
        
        Args:
            config_path: Path to config/repos.yaml (defaults to project root config/repos.yaml)
        """
        self.project_root = Path(__file__).parent.parent
        self.repos_dir = self.project_root / ".github_repos"
        self.config_path = config_path or (self.project_root / "config" / "repos.yaml")
        self.terminal = TerminalTool()
        
        self.repos: Dict[str, RepoConfig] = {}
        self._load_config()
    
    def _load_config(self) -> None:
        """Load repository configuration from YAML file."""
        if not self.config_path.exists():
            log.info(f"Config file not found: {self.config_path}")
            return
        
        try:
            with open(self.config_path, "r") as f:
                config = yaml.safe_load(f) or {}
            
            for name, repo_data in config.get("repositories", {}).items():
                self.repos[name] = RepoConfig(
                    name=name,
                    url=repo_data.get("url", ""),
                    branch=repo_data.get("branch"),
                    enabled=repo_data.get("enabled", True),
                    sync_frequency=repo_data.get("sync_frequency", "daily"),
                )
            
            log.info(f"Loaded {len(self.repos)} repository configurations")
            
        except yaml.YAMLError as e:
            log.error(f"Failed to load config: {e}")
    
    def _save_config(self) -> None:
        """Save repository configuration to YAML file."""
        config = {"repositories": {}}
        
        for name, repo in self.repos.items():
            config["repositories"][name] = {
                "url": repo.url,
                "branch": repo.branch,
                "enabled": repo.enabled,
                "sync_frequency": repo.sync_frequency,
            }
        
        with open(self.config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    
    def _ensure_repos_dir(self) -> None:
        """Create the hidden repos directory if it doesn't exist."""
        self.repos_dir.mkdir(parents=True, exist_ok=True)
        # Hide the directory on Unix systems (prefix with .)
        # Already hidden by naming convention
    
    def add_repo(self, name: str, url: str, branch: Optional[str] = None) -> Dict[str, Any]:
        """
        Add a new repository to track.
        
        Args:
            name: Short name for the repo (used as directory name)
            url: GitHub repository URL
            branch: Optional branch to checkout (default: main/master)
        
        Returns:
            Dict with status and message
        """
        if name in self.repos:
            return {"success": False, "message": f"Repository '{name}' already exists"}
        
        # Add to config
        self.repos[name] = RepoConfig(name=name, url=url, branch=branch)
        self._save_config()
        
        # Clone the repository
        return self.clone_repo(name)
    
    def clone_repo(self, name: str) -> Dict[str, Any]:
        """
        Clone a repository.
        
        Args:
            name: Repository name from config
        
        Returns:
            Dict with status and message
        """
        if name not in self.repos:
            return {"success": False, "message": f"Repository '{name}' not in config"}
        
        repo = self.repos[name]
        self._ensure_repos_dir()
        
        repo_path = self.repos_dir / name
        
        # Check if already cloned
        if repo_path.exists():
            log.info(f"Repository '{name}' already exists at {repo_path}")
            return {
                "success": True,
                "message": f"Repository already cloned at {repo_path}",
                "path": str(repo_path),
            }
        
        # Build clone command
        branch_opt = f"--branch {repo.branch} " if repo.branch else ""
        cmd = f"git clone {branch_opt}{repo.url} {repo_path}"
        
        log.info(f"Cloning {name}: {cmd}")
        
        result = self.terminal.execute(cmd)
        
        if result.success:
            log.info(f"Successfully cloned {name} to {repo_path}")
            return {
                "success": True,
                "message": f"Cloned {name} to {repo_path}",
                "path": str(repo_path),
            }
        else:
            error_msg = result.stderr or result.error_message
            log.error(f"Failed to clone {name}: {error_msg}")
            return {
                "success": False,
                "message": f"Failed to clone: {error_msg}",
            }
    
    def sync_repo(self, name: str) -> Dict[str, Any]:
        """
        Sync a repository with git pull from origin (no GitHub API).

        Uses the branch from config (default main). If pull fails for branch
        main, retries with origin master.

        Args:
            name: Repository name

        Returns:
            Dict with status and message
        """
        if name not in self.repos:
            return {"success": False, "message": f"Repository '{name}' not in config"}

        repo = self.repos[name]
        repo_path = self.repos_dir / name

        if not repo_path.exists():
            log.info(f"Repository '{name}' not found, cloning...")
            return self.clone_repo(name)

        branch = repo.branch or "main"
        pull_result = self.terminal.execute(
            f"git pull origin {branch}",
            working_dir=repo_path,
        )
        if not pull_result.success:
            if branch == "main":
                pull_result = self.terminal.execute(
                    "git pull origin master",
                    working_dir=repo_path,
                )
            if not pull_result.success:
                error_msg = pull_result.stderr or pull_result.error_message
                log.error(f"Failed to git pull for {name}: {error_msg}")
                return {
                    "success": False,
                    "message": f"Failed to git pull: {error_msg}",
                }

        repo.last_sync = datetime.now()
        self._save_config()
        log.info(f"Successfully synced {name}")
        return {
            "success": True,
            "message": f"Synced {name}",
            "output": pull_result.stdout[:500] if pull_result.stdout else "No changes",
        }
    
    def sync_all(self) -> Dict[str, Any]:
        """
        Sync all enabled repositories.
        
        Returns:
            Dict with summary of sync operations
        """
        results = {}
        success_count = 0
        error_count = 0
        
        for name, repo in self.repos.items():
            if not repo.enabled:
                log.info(f"Skipping disabled repo: {name}")
                continue
            
            result = self.sync_repo(name)
            results[name] = result
            
            if result["success"]:
                success_count += 1
            else:
                error_count += 1
        
        return {
            "success": error_count == 0,
            "total": len(self.repos),
            "synced": success_count,
            "errors": error_count,
            "results": results,
        }
    
    def remove_repo(self, name: str, delete_local: bool = False) -> Dict[str, Any]:
        """
        Remove a repository from tracking.
        
        Args:
            name: Repository name
            delete_local: If True, also delete local clone
        
        Returns:
            Dict with status and message
        """
        if name not in self.repos:
            return {"success": False, "message": f"Repository '{name}' not in config"}
        
        # Remove from config
        del self.repos[name]
        self._save_config()
        
        # Optionally delete local clone
        if delete_local:
            repo_path = self.repos_dir / name
            if repo_path.exists():
                cmd = f"rm -rf {repo_path}"
                result = self.terminal.execute(cmd)
                if result.success:
                    log.info(f"Deleted local clone: {repo_path}")
                else:
                    log.error(f"Failed to delete {repo_path}: {result.error_message}")
        
        log.info(f"Removed repository '{name}' from tracking")
        return {"success": True, "message": f"Removed '{name}' from tracking"}
    
    def list_repos(self) -> List[Dict[str, Any]]:
        """
        List all tracked repositories.
        
        Returns:
            List of repo info dicts
        """
        repos = []
        for name, repo in self.repos.items():
            repo_path = self.repos_dir / name
            exists = repo_path.exists()
            
            repos.append({
                "name": name,
                "url": repo.url,
                "branch": repo.branch,
                "enabled": repo.enabled,
                "sync_frequency": repo.sync_frequency,
                "local_path": str(repo_path) if exists else None,
                "cloned": exists,
            })
        
        return repos
    
    def get_repo_path(self, name: str) -> Optional[Path]:
        """
        Get the local path for a repository.
        
        Args:
            name: Repository name
        
        Returns:
            Path to repo or None if not cloned
        """
        if name not in self.repos:
            return None
        
        repo_path = self.repos_dir / name
        if repo_path.exists():
            return repo_path
        return None
    
    def get_all_repo_paths(self) -> List[Path]:
        """
        Get paths to all cloned repositories.
        
        Returns:
            List of Path objects for cloned repos
        """
        paths = []
        for name in self.repos:
            path = self.get_repo_path(name)
            if path:
                paths.append(path)
        return paths


# Convenience functions for direct usage

def add_repo(name: str, url: str, branch: Optional[str] = None) -> Dict[str, Any]:
    """Add and clone a new repository."""
    tracker = GitHubRepoTracker()
    return tracker.add_repo(name, url, branch)


def sync_repo(name: str) -> Dict[str, Any]:
    """Sync a specific repository."""
    tracker = GitHubRepoTracker()
    return tracker.sync_repo(name)


def sync_all_repos() -> Dict[str, Any]:
    """Sync all tracked repositories."""
    tracker = GitHubRepoTracker()
    return tracker.sync_all()


def list_tracked_repos() -> List[Dict[str, Any]]:
    """List all tracked repositories."""
    tracker = GitHubRepoTracker()
    return tracker.list_repos()


if __name__ == "__main__":
    # CLI usage example
    import sys
    
    tracker = GitHubRepoTracker()
    
    if len(sys.argv) < 2:
        print("Usage: python github_repo_tracker.py [add|sync|list|remove] [args...]")
        print("\nCommands:")
        print("  add <name> <url> [branch]  - Add and clone a repo")
        print("  sync [name]                - Sync a repo (or all if no name)")
        print("  list                       - List all tracked repos")
        print("  remove <name>              - Remove a repo from tracking")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "add":
        if len(sys.argv) < 4:
            print("Error: add requires <name> <url> [branch]")
            sys.exit(1)
        name = sys.argv[2]
        url = sys.argv[3]
        branch = sys.argv[4] if len(sys.argv) > 4 else None
        result = tracker.add_repo(name, url, branch)
        print(f"{'✓' if result['success'] else '✗'} {result['message']}")
    
    elif command == "sync":
        if len(sys.argv) > 2:
            result = tracker.sync_repo(sys.argv[2])
        else:
            result = tracker.sync_all()
        print(f"{'✓' if result['success'] else '✗'} Sync complete")
        if "results" in result:
            print(f"  Synced: {result['synced']}/{result['total']}, Errors: {result['errors']}")
    
    elif command == "list":
        repos = tracker.list_repos()
        if not repos:
            print("No repositories tracked")
        else:
            print(f"Tracked repositories ({len(repos)}):")
            for repo in repos:
                status = "✓" if repo["cloned"] else "○"
                branch = f" ({repo['branch']})" if repo["branch"] else ""
                print(f"  {status} {repo['name']}{branch}")
                print(f"     {repo['url']}")
                if repo["cloned"]:
                    print(f"     Path: {repo['local_path']}")
    
    elif command == "remove":
        if len(sys.argv) < 3:
            print("Error: remove requires <name>")
            sys.exit(1)
        result = tracker.remove_repo(sys.argv[2], delete_local=True)
        print(f"{'✓' if result['success'] else '✗'} {result['message']}")
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
