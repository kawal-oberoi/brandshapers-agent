# =====================================================
# BRANDSHAPERS - AGENT 1 (The Brain) v3.1
# Fixed: IST timezone throughout
# Fixed: "today" keyword now properly detected (was defaulting to 2-day range)
# Fixed: conversions now summed from actual `conversions` field (was counting rows)
# =====================================================

import os, json, time, requests
import pytz
from datetime import datetime, timedelta
from supabase import create_client, Client

SUPABASE_URL        = os.environ.get("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY")
SLACK_BOT_TOKEN     = os.environ.get("SLACK_BOT_TOKEN")
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY")
CHANNEL_AGENT1      = "C0BCQP0P99R"
CHANNEL_ALERTS      = "C0BCV12LJ4E"

IST                = pytz.timezone("Asia/Kolkata")
supabase: Client   = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
processed_messages = set()

def now_ist():
    return datetime.now(IST)

def send_slack(channel, message):
    try:
        r = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
            json={"channel": channel, "text": message, "mrkdwn": True}, timeout=10)
        return r.json().get("ok", False)
    except Exception as e:
        print(f"Slack error: {e}")
        return False

def get_new_messages():
    try:
        r = requests.get(
            "https://slack.com/api/conversations.history",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
            params={"channel": CHANNEL_AGENT1, "oldest": str(time.time() - 120), "limit": 10}, timeout=10)
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
    today = now_ist().strftime("%Y-%m-%d")

    # FIX: "today" keyword was missing entirely before — it fell through to the
    # default `days = 2`, which pulled in yesterday's (and the day before's) data
    # and presented it as "today". Now explicitly handled with days = 0.
    if "today" in q:
        days = 0
    elif "month" in q:
        days = 30
    elif "week" in q:
        days = 7
    else:
        days = 2

    start = (now_ist() - timedelta(days=days)).strftime("%Y-%m-%d")

    camps = supabase.table("trackier_campaigns").select("campaign_id, title, status").execute()
    pubs  = supabase.table("trackier_publishers").select("publisher_id, name, email, status").execute()
    camp_lookup = {c["campaign_id"]: c["title"] for c in camps.data}

    # FIX: added `conversions` to the select — it was never being fetched, so the
    # code below had no choice but to count rows instead of actual approved conversions.
    convs = supabase.table("trackier_conversions")\
        .select("campaign_id, publisher_id, goal_value, revenue, payout, conversions, status, created_at")\
        .gte("created_at", start).order("revenue", desc=True).limit(500).execute()

    by_camp = {}
    for c in convs.data:
        cid        = c.get("campaign_id", "")
        name       = camp_lookup.get(cid) or c.get("goal_value") or f"Campaign {cid}"
        rev        = float(c.get("revenue") or 0)
        pay        = float(c.get("payout") or 0)
        # FIX: sum the actual `conversions` field from Trackier, not `+= 1` per row.
        # Previously this counted "number of matching rows" as the conversion count,
        # which silently diverged from the real approved-conversions number.
        conv_count = int(c.get("conversions") or 0)
        if name not in by_camp:
            by_camp[name] = {"revenue": 0, "payout": 0, "profit": 0, "conversions": 0}
        by_camp[name]["revenue"]     += rev
        by_camp[name]["payout"]      += pay
        by_camp[name]["profit"]      += rev - pay
        by_camp[name]["conversions"] += conv_count

    top       = sorted(by_camp.items(), key=lambda x: x[1]["revenue"], reverse=True)
    total_rev = sum(v["revenue"] for v in by_camp.values())
    total_pay = sum(v["payout"] for v in by_camp.values())

    by_pub = {}
    for c in convs.data:
        pid        = c.get("publisher_id", "")
        pname      = next((p["name"] for p in pubs.data if p["publisher_id"] == pid), f"Publisher {pid}")
        rev        = float(c.get("revenue") or 0)
        conv_count = int(c.get("conversions") or 0)  # FIX: same row-count bug fixed here too
        if pname not in by_pub:
            by_pub[pname] = {"revenue": 0, "conversions": 0}
        by_pub[pname]["revenue"]     += rev
        by_pub[pname]["conversions"] += conv_count
    top_pubs = sorted(by_pub.items(), key=lambda x: x[1]["revenue"], reverse=True)

    af_data = []
    if any(w in q for w in ["install", "click", "app", "appflyer", "paybis", "novio"]):
        af      = supabase.table("appflyer_stats").select("*").gte("date", start).execute()
        af_data = af.data

    return {
        "time_range":     f"{start} to {today} IST",
        "total_revenue":  total_rev,
        "total_payout":   total_pay,
        "total_profit":   total_rev - total_pay,
        "total_records":  len(convs.data),
        "with_revenue":   len([c for c in convs.data if float(c.get("revenue") or 0) > 0]),
        "top_campaigns":  [{"name": k, **v} for k, v in top[:20]],
        "top_publishers": [{"name": k, **v} for k, v in top_pubs[:10]],
        "appflyer":       af_data
    }

def ask_claude(question, data):
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            json={
                "model": "claude-sonnet-4-6", "max_tokens": 1024,
                "system": """You are Agent 1, senior data analyst for Brandshapers Dubai affiliate company.
Talk to Kawal the founder. Be direct. Use rupee symbol.
Use *bold* and bullets for Slack. Data has top_campaigns with revenue/payout/profit.
All dates and times are in IST (India Standard Time).
ALWAYS give actual numbers from top_campaigns.""",
                "messages": [{"role": "user", "content": f'Kawal asked: "{question}"\n\nData (all times IST):\n{json.dumps(data, indent=2, default=str)[:12000]}\n\nAnswer with actual numbers.'}]
            }, timeout=30)
        result = r.json()
        return result["content"][0]["text"] if result.get("content") else "Error getting response."
    except Exception as e:
        return f"Error: {e}"

def process(msg):
    q = msg["text"]
    print(f"\n💬 {q}")
    send_slack(CHANNEL_AGENT1, "🤔 _Analysing..._")
    data   = fetch_data(q)
    print(f"   💰 Revenue: ₹{data['total_revenue']:,.0f} | Records: {data['total_records']}")
    answer = ask_claude(q, data)
    send_slack(CHANNEL_AGENT1, f"*🤖 Agent 1:*\n\n{answer}\n\n_📅 {data['time_range']}_")
    print("   ✅ Sent!")

def run():
    print("🤖 Agent 1 v3.1 IST — LIVE")
    send_slack(CHANNEL_AGENT1,
        "🧠 *Agent 1 v3.1 — 'today' fix + accurate conversion counts!*\n\n"
        "All data and dates are now in India Standard Time (IST) ✅\n"
        "Ask me anything about your campaigns!"
    )
    while True:
        try:
            for m in get_new_messages():
                process(m)
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(10)

if __name__ == "__main__":
    run()
