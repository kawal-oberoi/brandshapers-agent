# =====================================================
# BRANDSHAPERS - AGENT 4 (The Reporter)
# Writes live data to Google Sheets dashboard
# Runs every 6 hours automatically
# =====================================================

import os
import json
import time
import schedule
import requests
from datetime import datetime, timedelta
from supabase import create_client, Client
import gspread
from google.oauth2.service_account import Credentials

# =====================================================
# CONFIGURATION
# =====================================================
SUPABASE_URL        = os.environ.get("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY")
GOOGLE_CREDS_JSON   = os.environ.get("GOOGLE_CREDS_JSON")
SHEET_ID            = "1luPWi85oati6lyMLJXKbie5-KrXsQINVeImWMacGfmc"
SLACK_BOT_TOKEN     = os.environ.get("SLACK_BOT_TOKEN")
CHANNEL_ALERTS      = "C0BCV12LJ4E"

supabase: Client    = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)


# =====================================================
# GOOGLE SHEETS — CONNECT
# =====================================================
def connect_sheets():
    try:
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        creds      = Credentials.from_service_account_info(
            creds_dict,
            scopes=[
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive"
            ]
        )
        client = gspread.authorize(creds)
        sheet  = client.open_by_key(SHEET_ID)
        print("✅ Connected to Google Sheets")
        return sheet
    except Exception as e:
        print(f"❌ Google Sheets connection error: {e}")
        return None


# =====================================================
# HELPER — GET OR CREATE WORKSHEET TAB
# =====================================================
def get_or_create_tab(sheet, title):
    try:
        return sheet.worksheet(title)
    except:
        return sheet.add_worksheet(title=title, rows=1000, cols=20)


# =====================================================
# TAB 1 — DAILY SUMMARY
# =====================================================
def update_daily_summary(sheet):
    print("\n📊 Updating Daily Summary tab...")
    ws    = get_or_create_tab(sheet, "📊 Daily Summary")
    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    convs = supabase.table("trackier_conversions")\
        .select("revenue, payout, status, created_at")\
        .gte("created_at", start).execute()

    total_rev  = sum(float(c.get("revenue") or 0) for c in convs.data)
    total_pay  = sum(float(c.get("payout") or 0) for c in convs.data)
    total_conv = len(convs.data)
    approved   = sum(1 for c in convs.data if c.get("status") == "approved")
    profit     = total_rev - total_pay
    margin     = (profit / total_rev * 100) if total_rev > 0 else 0

    # Header
    ws.clear()
    ws.update("A1", [["Brandshapers Performance Dashboard — Daily Summary"]])
    ws.update("A2", [[f"Last Updated: {datetime.now().strftime('%d %b %Y %H:%M')} IST"]])
    ws.update("A4", [["Metric", "Value"]])
    ws.update("A5", [
        ["Total Revenue",    f"₹{total_rev:,.0f}"],
        ["Total Payout",     f"₹{total_pay:,.0f}"],
        ["Total Profit",     f"₹{profit:,.0f}"],
        ["Profit Margin",    f"{margin:.1f}%"],
        ["Total Conversions", total_conv],
        ["Approved",         approved],
        ["Date Range",       f"{start} to {today}"]
    ])

    # Format header
    ws.format("A1", {"textFormat": {"bold": True, "fontSize": 14}})
    ws.format("A4:B4", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.2, "green": 0.5, "blue": 0.8}})
    print("   ✅ Daily Summary updated")


# =====================================================
# TAB 2 — TOP CAMPAIGNS
# =====================================================
def update_top_campaigns(sheet):
    print("\n📈 Updating Top Campaigns tab...")
    ws    = get_or_create_tab(sheet, "📈 Top Campaigns")
    start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    convs = supabase.table("trackier_conversions")\
        .select("campaign_id, goal_value, revenue, payout, status, created_at")\
        .gte("created_at", start)\
        .order("revenue", desc=True).limit(500).execute()

    camps = supabase.table("trackier_campaigns")\
        .select("campaign_id, title, status").execute()
    camp_lookup = {c["campaign_id"]: c["title"] for c in camps.data}

    # Group by campaign
    by_camp = {}
    for c in convs.data:
        cid  = c.get("campaign_id", "")
        name = camp_lookup.get(cid) or c.get("goal_value") or f"Campaign {cid}"
        rev  = float(c.get("revenue") or 0)
        pay  = float(c.get("payout") or 0)
        if name not in by_camp:
            by_camp[name] = {"revenue": 0, "payout": 0, "profit": 0, "conversions": 0}
        by_camp[name]["revenue"]     += rev
        by_camp[name]["payout"]      += pay
        by_camp[name]["profit"]      += rev - pay
        by_camp[name]["conversions"] += 1

    top = sorted(by_camp.items(), key=lambda x: x[1]["revenue"], reverse=True)

    ws.clear()
    ws.update("A1", [[f"Top Campaigns by Revenue — Last 7 Days (updated {datetime.now().strftime('%d %b %H:%M')})"]])
    ws.update("A3", [["Rank", "Campaign Name", "Revenue (₹)", "Payout (₹)", "Profit (₹)", "Conversions", "Margin %"]])

    rows = []
    for i, (name, stats) in enumerate(top, 1):
        margin = (stats["profit"] / stats["revenue"] * 100) if stats["revenue"] > 0 else 0
        rows.append([
            i,
            name,
            round(stats["revenue"], 0),
            round(stats["payout"], 0),
            round(stats["profit"], 0),
            stats["conversions"],
            f"{margin:.1f}%"
        ])

    if rows:
        ws.update(f"A4", rows)

    ws.format("A1", {"textFormat": {"bold": True, "fontSize": 13}})
    ws.format("A3:G3", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.1, "green": 0.7, "blue": 0.3}})
    print(f"   ✅ Top Campaigns updated — {len(rows)} campaigns")


# =====================================================
# TAB 3 — PUBLISHER PERFORMANCE
# =====================================================
def update_publisher_performance(sheet):
    print("\n👥 Updating Publisher Performance tab...")
    ws    = get_or_create_tab(sheet, "👥 Publishers")
    start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    convs = supabase.table("trackier_conversions")\
        .select("publisher_id, revenue, payout, status")\
        .gte("created_at", start).execute()

    pubs = supabase.table("trackier_publishers")\
        .select("publisher_id, name, email, status").execute()
    pub_lookup = {p["publisher_id"]: p["name"] for p in pubs.data}

    by_pub = {}
    for c in convs.data:
        pid   = c.get("publisher_id", "")
        name  = pub_lookup.get(pid) or f"Publisher {pid}"
        rev   = float(c.get("revenue") or 0)
        pay   = float(c.get("payout") or 0)
        if name not in by_pub:
            by_pub[name] = {"revenue": 0, "payout": 0, "conversions": 0}
        by_pub[name]["revenue"]     += rev
        by_pub[name]["payout"]      += pay
        by_pub[name]["conversions"] += 1

    top_pubs = sorted(by_pub.items(), key=lambda x: x[1]["revenue"], reverse=True)

    ws.clear()
    ws.update("A1", [[f"Publisher Performance — Last 7 Days (updated {datetime.now().strftime('%d %b %H:%M')})"]])
    ws.update("A3", [["Rank", "Publisher Name", "Revenue (₹)", "Payout (₹)", "Conversions"]])

    rows = []
    for i, (name, stats) in enumerate(top_pubs, 1):
        rows.append([i, name, round(stats["revenue"], 0), round(stats["payout"], 0), stats["conversions"]])

    if rows:
        ws.update("A4", rows)

    ws.format("A1", {"textFormat": {"bold": True, "fontSize": 13}})
    ws.format("A3:E3", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.5, "green": 0.2, "blue": 0.8}})
    print(f"   ✅ Publisher Performance updated — {len(rows)} publishers")


# =====================================================
# TAB 4 — APPFLYER STATS
# =====================================================
def update_appflyer_stats(sheet):
    print("\n📱 Updating Appflyer Stats tab...")
    ws    = get_or_create_tab(sheet, "📱 Appflyer")
    start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    stats = supabase.table("appflyer_stats")\
        .select("app_name, date, installs, clicks, impressions, revenue, media_source")\
        .gte("date", start)\
        .order("date", desc=True).execute()

    ws.clear()
    ws.update("A1", [[f"Appflyer Stats — Last 7 Days (updated {datetime.now().strftime('%d %b %H:%M')})"]])
    ws.update("A3", [["Date", "App Name", "Media Source", "Installs", "Clicks", "Impressions", "Revenue (₹)"]])

    rows = []
    for s in stats.data:
        rows.append([
            s.get("date", ""),
            s.get("app_name", ""),
            s.get("media_source", ""),
            s.get("installs", 0),
            s.get("clicks", 0),
            s.get("impressions", 0),
            round(float(s.get("revenue") or 0), 0)
        ])

    if rows:
        ws.update("A4", rows)
    else:
        ws.update("A4", [["No Appflyer data yet — will populate once apps start tracking"]])

    ws.format("A1", {"textFormat": {"bold": True, "fontSize": 13}})
    ws.format("A3:G3", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.9, "green": 0.5, "blue": 0.1}})
    print(f"   ✅ Appflyer Stats updated — {len(rows)} rows")


# =====================================================
# TAB 5 — ZERO REVENUE ALERTS
# =====================================================
def update_zero_revenue_alerts(sheet):
    print("\n🚨 Updating Zero Revenue Alerts tab...")
    ws    = get_or_create_tab(sheet, "🚨 Alerts")
    start = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")

    convs = supabase.table("trackier_conversions")\
        .select("campaign_id, goal_value, revenue, payout, status, created_at")\
        .gte("created_at", start).execute()

    camps = supabase.table("trackier_campaigns")\
        .select("campaign_id, title, status").execute()
    camp_lookup = {c["campaign_id"]: c["title"] for c in camps.data}

    # Find campaigns with conversions but zero revenue
    by_camp = {}
    for c in convs.data:
        cid  = c.get("campaign_id", "")
        name = camp_lookup.get(cid) or c.get("goal_value") or f"Campaign {cid}"
        rev  = float(c.get("revenue") or 0)
        if name not in by_camp:
            by_camp[name] = {"revenue": 0, "conversions": 0}
        by_camp[name]["revenue"]     += rev
        by_camp[name]["conversions"] += 1

    zero_rev = [(name, stats) for name, stats in by_camp.items() if stats["revenue"] == 0]
    zero_rev.sort(key=lambda x: x[1]["conversions"], reverse=True)

    ws.clear()
    ws.update("A1", [[f"Zero Revenue Alerts — Campaigns with conversions but ₹0 revenue (updated {datetime.now().strftime('%d %b %H:%M')})"]])
    ws.update("A3", [["Campaign Name", "Conversions", "Revenue", "Action Needed"]])

    rows = []
    for name, stats in zero_rev:
        rows.append([name, stats["conversions"], "₹0", "Check payout rate config in Trackier"])

    if rows:
        ws.update("A4", rows)
    else:
        ws.update("A4", [["✅ All campaigns with conversions are generating revenue!"]])

    ws.format("A1", {"textFormat": {"bold": True, "fontSize": 13}})
    ws.format("A3:D3", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.9, "green": 0.2, "blue": 0.2}})
    print(f"   ✅ Alerts tab updated — {len(rows)} zero-revenue campaigns flagged")


# =====================================================
# TAB 6 — 30 DAY TREND
# =====================================================
def update_historical_trend(sheet):
    print("\n📅 Updating 30-Day Trend tab...")
    ws    = get_or_create_tab(sheet, "📅 30-Day Trend")
    start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    convs = supabase.table("trackier_conversions")\
        .select("revenue, payout, status, created_at")\
        .gte("created_at", start).execute()

    # Group by date
    by_date = {}
    for c in convs.data:
        date = str(c.get("created_at", ""))[:10]
        rev  = float(c.get("revenue") or 0)
        pay  = float(c.get("payout") or 0)
        if date not in by_date:
            by_date[date] = {"revenue": 0, "payout": 0, "conversions": 0}
        by_date[date]["revenue"]     += rev
        by_date[date]["payout"]      += pay
        by_date[date]["conversions"] += 1

    sorted_dates = sorted(by_date.items(), reverse=True)

    ws.clear()
    ws.update("A1", [[f"30-Day Performance Trend (updated {datetime.now().strftime('%d %b %H:%M')})"]])
    ws.update("A3", [["Date", "Revenue (₹)", "Payout (₹)", "Profit (₹)", "Conversions"]])

    rows = []
    for date, stats in sorted_dates:
        profit = stats["revenue"] - stats["payout"]
        rows.append([date, round(stats["revenue"], 0), round(stats["payout"], 0), round(profit, 0), stats["conversions"]])

    if rows:
        ws.update("A4", rows)

    ws.format("A1", {"textFormat": {"bold": True, "fontSize": 13}})
    ws.format("A3:E3", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.2, "green": 0.4, "blue": 0.8}})
    print(f"   ✅ 30-Day Trend updated — {len(rows)} days")


# =====================================================
# MASTER UPDATE — RUNS ALL TABS
# =====================================================
def run_full_update():
    print(f"\n{'='*55}")
    print(f"🤖 AGENT 4 — Dashboard Update Started {datetime.now()}")
    print(f"{'='*55}")

    sheet = connect_sheets()
    if not sheet:
        print("❌ Could not connect to Google Sheets")
        return

    update_daily_summary(sheet)
    time.sleep(2)  # Avoid API rate limits
    update_top_campaigns(sheet)
    time.sleep(2)
    update_publisher_performance(sheet)
    time.sleep(2)
    update_appflyer_stats(sheet)
    time.sleep(2)
    update_zero_revenue_alerts(sheet)
    time.sleep(2)
    update_historical_trend(sheet)

    print(f"\n{'='*55}")
    print(f"✅ Dashboard fully updated at {datetime.now()}")
    print(f"🔗 https://docs.google.com/spreadsheets/d/{SHEET_ID}")
    print(f"{'='*55}\n")

    # Send Slack notification
    if SLACK_BOT_TOKEN:
        requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
            json={
                "channel": CHANNEL_ALERTS,
                "text": f"📊 *Google Sheets Dashboard Updated*\n🔗 https://docs.google.com/spreadsheets/d/{SHEET_ID}\n_Updated at {datetime.now().strftime('%d %b %Y %H:%M')} IST_"
            }
        )


# =====================================================
# ENTRY POINT
# =====================================================
if __name__ == "__main__":
    print("🤖 Agent 4 — The Reporter is LIVE")
    print(f"📊 Sheet: https://docs.google.com/spreadsheets/d/{SHEET_ID}")

    # Run immediately on startup
    run_full_update()

    # Schedule every 6 hours
    schedule.every(6).hours.do(run_full_update)

    # Also update daily at 7:30 AM India time (2:00 AM UTC) — 30 min before morning report
    schedule.every().day.at("02:00").do(run_full_update)

    print("⏰ Scheduler active — updating every 6 hours")

    while True:
        schedule.run_pending()
        time.sleep(60)
