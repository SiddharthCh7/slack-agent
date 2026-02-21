"""
Main entry point for OLake Slack Community Agent.

HTTP webhook server for Slack Events API.

Startup sequence:
  1. Validate configuration
  2. auth.test → cache bot's own user ID
  3. users.list → build slack_name → user_id cache for the OLake team
  4. Load olake-team.json
  5. Initialize DB and agent graph
  6. Start Flask webhook server
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
from agent.team_resolver import (
    load_team,
    build_name_to_id_cache,
    set_bot_user_id,
    is_org_member_by_id,
    is_org_member_by_name,
)


app = Flask(__name__)
logger = get_logger(log_dir=Config.LOG_DIR, log_level=Config.LOG_LEVEL)
slack_client = create_slack_client()


# ---------------------------------------------------------------------------
# Startup initialization
# ---------------------------------------------------------------------------

def initialize_team_resolver() -> None:
    """
    At startup:
      1. Call auth.test to get the bot's own Slack user ID.
      2. Call users.list to build a slack_name → user_id cache for OLake team members.
      3. Load olake-team.json.

    This ensures:
      - Thread messages can be labelled [BOT] / [USER] correctly.
      - Escalation @mentions use proper <@USERID> format (reliable pings).
      - Org-member detection works by ID (fallback: display-name).
    """
    try:
        # 1. Bot identity
        bot_info = slack_client.client.auth_test()
        bot_user_id = bot_info.get("user_id") or bot_info.get("user")
        if bot_user_id:
            set_bot_user_id(bot_user_id)
        else:
            logger.logger.warning("Could not fetch bot user ID from auth.test")

        # 2. Team data
        load_team()

        # 3. Build slack_name → user_id cache
        #    Slack paginates users.list; fetch all pages.
        all_users = []
        cursor = None
        while True:
            kwargs = {"limit": 200}
            if cursor:
                kwargs["cursor"] = cursor
            resp = slack_client.client.users_list(**kwargs)
            members = resp.get("members", [])
            all_users.extend(members)
            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        build_name_to_id_cache(all_users)
        logger.logger.info("Team resolver initialized successfully.")

    except Exception as e:
        logger.logger.error(f"Team resolver initialization failed: {e}. Org-member features will use name-matching fallback.")


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

@app.route(Config.WEBHOOK_PATH, methods=['POST'])
def slack_events():
    """Handle Slack Events API webhook."""
    try:
        data = request.get_json()

        timestamp = request.headers.get('X-Slack-Request-Timestamp', '')
        signature = request.headers.get('X-Slack-Signature', '')
        body = request.get_data(as_text=True)

        if not slack_client.verify_signature(timestamp, body, signature):
            logger.logger.warning("Invalid Slack signature")
            return jsonify({"error": "Invalid signature"}), 403

        # URL verification challenge
        if data.get('type') == 'url_verification':
            logger.logger.info("Handling URL verification challenge")
            return jsonify({"challenge": data.get('challenge')}), 200

        # Event callback
        if data.get('type') == 'event_callback':
            event = data.get('event', {})
            event_type = event.get('type')

            if event_type == 'message':
                # Ignore bot messages and edits/deletes
                if slack_client.is_bot_message(event) or event.get('subtype'):
                    return jsonify({"ok": True}), 200

                # --- Early org-member guard ---
                # If the sender is an OLake team member, skip processing entirely.
                # (Thread-level detection happens inside context_builder, but this
                #  covers stand-alone messages from team members too.)
                sender_id = event.get('user', '')
                if sender_id and is_org_member_by_id(sender_id):
                    logger.logger.info(
                        f"Skipping message from org member user_id={sender_id}"
                    )
                    return jsonify({"ok": True}), 200

                # Process in background thread
                thread = threading.Thread(
                    target=process_message,
                    args=(data,),
                    daemon=True,
                )
                thread.start()

        return jsonify({"ok": True}), 200

    except Exception as e:
        logger.log_error(
            error_type="WebhookError",
            error_message=str(e),
            stack_trace=str(e),
        )
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Message processing
# ---------------------------------------------------------------------------

def process_message(event_data: Dict[str, Any]) -> None:
    """
    Process a Slack message event through the agent graph.

    Args:
        event_data: Slack event data
    """
    try:
        event = event_data.get('event', {})

        logger.log_message_received(
            user_id=event.get('user', ''),
            channel_id=event.get('channel', ''),
            text=event.get('text', ''),
            thread_ts=event.get('thread_ts'),
            user_profile=None,
        )

        # Show "eyes" reaction while processing
        slack_client.add_reaction(
            channel=event.get('channel'),
            timestamp=event.get('ts'),
            emoji='eyes',
        )

        initial_state = create_initial_state(event_data)
        graph = get_agent_graph()
        final_state = graph.invoke(initial_state)

        # Remove "eyes" reaction when done
        slack_client.remove_reaction(
            channel=event.get('channel'),
            timestamp=event.get('ts'),
            emoji='eyes',
        )

        logger.logger.info(
            f"Message processed. "
            f"Confidence: {final_state.get('final_confidence', 0):.2f}, "
            f"Escalated: {final_state.get('should_escalate', False)}, "
            f"OrgMemberSilenced: {final_state.get('org_member_replied', False)}"
        )

    except Exception as e:
        logger.log_error(
            error_type="MessageProcessingError",
            error_message=str(e),
            stack_trace=str(e),
        )


# ---------------------------------------------------------------------------
# Utility endpoints
# ---------------------------------------------------------------------------

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "agent": "OLake Slack Community Agent",
        "version": "1.0.0",
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="OLake Slack Community Agent")
    parser.add_argument('--port', type=int, default=Config.WEBHOOK_PORT)
    parser.add_argument('--validate-config', action='store_true')
    parser.add_argument('--stats', action='store_true')
    args = parser.parse_args()

    if args.validate_config:
        Config.print_config()
        return 0 if Config.validate() else 1

    if args.stats:
        db = get_database()
        stats = db.get_stats()
        print("\n📊 OLake Slack Agent Statistics")
        print("=" * 50)
        for k, v in stats.items():
            print(f"{k}: {v}")
        print("=" * 50 + "\n")
        return 0

    if not Config.validate():
        print("\n❌ Configuration validation failed. Please check your .env file.")
        return 1

    Config.print_config()

    # Initialize DB and agent graph
    get_database()
    get_agent_graph()

    # Initialize team resolver (bot user ID + slack_name→ID cache)
    initialize_team_resolver()

    logger.logger.info("=" * 60)
    logger.logger.info("OLake Slack Community Agent Starting")
    logger.logger.info("=" * 60)
    logger.logger.info(f"Webhook: http://localhost:{args.port}{Config.WEBHOOK_PATH}")
    logger.logger.info(f"Health:  http://localhost:{args.port}/health")
    logger.logger.info(f"Stats:   http://localhost:{args.port}/stats")
    logger.logger.info("=" * 60)

    app.run(host='0.0.0.0', port=args.port, debug=False)


if __name__ == "__main__":
    exit(main())
