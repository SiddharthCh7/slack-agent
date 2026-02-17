"""
Database persistence for OLake Slack Community Agent.

Manages storage of conversations, user profiles, and interaction history.
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from contextlib import contextmanager

from agent.state import (
    ConversationRecord,
    UserInteraction,
    UserProfile,
    IntentType,
    UrgencyLevel
)
from agent.logger import get_logger


class Database:
    """SQLite database for agent persistence."""
    
    def __init__(self, db_path: str = "data/slack_agent.db"):
        """
        Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger()
        self._init_database()
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def _init_database(self) -> None:
        """Initialize database schema."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Conversations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_ts TEXT NOT NULL UNIQUE,
                    thread_ts TEXT,
                    channel_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    message_text TEXT NOT NULL,
                    intent_type TEXT,
                    urgency TEXT,
                    response_text TEXT,
                    confidence REAL DEFAULT 0.0,
                    needs_clarification INTEGER DEFAULT 0,
                    escalated INTEGER DEFAULT 0,
                    escalation_reason TEXT,
                    docs_cited TEXT,
                    reasoning_summary TEXT,
                    processing_time REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    resolved INTEGER DEFAULT 0,
                    resolved_at TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_user 
                ON conversations(user_id, created_at DESC)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_thread 
                ON conversations(thread_ts)
            """)
            
            # User interactions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    message_ts TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    topic TEXT,
                    resolved INTEGER DEFAULT 0,
                    resolution_time REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (message_ts) REFERENCES conversations(message_ts)
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_interactions 
                ON user_interactions(user_id, created_at DESC)
            """)
            
            # User profiles table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    username TEXT,
                    real_name TEXT,
                    email TEXT,
                    total_messages INTEGER DEFAULT 0,
                    common_topics TEXT,
                    resolved_issues INTEGER DEFAULT 0,
                    unresolved_issues INTEGER DEFAULT 0,
                    avg_resolution_time REAL DEFAULT 0.0,
                    last_interaction TIMESTAMP,
                    knowledge_level TEXT DEFAULT 'beginner',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Documentation lookups cache
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS documentation_lookups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    results TEXT NOT NULL,
                    relevance_score REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_doc_lookups_query 
                ON documentation_lookups(query, created_at DESC)
            """)
            
            self.logger.logger.info("Database initialized successfully")
    
    def save_conversation(self, record: ConversationRecord) -> int:
        """
        Save a conversation record.
        
        Args:
            record: ConversationRecord to save
            
        Returns:
            ID of inserted record
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO conversations (
                    message_ts, thread_ts, channel_id, user_id, message_text,
                    intent_type, urgency, response_text, confidence,
                    needs_clarification, escalated, escalation_reason,
                    docs_cited, reasoning_summary, processing_time,
                    created_at, resolved, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.message_ts,
                record.thread_ts,
                record.channel_id,
                record.user_id,
                record.message_text,
                record.intent_type,
                record.urgency,
                record.response_text,
                record.confidence,
                1 if record.needs_clarification else 0,
                1 if record.escalated else 0,
                record.escalation_reason,
                record.docs_cited,
                record.reasoning_summary,
                record.processing_time,
                record.created_at,
                1 if record.resolved else 0,
                record.resolved_at
            ))
            
            return cursor.lastrowid
    
    def get_user_recent_messages(
        self,
        user_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get user's recent messages."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM conversations
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (user_id, limit))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_thread_messages(
        self,
        thread_ts: str
    ) -> List[Dict[str, Any]]:
        """Get all messages in a thread."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM conversations
                WHERE thread_ts = ? OR message_ts = ?
                ORDER BY created_at ASC
            """, (thread_ts, thread_ts))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def update_user_profile(
        self,
        user_id: str,
        username: str,
        real_name: str,
        email: Optional[str] = None
    ) -> None:
        """Create or update user profile."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Calculate stats
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_messages,
                    SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) as resolved,
                    SUM(CASE WHEN resolved = 0 AND needs_clarification = 0 AND escalated = 0 THEN 1 ELSE 0 END) as unresolved,
                    AVG(CASE WHEN resolved = 1 THEN processing_time ELSE NULL END) as avg_time
                FROM conversations
                WHERE user_id = ?
            """, (user_id,))
            
            stats = dict(cursor.fetchone())
            
            # Get common topics (extract from message text - simplified)
            cursor.execute("""
                SELECT message_text FROM conversations
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 20
            """, (user_id,))
            
            messages = [row["message_text"] for row in cursor.fetchall()]
            # Simple topic extraction (in real implementation, use NLP)
            common_topics = []  # Placeholder
            
            # Determine knowledge level based on interactions
            knowledge_level = "beginner"
            if stats["total_messages"] > 20:
                knowledge_level = "advanced"
            elif stats["total_messages"] > 5:
                knowledge_level = "intermediate"
            
            cursor.execute("""
                INSERT INTO user_profiles (
                    user_id, username, real_name, email, total_messages,
                    common_topics, resolved_issues, unresolved_issues,
                    avg_resolution_time, last_interaction, knowledge_level, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    real_name = excluded.real_name,
                    email = excluded.email,
                    total_messages = excluded.total_messages,
                    common_topics = excluded.common_topics,
                    resolved_issues = excluded.resolved_issues,
                    unresolved_issues = excluded.unresolved_issues,
                    avg_resolution_time = excluded.avg_resolution_time,
                    last_interaction = CURRENT_TIMESTAMP,
                    knowledge_level = excluded.knowledge_level,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                user_id,
                username,
                real_name,
                email,
                stats["total_messages"] or 0,
                json.dumps(common_topics),
                stats["resolved"] or 0,
                stats["unresolved"] or 0,
                stats["avg_time"] or 0.0,
                knowledge_level
            ))
    
    def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        """Get user profile."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM user_profiles WHERE user_id = ?
            """, (user_id,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            row_dict = dict(row)
            return UserProfile(
                user_id=row_dict["user_id"],
                username=row_dict["username"],
                real_name=row_dict["real_name"],
                email=row_dict["email"],
                total_messages=row_dict["total_messages"],
                common_topics=json.loads(row_dict["common_topics"]) if row_dict["common_topics"] else [],
                resolved_issues=row_dict["resolved_issues"],
                unresolved_issues=row_dict["unresolved_issues"],
                avg_resolution_time=row_dict["avg_resolution_time"],
                last_interaction=datetime.fromisoformat(row_dict["last_interaction"]) if row_dict["last_interaction"] else None,
                knowledge_level=row_dict["knowledge_level"]
            )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get agent statistics."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_conversations,
                    SUM(CASE WHEN resolved = 1 THEN 1 ELSE 0 END) as resolved_count,
                    SUM(CASE WHEN escalated = 1 THEN 1 ELSE 0 END) as escalated_count,
                    AVG(confidence) as avg_confidence,
                    AVG(processing_time) as avg_processing_time
                FROM conversations
            """)
            
            stats = dict(cursor.fetchone())
            
            cursor.execute("""
                SELECT COUNT(DISTINCT user_id) as unique_users
                FROM conversations
            """)
            
            stats.update(dict(cursor.fetchone()))
            
            return stats


# Global database instance
_db: Optional[Database] = None


def get_database(db_path: Optional[str] = None) -> Database:
    """Get or create the global database instance."""
    global _db
    if _db is None:
        from agent.config import Config
        _db = Database(db_path=db_path or Config.DATABASE_PATH)
    return _db
