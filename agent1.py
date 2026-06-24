# =====================================================
# BRANDSHAPERS - AGENT 1 (The Brain)
# - Listens to Slack channel #brandshapers-agent1
# - Understands plain English questions
# - Queries Supabase for relevant data
# - Uses Claude AI to analyse and respond
# - Replies back on Slack in plain English
# =====================================================

import os
import json
import time
import requests
from datetime import datetime, timedelta
from supabase import create_client, Client

# =====================================================
# CONFIGURATION
# =====================================================
SUPABASE_URL        = os.environ.get("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY")
SLACK_BOT_TOKEN     = os.environ.get("SLACK_BOT_TOKEN")
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY")

# Slack Channels
CHANNEL_AGENT1      = "C0BCQP0P99R"   # brandshapers-agent1
CHANNEL_ALERTS      = "C0BCV12LJ4E"   # brandshapers-alerts

supabase: Client    = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)

# Track processed messages to avoid duplicates
processed_messages  = set()


# =====================================================
# SLACK — SEND MESSAGE
# =====================================================
def send_slack(channel, message):
    try:
        response = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={
                "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                "Content-Type":  "application/json"
            },
            json={
                "channel": channel,
                "text":    message,
                "mrkdwn":  True
            },
            timeout=10
        )
        return response.json().get("ok", False)
    except Exception as e:
        print(f"❌ Slack error: {e}")
        return False


# =====================================================
# SLACK — READ NEW MESSAGES
# =====================================================
def get_new_messages():
    try:
        # Get messages from last 2 minutes
        oldest = str(time.time() - 120)
        response = requests.get(
            "https://slack.com/api/conversations.history",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
            params={
                "channel": CHANNEL_AGENT1,
                "oldest":  oldest,
                "limit":   10
            },
            timeout=10
        )
        data     = response.json()
        messages = data.get("messages", [])

        # Filter out bot messages and already processed
        new_msgs = []
        for msg in messages:
            msg_id   = msg.get("ts")
            msg_text = msg.get("text", "")
            is_bot   = msg.get("bot_id") or msg.get("subtype") == "bot_message"

            if not is_bot and msg_id not in processed_messages and msg_text:
                new_msgs.append({"id": msg_id, "text": msg_text})
                processed_messages.add(msg_id)

        return new_msgs

    except Exception as e:
        print(f"❌ Slack read error: {e}")
        return []


# =====================================================
# DATABASE — FETCH ALL RELEVANT DATA
# Based on the question, pull the right data
# =====================================================
def fetch_data_for_question(question):
    """
    Intelligently fetches the right data from Supabase
    based on what the user is asking about
    """
    question_lower = question.lower()
    data           = {}
    today          = datetime.now().strftime("%Y-%m-%d")
    yesterday      = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    week_ago       = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago      = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    # Determine time range from question
    if any(w in question_lower for w in ["today", "24 hours", "24hrs"]):
        start_date = today
    elif any(w in question_lower for w in ["week", "7 days", "weekly"]):
        start_date = week_ago
    elif any(w in question_lower for w in ["month", "30 days", "monthly"]):
        start_date = month_ago
    else:
        start_date = yesterday  # Default: yesterday to today

    # Always fetch campaign and publisher lookup tables
    campaigns  = supabase.table("trackier_campaigns")\
        .select("campaign_id, title, status, model")\
        .execute()
    publishers = supabase.table("trackier_publishers")\
        .select("publisher_id, name, email, status")\
        .execute()

    data["campaigns"]  = campaigns.data
    data["publishers"] = publishers.data
    data["time_range"] = f"{start_date} to {today}"

    # Fetch conversions if relevant
    if any(w in question_lower for w in [
        "revenue", "conversion", "earning", "payout", "money",
        "perform", "top", "best", "worst", "bottom", "campaign",
        "publisher", "profit", "compare", "week", "month", "today"
    ]):
        convs = supabase.table("trackier_conversions")\
            .select("campaign_id, publisher_id, revenue, payout, status, created_at")\
            .gte("created_at", start_date)\
            .execute()
        data["conversions"] = convs.data

    # Fetch Appflyer data if relevant
    if any(w in question_lower for w in [
        "install", "click", "appflyer", "app", "impression",
        "paybis", "novio", "stablmoney", "mobile", "android", "ios"
    ]):
        af_stats = supabase.table("appflyer_stats")\
            .select("app_name, date, installs, clicks, impressions, revenue, media_source, campaign")\
            .gte("date", start_date)\
            .execute()
        data["appflyer_stats"] = af_stats.data

        af_apps = supabase.table("appflyer_apps")\
            .select("app_id, app_name, platform")\
            .execute()
        data["appflyer_apps"] = af_apps.data

    # Fetch sync health if relevant
    if any(w in question_lower for w in [
        "sync", "status", "agent", "working", "health", "last update"
    ]):
        sync = supabase.table("sync_log")\
            .select("sync_type, status, records_synced, created_at")\
            .order("created_at", desc=True)\
            .limit(20)\
            .execute()
        data["sync_log"] = sync.data

    return data


# =====================================================
# CLAUDE AI — ANALYSE DATA AND GENERATE RESPONSE
# =====================================================
def ask_claude(question, data):
    """
    Sends the question + data to Claude AI
    Gets back a plain English analysis
    """
    try:
        # Build a rich context for Claude
        system_prompt = """You are Agent 1 — a senior data analyst for Brandshapers, 
a digital affiliate marketing company based in Dubai. 

You have access to live campaign data from Trackier (affiliate platform) 
and Appflyer (mobile tracking). You are talking directly to Kawal, 
the founder and Operations Head of Brandshapers.

Your job is to:
1. Answer his questions clearly and concisely
2. Highlight what's working and what's not
3. Give actionable recommendations where relevant
4. Use Indian Rupee (₹) for currency
5. Keep responses focused — no fluff
6. Use Slack formatting: *bold*, bullet points with •
7. If data is insufficient, say so honestly and explain why

You are NOT just a chatbot. You are a business intelligence analyst 
who understands affiliate marketing deeply."""

        user_message = f"""Kawal asked: "{question}"

Here is the live data from the database:
{json.dumps(data, indent=2, default=str)[:8000]}

Please analyse this data and answer Kawal's question clearly.
Focus on what matters most to him as a business owner.
Keep your response concise but complete."""

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type":      "application/json"
            },
            json={
                "model":      "claude-sonnet-4-6",
                "max_tokens": 1024,
                "system":     system_prompt,
                "messages":   [{"role": "user", "content": user_message}]
            },
            timeout=30
        )

        result = response.json()

        if result.get("content"):
            return result["content"][0]["text"]
        else:
            print(f"❌ Claude error: {result}")
            return "Sorry, I had trouble analysing that. Please try again."

    except Exception as e:
        print(f"❌ Claude API error: {e}")
        return f"Sorry, I encountered an error: {str(e)}"


# =====================================================
# MAIN — PROCESS A QUESTION FROM SLACK
# =====================================================
def process_question(message):
    question = message["text"]
    print(f"\n💬 New question: {question}")

    # Send typing indicator
    send_slack(CHANNEL_AGENT1, f"🤔 _Analysing your question..._")

    # Fetch relevant data
    print("   📊 Fetching data from database...")
    data = fetch_data_for_question(question)

    # Ask Claude to analyse
    print("   🧠 Asking Claude AI...")
    answer = ask_claude(question, data)

    # Send answer back to Slack
    final_msg = f"*🤖 Agent 1 Response:*\n\n{answer}\n\n_Data range: {data.get('time_range', 'recent')}_"
    send_slack(CHANNEL_AGENT1, final_msg)
    print("   ✅ Answer sent to Slack")


# =====================================================
# MAIN LOOP — POLL SLACK EVERY 10 SECONDS
# =====================================================
def run():
    print("🤖 Agent 1 — The Brain is LIVE")
    print("👂 Listening to #brandshapers-agent1...")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Send startup message
    send_slack(CHANNEL_AGENT1,
        "🧠 *Agent 1 — The Brain is now LIVE*\n\n"
        "I'm ready to answer your questions about campaign performance, "
        "publisher stats, revenue, and more.\n\n"
        "*Try asking me:*\n"
        "• _Which campaigns made money yesterday?_\n"
        "• _Who are my top publishers this week?_\n"
        "• _How many installs did we get today?_\n"
        "• _Which campaigns should I pause?_\n\n"
        "Just type your question here and I'll respond in seconds! 💬"
    )

    # Poll Slack every 10 seconds for new messages
    while True:
        try:
            new_messages = get_new_messages()
            for message in new_messages:
                process_question(message)
        except Exception as e:
            print(f"❌ Loop error: {e}")

        time.sleep(10)


# =====================================================
# ENTRY POINT
# =====================================================
if __name__ == "__main__":
    run()
