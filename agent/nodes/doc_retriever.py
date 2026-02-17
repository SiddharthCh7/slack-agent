"""
Documentation Retriever Node - Searches OLake documentation for relevant information.
"""

from typing import Dict, Any, List
import re

from agent.state import ConversationState, RetrievedDocument
from agent.config import Config, load_olake_docs
from agent.logger import get_logger, EventType


def doc_retriever(state: ConversationState) -> ConversationState:
    """
    Retrieve relevant documentation based on user's message and topics.
    
    Args:
        state: Current conversation state
        
    Returns:
        Updated state with retrieved documents
    """
    logger = get_logger()
    
    user_id = state["user_id"]
    channel_id = state["channel_id"]
    message_text = state["message_text"]
    key_topics = state.get("key_topics", [])
    technical_terms = state.get("technical_terms", [])
    
    try:
        # Build search queries from message and topics
        search_queries = []
        
        # Use the message text
        search_queries.append(message_text)
        
        # Use key topics
        for topic in key_topics:
            search_queries.append(topic)
        
        # Use technical terms
        for term in technical_terms:
            search_queries.append(term)
        
        state["search_queries"] = search_queries
        
        # Load documentation
        docs_content = load_olake_docs()
        
        # Simple keyword-based search (for now - can be replaced with vector search)
        retrieved_docs = []
        
        # Split docs into sections
        doc_sections = _split_documentation(docs_content)
        
        # Score each section based on query relevance
        for section in doc_sections:
            relevance_score = _calculate_relevance(
                section["content"],
                search_queries
            )
            
            if relevance_score >= Config.DOC_RELEVANCE_THRESHOLD:
                retrieved_docs.append(
                    RetrievedDocument(
                        title=section["title"],
                        content=section["content"],
                        url=section.get("url", "https://olake.io/docs/"),
                        relevance_score=relevance_score,
                        source_type="docs"
                    )
                )
        
        # Sort by relevance and limit
        retrieved_docs.sort(key=lambda x: x.relevance_score, reverse=True)
        retrieved_docs = retrieved_docs[:Config.MAX_RETRIEVED_DOCS]
        
        state["retrieved_docs"] = retrieved_docs
        state["docs_relevance_score"] = (
            sum(doc.relevance_score for doc in retrieved_docs) / len(retrieved_docs)
            if retrieved_docs else 0.0
        )
        
        # Log documentation search
        logger.log_docs_searched(
            query=message_text,
            num_results=len(retrieved_docs),
            top_results=[
                {"title": doc.title, "relevance": doc.relevance_score}
                for doc in retrieved_docs[:3]
            ],
            user_id=user_id,
            channel_id=channel_id
        )
        
    except Exception as e:
        logger.log_error(
            error_type="DocRetrievalError",
            error_message=str(e),
            user_id=user_id,
            channel_id=channel_id
        )
        
        # Fallback to empty results
        state["retrieved_docs"] = []
        state["docs_relevance_score"] = 0.0
        state["search_queries"] = []
    
    return state


def _split_documentation(docs_content: str) -> List[Dict[str, str]]:
    """Split documentation into sections."""
    sections = []
    
    # Split by headers
    lines = docs_content.split('\n')
    current_section = {"title": "Introduction", "content": ""}
    
    for line in lines:
        # Check for markdown headers
        if line.startswith('# '):
            if current_section["content"].strip():
                sections.append(current_section)
            current_section = {
                "title": line.replace('#', '').strip(),
                "content": ""
            }
        elif line.startswith('## '):
            if current_section["content"].strip():
                sections.append(current_section)
            current_section = {
                "title": line.replace('#', '').strip(),
                "content": ""
            }
        else:
            current_section["content"] += line + "\n"
    
    # Add last section
    if current_section["content"].strip():
        sections.append(current_section)
    
    return sections


def _calculate_relevance(content: str, queries: List[str]) -> float:
    """
    Calculate relevance score between content and search queries.
    
    This is a simple keyword-based approach. For production, use:
    - Vector embeddings (sentence-transformers)
    - BM25 ranking
    - Semantic search
    """
    content_lower = content.lower()
    total_score = 0.0
    
    for query in queries:
        query_lower = query.lower()
        query_terms = re.findall(r'\w+', query_lower)
        
        # Count keyword matches
        matches = sum(1 for term in query_terms if term in content_lower)
        
        # Score based on match ratio
        if query_terms:
            score = matches / len(query_terms)
            total_score += score
    
    # Normalize by number of queries
    return total_score / len(queries) if queries else 0.0
