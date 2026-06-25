# =====================================================
# BRANDSHAPERS - AGENT 3 (The Analyst) v2.0
# Fixed: IST timezone throughout
# =====================================================

import os
import json
import time
import schedule
import requests
from datetime import datetime, timedelta
import pytz
from supabase import create_client, Client

SUPABASE_URL    = os.environ.get("SUPABASE_URL")
SUPABASE_SECRET = os.environ.get("SUPABASE_SECRET_KEY")
SLACK_TOKEN     = os.environ.get("SLACK_BOT_TOKEN")
CHANNEL_DAILY   = "C0BCV0XH830"
CHANNEL_ALERTS  = "C0BCV12LJ4E"
CHANNEL_AGENT1  = "C0BCQP0P99R"

IST      = pytz.timezone("Asia/Kolkata")
supabase = create_client(SUPABASE_URL, SUPABASE_SECRET)

def now_ist():
    return datetime.now(IST)

def today_ist():
    return now_ist().strftime("%Y-%m-%d")

def yesterday_ist():
    return (now_ist() - timedelta(days=1)).strftime("%Y-%m-%d")

def send_slack(channel, message):
    try:
        r = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_TOKEN}", "Content-Type": "application/json"},
            json={"channel": channel, "text": message, "mrkdwn": True},
            timeout=10
        )
        return r.json().get("ok", False)
    except:
        return False

def get_summary():
    yest = yesterday_ist()
    r    = supabase.table("trackier_conversions").select("revenue, payout, status").gte("created_at", yest).execute()
    total_rev  = sum(float(c.get("revenue") or 0) for c in r.data)
    total_pay  = sum(float(c.get("payout") or 0) for c in r.data)
    total_conv = len(r.data)
    approved   = sum(1 for c in r.data if c.get("status") == "approved")
    return {"total_revenue": total_rev, "total_payout": total_pay,
            "profit": total_rev - total_pay, "total_conversions": total_conv, "approved": approved}

def get_top_campaigns():
    yest  = yesterday_ist()
    convs = supabase.table("trackier_conversions").select("campaign_id, goal_value, revenue, payout").gte("created_at", yest).execute()
    camps = supabase.table("trackier_campaigns").select("campaign_id, title").execute()
    camp_lookup = {c["campaign_id"]: c["title"] for c in camps.data}
    by_camp = {}
    for c in convs.data:
        cid  = c.get("campaign_id", "")
        name = camp_lookup.get(cid) or c.get("goal_value") or f"Campaign {cid}"
        rev  = float(c.get("revenue") or 0)
        if name not in by_camp:
            by_camp[name] = {"revenue": 0, "conversions": 0}
        by_camp[name]["revenue"]     += rev
        by_camp[name]["conversions"] += 1
    return sorted(by_camp.items(), key=lambda x: x[1]["revenue"], reverse=True)

def get_appflyer_summary():
    yest  = yesterday_ist()
    stats = supabase.table("appflyer_stats").select("app_name, installs, clicks, impressions, revenue").gte("date", yest).execute()
    total = {"installs": 0, "clicks": 0, "impressions": 0, "revenue": 0}
    for s in stats.data:
        total["installs"]    += int(s.get("installs") or 0)
        total["clicks"]      += int(s.get("clicks") or 0)
        total["impressions"] += int(s.get("impressions") or 0)
        total["revenue"]     += float(s.get("revenue") or 0)
    return total

def send_morning_digest():
    print("\n📊 Sending morning digest...")
    date     = now_ist().strftime("%d %B %Y")
    summary  = get_summary()
    top      = get_top_campaigns()
    appflyer = get_appflyer_summary()

    msg = f"""🌅 *Good Morning Kawal — Daily Performance Report*
📅 *{date} | IST*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💰 *OVERALL SUMMARY (Last 24 Hours IST)*
• Total Revenue:     ₹{summary['total_revenue']:,.0f}
• Total Payout:      ₹{summary['total_payout']:,.0f}
• Profit:            ₹{summary['profit']:,.0f}
• Total Conversions: {summary['total_conversions']:,}
• Approved:          {summary['approved']:,}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📈 *TOP PERFORMING CAMPAIGNS*
"""
    for i, (name, stats) in enumerate(top[:5], 1):
        msg += f"{i}. {name[:40]}\n   Revenue: ₹{stats['revenue']:,.0f} | Conversions: {stats['conversions']}\n"

    if top[5:8]:
        msg += "\n📉 *LOW PERFORMING CAMPAIGNS*\n"
        for name, stats in top[-3:]:
            if stats["revenue"] == 0:
                msg += f"• {name[:40]} — ₹0\n"

    msg += f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"

    if appflyer["installs"] > 0:
        msg += f"""📱 *APPFLYER (Last 24 Hours IST)*
• Installs:    {appflyer['installs']:,}
• Clicks:      {appflyer['clicks']:,}
• Impressions: {appflyer['impressions']:,}
• Revenue:     ₹{appflyer['revenue']:,.0f}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    msg += f"_💬 Ask Agent 1 in #brandshapers-agent1_\n"
    msg += f"_🕐 Generated at {now_ist().strftime('%I:%M %p IST')}_"

    send_slack(CHANNEL_DAILY, msg)
    print("   ✅ Morning digest sent!")

def check_anomalies():
    print("\n🔍 Checking anomalies...")
    alerts = []
    try:
        yest   = yesterday_ist()
        convs  = supabase.table("trackier_conversions").select("campaign_id").gte("created_at", yest).execute()
        camps  = supabase.table("trackier_campaigns").select("campaign_id, title").eq("status", "active").execute()
        active = {c["campaign_id"]: c["title"] for c in camps.data}
        recent = {c["campaign_id"] for c in convs.data}
        silent = [(cid, title) for cid, title in active.items() if cid not in recent]
        if silent:
            titles = [t for _, t in silent[:5]]
            alerts.append(
                f"🔴 *Campaigns with zero conversions in last 24hrs IST*\n" +
                "\n".join([f"   • {t}" for t in titles]) +
                (f"\n   _...and {len(silent)-5} more_" if len(silent) > 5 else "")
            )
        sync = supabase.table("sync_log").select("created_at").order("created_at", desc=True).limit(1).execute()
        if sync.data:
            last = datetime.fromisoformat(sync.data[0]["created_at"].replace("Z", "+00:00"))
            last_ist = last.astimezone(IST)
            hours_since = (now_ist() - last_ist).total_seconds() / 3600
            if hours_since > 8:
                alerts.append(f"⚠️ *Agent 2 hasn't synced in {int(hours_since)} hours*\nLast sync: {last_ist.strftime('%d %b %I:%M %p IST')}")
        if alerts:
            send_slack(CHANNEL_ALERTS, "*🚨 BRANDSHAPERS ALERT*\n\n" + "\n\n".join(alerts))
    except Exception as e:
        print(f"   ❌ Anomaly check error: {e}")

if __name__ == "__main__":
    print("🤖 Agent 3 v2.0 IST — LIVE")
    send_slack(CHANNEL_ALERTS,
        "🟢 *Agent 3 v2.0 IST — LIVE*\n"
        "• Daily reports at 8:00 AM IST → #brandshapers-daily-report\n"
        "• Anomaly checks every hour IST\n"
        "• All times now in India Standard Time ✅"
    )
    check_anomalies()
    send_morning_digest()
    schedule.every().day.at("02:30").do(send_morning_digest)  # 8:00 AM IST
    schedule.every(1).hours.do(check_anomalies)
    print("⏰ Scheduler: 8 AM IST daily + hourly anomaly checks")
    while True:
        schedule.run_pending()
        time.sleep(60)
