"""Keywords and hashtags configuration for the OLake LinkedIn Marketing Agent.

These are the target terms the feed scanner will search for.
"""

# Tier 1 — High Intent (always engage)
# Posts with these terms are highly likely to be relevant to OLake
TIER_1_KEYWORDS = [
    "Apache Iceberg",
    "Iceberg table format",
    "data lakehouse",
    "Iceberg CDC",
    "database replication Iceberg",
    "EL pipeline",
    "Iceberg ingestion",
]

# Tier 2 — Strong Signal (engage if post is substantive)
# These indicate strong interest in data engineering topics OLake addresses
TIER_2_KEYWORDS = [
    "Change Data Capture",
    "CDC pipeline",
    "data replication",
    "Debezium alternatives",
    "ETL vs ELT",
    "open table format",
    "Parquet lakehouse",
    "Iceberg vs Delta Lake",
    "Hive to Iceberg migration",
]

# Tier 3 — Contextual (engage only if Iceberg/lakehouse mentioned in body)
# General data engineering terms - require additional context checks
TIER_3_KEYWORDS = [
    "data engineering",
    "data lake modernization",
    "real-time analytics",
    "streaming ingestion",
    "PostgreSQL replication",
    "MySQL CDC",
    "MongoDB change streams",
    "Trino",
    "Apache Spark data lake",
]

# Hashtags to monitor
TARGET_HASHTAGS = [
    "#ApacheIceberg",
    "#DataLakehouse",
    "#DataEngineering",
    "#CDC",
    "#DataReplication",
    "#OpenSource",
    "#DataLake",
    "#Iceberg",
]

# Combined search terms for the LinkedIn API
def get_search_keywords() -> list[str]:
    """Get all keywords for searching, prioritized by tier."""
    return TIER_1_KEYWORDS + TIER_2_KEYWORDS + TIER_3_KEYWORDS

def get_all_hashtags() -> list[str]:
    """Get all hashtags for searching."""
    return TARGET_HASHTAGS

def get_tier_for_keyword(keyword: str) -> int:
    """Determine which tier a keyword belongs to.
    
    Returns:
        1, 2, or 3 for the tier, or 0 if not found
    """
    keyword_lower = keyword.lower()
    
    for kw in TIER_1_KEYWORDS:
        if kw.lower() in keyword_lower or keyword_lower in kw.lower():
            return 1
    
    for kw in TIER_2_KEYWORDS:
        if kw.lower() in keyword_lower or keyword_lower in kw.lower():
            return 2
            
    for kw in TIER_3_KEYWORDS:
        if kw.lower() in keyword_lower or keyword_lower in kw.lower():
            return 3
    
    return 0
