"""
Main entry point for OLake Slack Community Agent.

HTTP webhook server for Slack Events API.
"""

import argparse
from flask import Flask, request, jsonify
import threading
from typing import Dict, Any

from agent.config import Config
from agent.slack_client import create_slack_client
from agent.graph import get_agent_graph
from agent.state import create_initial_state
from agent.logger import get_logger
from agent.persistence import get_database


app = Flask(__name__)
logger = get_logger(log_dir=Config.LOG_DIR, log_level=Config.LOG_LEVEL)
slack_client = create_slack_client()


@app.route(Config.WEBHOOK_PATH, methods=['POST'])
def slack_events():
    """Handle Slack Events API webhook."""
    try:
        # Get request data
        data = request.get_json()
        
        # Verify signature
        timestamp = request.headers.get('X-Slack-Request-Timestamp', '')
        signature = request.headers.get('X-Slack-Signature', '')
        body = request.get_data(as_text=True)
        
        if not slack_client.verify_signature(timestamp, body, signature):
            logger.logger.warning("Invalid Slack signature")
            return jsonify({"error": "Invalid signature"}), 403
        
        # Handle URL verification challenge
        if data.get('type') == 'url_verification':
            logger.logger.info("Handling URL verification challenge")
            return jsonify({"challenge": data.get('challenge')}), 200
        
        # Handle event callback
        if data.get('type') == 'event_callback':
            event = data.get('event', {})
            event_type = event.get('type')
            
            # Only handle message events
            if event_type == 'message':
                # Ignore bot messages and message changes
                if slack_client.is_bot_message(event) or event.get('subtype'):
                    return jsonify({"ok": True}), 200
                
                # Process message in background thread
                thread = threading.Thread(
                    target=process_message,
                    args=(data,),
                    daemon=True
                )
                thread.start()
                
                return jsonify({"ok": True}), 200
        
        return jsonify({"ok": True}), 200
        
    except Exception as e:
        logger.log_error(
            error_type="WebhookError",
            error_message=str(e),
            stack_trace=str(e)
        )
        return jsonify({"error": str(e)}), 500


def process_message(event_data: Dict[str, Any]) -> None:
    """
    Process a Slack message event through the agent graph.
    
    Args:
        event_data: Slack event data
    """
    try:
        event = event_data.get('event', {})
        
        # Log incoming message
        logger.log_message_received(
            user_id=event.get('user', ''),
            channel_id=event.get('channel', ''),
            text=event.get('text', ''),
            thread_ts=event.get('thread_ts'),
            user_profile=None  # Will be loaded in context_builder
        )
        
        # Add "eyes" reaction to show bot is processing
        slack_client.add_reaction(
            channel=event.get('channel'),
            timestamp=event.get('ts'),
            emoji='eyes'
        )
        
        # Create initial state
        initial_state = create_initial_state(event_data)
        
        # Run through agent graph
        graph = get_agent_graph()
        final_state = graph.invoke(initial_state)
        
        # Remove "eyes" reaction
        slack_client.remove_reaction(
            channel=event.get('channel'),
            timestamp=event.get('ts'),
            emoji='eyes'
        )
        
        logger.logger.info(
            f"Message processed successfully. "
            f"Confidence: {final_state.get('final_confidence', 0):.2f}, "
            f"Escalated: {final_state.get('should_escalate', False)}"
        )
        
    except Exception as e:
        logger.log_error(
            error_type="MessageProcessingError",
            error_message=str(e),
            stack_trace=str(e)
        )


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "agent": "OLake Slack Community Agent",
        "version": "1.0.0"
    }), 200


@app.route('/stats', methods=['GET'])
def get_stats():
    """Get agent statistics."""
    try:
        db = get_database()
        stats = db.get_stats()
        return jsonify(stats), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="OLake Slack Community Agent")
    parser.add_argument(
        '--port',
        type=int,
        default=Config.WEBHOOK_PORT,
        help='Port to run webhook server on'
    )
    parser.add_argument(
        '--validate-config',
        action='store_true',
        help='Validate configuration and exit'
    )
    parser.add_argument(
        '--stats',
        action='store_true',
        help='Show agent statistics and exit'
    )
    
    args = parser.parse_args()
    
    # Validate configuration
    if args.validate_config:
        Config.print_config()
        if Config.validate():
            print("\n✅ Configuration is valid!")
            return 0
        else:
            print("\n❌ Configuration has errors!")
            return 1
    
    # Show stats
    if args.stats:
        db = get_database()
        stats = db.get_stats()
        
        print("\n📊 OLake Slack Agent Statistics")
        print("=" * 50)
        print(f"Total Conversations: {stats.get('total_conversations', 0)}")
        print(f"Resolved: {stats.get('resolved_count', 0)}")
        print(f"Escalated: {stats.get('escalated_count', 0)}")
        print(f"Unique Users: {stats.get('unique_users', 0)}")
        print(f"Avg Confidence: {stats.get('avg_confidence', 0):.2%}")
        print(f"Avg Processing Time: {stats.get('avg_processing_time', 0):.2f}s")
        print("=" * 50 + "\n")
        return 0
    
    # Validate configuration before starting
    if not Config.validate():
        print("\n❌ Configuration validation failed. Please check your .env file.")
        return 1
    
    # Print config
    Config.print_config()
    
    # Initialize database
    get_database()
    
    # Initialize agent graph
    get_agent_graph()
    
    logger.logger.info("=" * 60)
    logger.logger.info("OLake Slack Community Agent Starting")
    logger.logger.info("=" * 60)
    logger.logger.info(f"Webhook URL: http://localhost:{args.port}{Config.WEBHOOK_PATH}")
    logger.logger.info(f"Health Check: http://localhost:{args.port}/health")
    logger.logger.info(f"Stats API: http://localhost:{args.port}/stats")
    logger.logger.info("")
    logger.logger.info("💡 For local development, use ngrok:")
    logger.logger.info(f"   ngrok http {args.port}")
    logger.logger.info("   Then set Request URL in Slack to:")
    logger.logger.info("   https://your-ngrok-url.ngrok.io/slack/events")
    logger.logger.info("=" * 60)
    
    # Run Flask app
    app.run(
        host='0.0.0.0',
        port=args.port,
        debug=False
    )


if __name__ == "__main__":
    exit(main())
