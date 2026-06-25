import os, json, time, requests
from datetime import datetime, timedelta
from supabase import create_client, Client

SUPABASE_URL        = os.environ.get("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY")
SLACK_BOT_TOKEN     = os.environ.get("SLACK_BOT_TOKEN")
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY")
CHANNEL_AGENT1      = "C0BCQP0P99R"
CHANNEL_ALERTS      = "C0BCV12LJ4E"

supabase: Client   = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
processed_messages = set()

def send_slack(channel, message):
    try:
        r = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
            json={"channel": channel, "text": message, "mrkdwn": True},
            timeout=10
        )
        return r.json().get("ok", False)
    except Exception as e:
        print(f"Slack error: {e}")
        return False

def get_new_messages():
    try:
        r = requests.get(
            "https://slack.com/api/conversations.history",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
            params={"channel": CHANNEL_AGENT1, "oldest": str(time.time() - 120), "limit": 10},
            timeout=10
        )
        msgs = r.json().get("messages", [])
        new  = []
        for m in msgs:
            mid  = m.get("ts")
            text = m.get("text", "")
            bot  = m.get("bot_id") or m.get("subtype") == "bot_message"
            if not bot and mid not in processed_messages and text:
                new.append({"id": mid, "text": text})
                processed_messages.add(mid)
        return new
    except Exception as e:
        print(f"Read error: {e}")
        return []

def fetch_data(question):
    q     = question.lower()
    today = datetime.now().strftime("%Y-%m-%d")
    days  = 30 if "month" in q else 7 if "week" in q else 2
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # Step 1: Get campaign name lookup
    camps = supabase.table("trackier_campaigns").select("campaign_id, title, status").execute()
    camp_lookup = {c["campaign_id"]: c["title"] for c in camps.data}

    # Step 2: Get publishers
    pubs = supabase.table("trackier_publishers").select("publisher_id, name, email, status").execute()

    # Step 3: Get ALL conversions with revenue - this is the core data
    convs = supabase.table("trackier_conversions")\
        .select("campaign_id, publisher_id, goal_value, revenue, payout, status, created_at")\
        .gte("created_at", start)\
        .order("revenue", desc=True)\
        .limit(500)\
        .execute()

    # Step 4: Group by campaign and calculate totals
    by_camp = {}
    for c in convs.data:
        cid  = c.get("campaign_id", "")
        # Use campaign title from lookup, fallback to goal_value, fallback to ID
        name = camp_lookup.get(cid) or c.get("goal_value") or f"Campaign {cid}"
        rev  = float(c.get("revenue") or 0)
        pay  = float(c.get("payout") or 0)
        if name not in by_camp:
            by_camp[name] = {"revenue": 0, "payout": 0, "profit": 0, "conversions": 0}
        by_camp[name]["revenue"]     += rev
        by_camp[name]["payout"]      += pay
        by_camp[name]["profit"]      += rev - pay
        by_camp[name]["conversions"] += 1

    # Step 5: Sort by revenue
    top = sorted(by_camp.items(), key=lambda x: x[1]["revenue"], reverse=True)
    total_rev = sum(v["revenue"] for v in by_camp.values())
    total_pay = sum(v["payout"] for v in by_camp.values())

    # Step 6: Group by publisher
    by_pub = {}
    for c in convs.data:
        pid  = c.get("publisher_id", "")
        pname = next((p["name"] for p in pubs.data if p["publisher_id"] == pid), f"Publisher {pid}")
        rev  = float(c.get("revenue") or 0)
        if pname not in by_pub:
            by_pub[pname] = {"revenue": 0, "conversions": 0}
        by_pub[pname]["revenue"]     += rev
        by_pub[pname]["conversions"] += 1
    top_pubs = sorted(by_pub.items(), key=lambda x: x[1]["revenue"], reverse=True)

    # Appflyer if relevant
    af_data = []
    if any(w in q for w in ["install", "click", "app", "appflyer", "paybis", "novio"]):
        af = supabase.table("appflyer_stats").select("*").gte("date", start).execute()
        af_data = af.data

    return {
        "time_range":       f"{start} to {today}",
        "total_revenue":    total_rev,
        "total_payout":     total_pay,
        "total_profit":     total_rev - total_pay,
        "total_records":    len(convs.data),
        "with_revenue":     len([c for c in convs.data if float(c.get("revenue") or 0) > 0]),
        "top_campaigns":    [{"name": k, **v} for k, v in top[:20]],
        "top_publishers":   [{"name": k, **v} for k, v in top_pubs[:10]],
        "appflyer":         af_data
    }

def ask_claude(question, data):
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 1024,
                "system": """You are Agent 1, senior data analyst for Brandshapers, 
a Dubai affiliate marketing company. You speak directly to Kawal, the founder.

CRITICAL RULES:
- The data ALWAYS contains top_campaigns with revenue figures
- ALWAYS lead with actual numbers from top_campaigns
- NEVER say data is missing — it is all in top_campaigns field
- Use rupee symbol for INR amounts
- Use *bold* and bullet points for Slack formatting
- Be direct and concise — Kawal is a busy founder
- total_revenue, total_payout, total_profit are pre-calculated for you""",
                "messages": [{
                    "role": "user",
                    "content": f'Kawal asked: "{question}"\n\nHere is the complete data:\n{json.dumps(data, indent=2, default=str)[:12000]}\n\nAnswer directly with actual numbers from top_campaigns.'
                }]
            },
            timeout=30
        )
        result = r.json()
        if result.get("content"):
            return result["content"][0]["text"]
        print(f"Claude error: {result}")
        return "Sorry, I had trouble with that. Please try again."
    except Exception as e:
        print(f"Claude API error: {e}")
        return f"Error: {e}"

def process(msg):
    q = msg["text"]
    print(f"\n💬 Question: {q}")
    send_slack(CHANNEL_AGENT1, "🤔 _Analysing..._")
    data = fetch_data(q)
    print(f"   ✅ Revenue: ₹{data['total_revenue']:,.0f} | Campaigns: {len(data['top_campaigns'])} | Records: {data['total_records']}")
    answer = ask_claude(q, data)
    send_slack(CHANNEL_AGENT1, f"*🤖 Agent 1:*\n\n{answer}\n\n_📅 {data['time_range']}_")
    print("   ✅ Answer sent to Slack!")

def run():
    print("🤖 Agent 1 FINAL — The Brain is LIVE")
    print("👂 Listening to #brandshapers-agent1...")
    send_slack(CHANNEL_AGENT1,
        "🧠 *Agent 1 FINAL — Ready with live data!*\n\n"
        "Ask me anything:\n"
        "• _What is my total revenue?_\n"
        "• _Show top 5 campaigns by revenue_\n"
        "• _Who are my best publishers?_\n"
        "• _How did Make Money GB perform this week?_"
    )
    while True:
        try:
            for m in get_new_messages():
                process(m)
        except Exception as e:
            print(f"Loop error: {e}")
        time.sleep(10)

if __name__ == "__main__":
    run()
