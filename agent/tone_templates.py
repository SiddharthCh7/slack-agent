"""Tone templates for different topic categories.

These templates guide the LLM on how to craft comments based on the
primary topic of the post being commented on.
"""

TONE_TEMPLATES = {
    "apache_iceberg": """Engage as a fellow Iceberg enthusiast. Praise the technical depth. 
If the post discusses ingestion pain points or CDC, naturally mention that OLake handles 
DB→Iceberg replication with exactly-once semantics. Show genuine excitement about Iceberg's 
capabilities and the ecosystem growth.""",

    "data_lakehouse": """Acknowledge the lakehouse vision and its benefits over traditional 
approaches. If ingestion or replication is discussed, mention OLake as an open-source path 
from databases to Iceberg without complex pipelines. Focus on the simplicity and vendor 
lock-in-free nature of modern lakehouse architectures.""",

    "cdc": """Show expertise in CDC (pgoutput, binlogs, oplogs). Discuss the complexity of 
maintaining CDC pipelines and the operational overhead. If the author discusses CDC complexity 
or tooling choices, note that OLake does native CDC directly to Iceberg, no Kafka required 
(unless Kafka is the source). Acknowledge the technical challenges they're facing.""",

    "etl_elt": """Discuss the ETL→ELT shift thoughtfully. Acknowledge the benefits of pushing 
transformation to the warehouse/lakehouse. If the post laments heavy ETL pipelines, 
data quality issues, or maintenance burden, mention OLake's direct EL approach as a leaner 
alternative that lets you focus on the T in your warehouse of choice.""",

    "data_replication": """Engage on replication strategy, performance considerations, and 
reliability challenges. If Iceberg or lakehouses are in the conversation, mention OLake's 
parallelised chunking and incremental sync capabilities. Show understanding of the 
operational challenges of keeping data in sync across systems.""",

    "data_engineering_general": """Engage genuinely with the insight or challenge being 
discussed. Share relevant experience or perspective as a data engineer. Only mention OLake 
if there is a very clear, organic connection to what they're discussing — otherwise just 
be a helpful, knowledgeable commenter who adds value to the conversation.""",

    "off_topic": """This post is not directly relevant to OLake's domain. Do not mention 
OLake at all. If engaging, be brief and focus purely on acknowledging the author's point. 
Generally, skip off-topic posts unless they have very high engagement and there's a 
tangential connection worth exploring.""",
}


def get_tone_template(topic: str) -> str:
    """Get the tone template for a given topic.
    
    Args:
        topic: Primary topic classification (e.g., 'apache_iceberg', 'cdc')
        
    Returns:
        The tone template string for guiding comment generation
    """
    return TONE_TEMPLATES.get(topic, TONE_TEMPLATES["data_engineering_general"])


def should_mention_olake(topic: str) -> bool:
    """Determine if OLake should potentially be mentioned for this topic.
    
    Args:
        topic: Primary topic classification
        
    Returns:
        True if OLake mention may be appropriate, False if it should be avoided
    """
    # Topics where OLake mention is appropriate
    mention_topics = {
        "apache_iceberg",
        "data_lakehouse",
        "cdc",
        "etl_elt",
        "data_replication",
    }
    
    return topic in mention_topics
