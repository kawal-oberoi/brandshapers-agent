# =====================================================
# BRANDSHAPERS - AGENT 1 (The Brain) v2.0
# Fixed: Always fetches conversions with revenue data
# Fixed: Better keyword detection
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

CHANNEL_AGENT1      = "C0BCQP0P99R"
CHANNEL_ALERTS      = "C0BCV12LJ4E"

supabase: Client    = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
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
            json={"channel": channel, "text": message, "mrkdwn": True},
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
        oldest   = str(time.time() - 120)
        response = requests.get(
            "https://slack.com/api/conversations.history",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
            params={"channel": CHANNEL_AGENT1, "oldest": oldest, "limit": 10},
            timeout=10
        )
        messages = response.json().get("messages", [])
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
# Always fetches conversions — that's where revenue lives
# =====================================================
def fetch_data_for_question(question):
    question_lower = question.lower()
    data           = {}
    today          = datetime.now().strftime("%Y-%m-%d")
    week_ago       = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago      = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    # Determine time range
    if any(w in question_lower for w in ["month", "30 days", "monthly"]):
        start_date = month_ago
        period     = "last 30 days"
    elif any(w in question_lower for w in ["week", "7 days", "weekly"]):
        start_date = week_ago
        period     = "last 7 days"
    else:
        start_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        period     = "yesterday to today"

    data["time_range"] = f"{start_date} to {today} ({period})"

    # ALWAYS fetch campaigns lookup
    campaigns = supabase.table("trackier_campaigns")\
        .select("campaign_id, title, status, model")\
        .execute()
    data["campaigns"] = campaigns.data

    # ALWAYS fetch publishers lookup
    publishers = supabase.table("trackier_publishers")\
        .select("publisher_id, name, email, status")\
        .execute()
    data["publishers"] = publishers.data

    # ALWAYS fetch conversions with revenue — this is core business data
    convs = supabase.table("trackier_conversions")\
        .select("campaign_id, publisher_id, goal_value, revenue, payout, status, created_at")\
        .gte("created_at", start_date)\
        .order("revenue", desc=True)\
        .limit(200)\
        .execute()
    data["conversions"] = convs.data

    # Calculate quick summary for Claude
    total_revenue     = sum(float(c.get("revenue") or 0) for c in convs.data)
    total_payout      = sum(float(c.get("payout") or 0) for c in convs.data)
    total_conversions = len(convs.data)
    campaigns_with_revenue = len([c for c in convs.data if float(c.get("revenue") or 0) > 0])

    data["summary"] = {
        "total_revenue":            total_revenue,
        "total_payout":             total_payout,
        "estimated_profit":         total_revenue - total_payout,
        "total_conversion_records": total_conversions,
        "campaigns_with_revenue":   campaigns_with_revenue
    }

    # Fetch Appflyer data if relevant
    if any(w in question_lower for w in [
        "install", "click", "appflyer", "app", "impression",
        "paybis", "novio", "mobile", "android", "ios"
    ]):
        af_stats = supabase.table("appflyer_stats")\
            .select("app_name, date, installs, clicks, impressions, revenue, media_source")\
            .gte("date", start_date)\
            .execute()
        data["appflyer_stats"] = af_stats.data

    # Fetch sync health if relevant
    if any(w in question_lower for w in ["sync", "status", "health", "working", "agent"]):
        sync = supabase.table("sync_log")\
            .select("sync_type, status, records_synced, created_at")\
            .order("created_at", desc=True)\
            .limit(10)\
            .execute()
        data["sync_log"] = sync.data

    return data


# =====================================================
# CLAUDE AI — ANALYSE AND RESPOND
# =====================================================
def ask_claude(question, data):
    try:
        system_prompt = """You are Agent 1 — a senior data analyst for Brandshapers, 
a digital affiliate marketing company based in Dubai.

You have access to LIVE campaign data from Trackier (affiliate platform) 
and Appflyer (mobile tracking). You are talking to Kawal, the founder.

Your job:
1. Answer questions clearly and concisely
2. Highlight what's working and what's not  
3. Give actionable recommendations
4. Use ₹ for Indian Rupee amounts
5. Use *bold* and bullet points for Slack formatting
6. Be direct — Kawal is a busy founder

Important data notes:
- conversions table contains performance records with revenue/payout
- goal_value field contains the campaign name in performance records
- revenue = what Brandshapers earns, payout = what publishers get
- profit = revenue minus payout

Always lead with the direct answer, then supporting data."""

        user_message = f"""Kawal asked: "{question}"

Live data from database:
{json.dumps(data, indent=2, default=str)[:10000]}

Answer his question directly using this data.
If revenue data exists in conversions, use it to answer revenue questions."""

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
        return "Sorry, I had trouble analysing that. Please try again."

    except Exception as e:
        print(f"❌ Claude API error: {e}")
        return f"Sorry, I encountered an error: {str(e)}"


# =====================================================
# PROCESS A QUESTION
# =====================================================
def process_question(message):
    question = message["text"]
    print(f"\n💬 Question: {question}")

    send_slack(CHANNEL_AGENT1, "🤔 _Analysing your question..._")

    print("   📊 Fetching data...")
    data = fetch_data_for_question(question)
    print(f"   ✅ Got {len(data.get('conversions', []))} conversion records")
    print(f"   💰 Total revenue in data: ₹{data.get('summary', {}).get('total_revenue', 0):,.0f}")

    print("   🧠 Asking Claude AI...")
    answer = ask_claude(question, data)

    final_msg = f"*🤖 Agent 1:*\n\n{answer}\n\n_📅 Data: {data.get('time_range', 'recent')}_"
    send_slack(CHANNEL_AGENT1, final_msg)
    print("   ✅ Answer sent!")


# =====================================================
# MAIN LOOP
# =====================================================
def run():
    print("🤖 Agent 1 v2.0 — The Brain is LIVE")
    print("👂 Listening to #brandshapers-agent1...")

    send_slack(CHANNEL_AGENT1,
        "🧠 *Agent 1 v2.0 — Ready with live revenue data!*\n\n"
        "I now have access to your campaign performance data. Try:\n"
        "• _Which campaigns made money yesterday?_\n"
        "• _Show me top 10 campaigns by revenue_\n"
        "• _Who are my best publishers?_\n"
        "• _What is my total revenue this week?_"
    )

    while True:
        try:
            new_messages = get_new_messages()
            for message in new_messages:
                process_question(message)
        except Exception as e:
            print(f"❌ Loop error: {e}")
        time.sleep(10)


if __name__ == "__main__":
    run()
