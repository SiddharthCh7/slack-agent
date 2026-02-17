"""
Structured logging system for OLake Slack Community Agent.

Provides comprehensive logging of all events including:
- Incoming messages
- User profiles
- Reasoning steps
- Documentation searches
- Responses
- Escalations
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from enum import Enum


class EventType(Enum):
    """Types of events to log."""
    MESSAGE_RECEIVED = "message_received"
    INTENT_CLASSIFIED = "intent_classified"
    CONTEXT_LOADED = "context_loaded"
    DOCS_SEARCHED = "docs_searched"
    REASONING_ITERATION = "reasoning_iteration"
    CLARIFICATION_NEEDED = "clarification_needed"
    SOLUTION_PROVIDED = "solution_provided"
    ESCALATION_TRIGGERED = "escalation_triggered"
    RESPONSE_SENT = "response_sent"
    ERROR_OCCURRED = "error_occurred"


class StructuredLogger:
    """Structured logger for agent events."""
    
    def __init__(self, log_dir: str = "logs", log_level: str = "INFO"):
        """
        Initialize structured logger.
        
        Args:
            log_dir: Directory for log files
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        # Create separate log files
        self.events_log = self.log_dir / "events.jsonl"
        self.errors_log = self.log_dir / "errors.jsonl"
        self.reasoning_log = self.log_dir / "reasoning.jsonl"
        
        # Setup standard logger
        self.logger = logging.getLogger("slack_agent")
        self.logger.setLevel(getattr(logging, log_level.upper()))
        
        # Console handler with clean formatting
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '%(asctime)s | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # File handler for detailed logs
        file_handler = logging.FileHandler(self.log_dir / "agent.log")
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s | %(name)s | %(levelname)s | %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)
    
    def _write_jsonl(self, filepath: Path, data: Dict[str, Any]) -> None:
        """Write a JSON line to a log file."""
        with open(filepath, 'a') as f:
            f.write(json.dumps(data) + '\n')
    
    def log_event(
        self,
        event_type: EventType,
        message: str,
        user_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        thread_ts: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log a structured event.
        
        Args:
            event_type: Type of event
            message: Human-readable message
            user_id: Slack user ID
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
            metadata: Additional metadata
        """
        event_data = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type.value,
            "message": message,
            "user_id": user_id,
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "metadata": metadata or {}
        }
        
        self._write_jsonl(self.events_log, event_data)
        
        # Also log to standard logger
        log_msg = f"{event_type.value.upper()}: {message}"
        if user_id:
            log_msg += f" | User: {user_id}"
        if channel_id:
            log_msg += f" | Channel: {channel_id}"
        
        self.logger.info(log_msg)
    
    def log_message_received(
        self,
        user_id: str,
        channel_id: str,
        text: str,
        thread_ts: Optional[str] = None,
        user_profile: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log an incoming message."""
        self.log_event(
            event_type=EventType.MESSAGE_RECEIVED,
            message=f"Message received: {text[:100]}...",
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            metadata={
                "text": text,
                "user_profile": user_profile
            }
        )
    
    def log_reasoning_iteration(
        self,
        iteration: int,
        thought_process: str,
        confidence: float,
        user_id: str,
        channel_id: str
    ) -> None:
        """Log a reasoning iteration."""
        reasoning_data = {
            "timestamp": datetime.now().isoformat(),
            "iteration": iteration,
            "thought_process": thought_process,
            "confidence": confidence,
            "user_id": user_id,
            "channel_id": channel_id
        }
        
        self._write_jsonl(self.reasoning_log, reasoning_data)
        
        self.logger.debug(
            f"Reasoning iteration {iteration} | Confidence: {confidence:.2f} | "
            f"Thought: {thought_process[:100]}..."
        )
    
    def log_docs_searched(
        self,
        query: str,
        num_results: int,
        top_results: list,
        user_id: str,
        channel_id: str
    ) -> None:
        """Log documentation search."""
        self.log_event(
            event_type=EventType.DOCS_SEARCHED,
            message=f"Searched docs for: {query}",
            user_id=user_id,
            channel_id=channel_id,
            metadata={
                "query": query,
                "num_results": num_results,
                "top_results": top_results
            }
        )
    
    def log_response_sent(
        self,
        user_id: str,
        channel_id: str,
        response_text: str,
        confidence: float,
        reasoning_summary: str,
        thread_ts: Optional[str] = None,
        docs_cited: Optional[list] = None
    ) -> None:
        """Log a response sent to user."""
        self.log_event(
            event_type=EventType.RESPONSE_SENT,
            message=f"Response sent (confidence: {confidence:.2f})",
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            metadata={
                "response_text": response_text,
                "confidence": confidence,
                "reasoning_summary": reasoning_summary,
                "docs_cited": docs_cited or []
            }
        )
    
    def log_escalation(
        self,
        user_id: str,
        channel_id: str,
        reason: str,
        original_message: str,
        thread_ts: Optional[str] = None
    ) -> None:
        """Log an escalation to human team."""
        self.log_event(
            event_type=EventType.ESCALATION_TRIGGERED,
            message=f"Escalated to team: {reason}",
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            metadata={
                "reason": reason,
                "original_message": original_message
            }
        )
    
    def log_error(
        self,
        error_type: str,
        error_message: str,
        stack_trace: Optional[str] = None,
        user_id: Optional[str] = None,
        channel_id: Optional[str] = None
    ) -> None:
        """Log an error."""
        error_data = {
            "timestamp": datetime.now().isoformat(),
            "error_type": error_type,
            "error_message": error_message,
            "stack_trace": stack_trace,
            "user_id": user_id,
            "channel_id": channel_id
        }
        
        self._write_jsonl(self.errors_log, error_data)
        
        self.logger.error(
            f"ERROR: {error_type} - {error_message}",
            exc_info=stack_trace is not None
        )


# Global logger instance
_logger: Optional[StructuredLogger] = None


def get_logger(log_dir: str = "logs", log_level: str = "INFO") -> StructuredLogger:
    """Get or create the global logger instance."""
    global _logger
    if _logger is None:
        _logger = StructuredLogger(log_dir=log_dir, log_level=log_level)
    return _logger
