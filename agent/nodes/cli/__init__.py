"""
CLI-mode nodes for the agent. Not used in production.

Production uses agent.graph (Slack nodes: context_builder, solution_provider, etc.).
This package is for CLI-only flows (cli_chat.py, interactive chat) that avoid
Slack API. test_agent.py uses the production graph, not this — so changes to
the main agent are tested and reflected in prod.
"""

from agent.nodes.cli.context_builder import build_cli_context
from agent.nodes.cli.solution_provider import cli_solution_provider

__all__ = [
    "build_cli_context",
    "cli_solution_provider",
]
