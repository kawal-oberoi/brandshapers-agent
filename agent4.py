# =====================================================
# BRANDSHAPERS - AGENT 4 (The Reporter) v2.0
# Fixed: IST timezone throughout
# =====================================================

import os, json, time, schedule, requests
import pytz
from datetime import datetime, timedelta
from supabase import create_client, Client
import gspread
from google.oauth2.service_account import Credentials

SUPABASE_URL      = os.environ.get("SUPABASE_URL")
SUPABASE_SECRET   = os.environ.get("SUPABASE_SECRET_KEY")
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON")
SHEET_ID          = "1luPWi85oati6lyMLJXKbie5-KrXsQINVeImWMacGfmc"
SLACK_TOKEN       = os.environ.get("SLACK_BOT_TOKEN")
CHANNEL_ALERTS    = "C0BCV12LJ4E"

IST      = pytz.timezone("Asia/Kolkata")
supabase = create_client(SUPABASE_URL, SUPABASE_SECRET)

def now_ist():
    return datetime.now(IST)

def today_ist():
    return now_ist().strftime("%Y-%m-%d")

def connect_sheets():
    try:
        creds  = Credentials.from_service_account_info(
            json.loads(GOOGLE_CREDS_JSON),
            scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        )
        client = gspread.authorize(creds)
        return client.open_by_key(SHEET_ID)
    except Exception as e:
        print(f"❌ Sheets error: {e}")
        return None

def get_tab(sheet, title):
    try:
        return sheet.worksheet(title)
    except:
        return sheet.add_worksheet(title=title, rows=1000, cols=20)

def update_daily_summary(sheet):
    print("\n📊 Daily Summary...")
    ws    = get_tab(sheet, "📊 Daily Summary")
    yest  = (now_ist() - timedelta(days=1)).strftime("%Y-%m-%d")
    convs = supabase.table("trackier_conversions").select("revenue, payout, status").gte("created_at", yest).execute()
    total_rev  = sum(float(c.get("revenue") or 0) for c in convs.data)
    total_pay  = sum(float(c.get("payout") or 0) for c in convs.data)
    total_conv = len(convs.data)
    approved   = sum(1 for c in convs.data if c.get("status") == "approved")
    profit     = total_rev - total_pay
    margin     = (profit / total_rev * 100) if total_rev > 0 else 0
    ws.clear()
    ws.update(values=[["Brandshapers Performance Dashboard — Daily Summary"]], range_name="A1")
    ws.update(values=[[f"Last Updated: {now_ist().strftime('%d %b %Y %I:%M %p IST')}"]], range_name="A2")
    ws.update(values=[["Metric", "Value"]], range_name="A4")
    ws.update(values=[
        ["Total Revenue (₹)",    f"₹{total_rev:,.0f}"],
        ["Total Payout (₹)",     f"₹{total_pay:,.0f}"],
        ["Total Profit (₹)",     f"₹{profit:,.0f}"],
        ["Profit Margin",         f"{margin:.1f}%"],
        ["Total Conversions",     total_conv],
        ["Approved",              approved],
        ["Date Range (IST)",      f"{yest} to {today_ist()}"],
        ["Timezone",              "India Standard Time (IST)"]
    ], range_name="A5")
    ws.format("A1", {"textFormat": {"bold": True, "fontSize": 14}})
    ws.format("A4:B4", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.2, "green": 0.5, "blue": 0.8}})
    print("   ✅ Done")

def update_top_campaigns(sheet):
    print("\n📈 Top Campaigns...")
    ws    = get_tab(sheet, "📈 Top Campaigns")
    start = (now_ist() - timedelta(days=7)).strftime("%Y-%m-%d")
    convs = supabase.table("trackier_conversions").select("campaign_id, goal_value, revenue, payout").gte("created_at", start).execute()
    camps = supabase.table("trackier_campaigns").select("campaign_id, title").execute()
    camp_lookup = {c["campaign_id"]: c["title"] for c in camps.data}
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
    ws.update(values=[[f"Top Campaigns — Last 7 Days IST (updated {now_ist().strftime('%d %b %I:%M %p IST')})"]], range_name="A1")
    ws.update(values=[["Rank", "Campaign Name", "Revenue (₹)", "Payout (₹)", "Profit (₹)", "Conversions", "Margin %"]], range_name="A3")
    rows = []
    for i, (name, s) in enumerate(top, 1):
        margin = (s["profit"] / s["revenue"] * 100) if s["revenue"] > 0 else 0
        rows.append([i, name, round(s["revenue"], 0), round(s["payout"], 0), round(s["profit"], 0), s["conversions"], f"{margin:.1f}%"])
    if rows:
        ws.update(values=rows, range_name="A4")
    ws.format("A3:G3", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.1, "green": 0.7, "blue": 0.3}})
    print(f"   ✅ {len(rows)} campaigns")

def update_publishers(sheet):
    print("\n👥 Publishers...")
    ws    = get_tab(sheet, "👥 Publishers")
    start = (now_ist() - timedelta(days=7)).strftime("%Y-%m-%d")
    convs = supabase.table("trackier_conversions").select("publisher_id, revenue, payout").gte("created_at", start).execute()
    pubs  = supabase.table("trackier_publishers").select("publisher_id, name").execute()
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
    top = sorted(by_pub.items(), key=lambda x: x[1]["revenue"], reverse=True)
    ws.clear()
    ws.update(values=[[f"Publisher Performance — Last 7 Days IST (updated {now_ist().strftime('%d %b %I:%M %p IST')})"]], range_name="A1")
    ws.update(values=[["Rank", "Publisher Name", "Revenue (₹)", "Payout (₹)", "Conversions"]], range_name="A3")
    rows = [[i, name, round(s["revenue"], 0), round(s["payout"], 0), s["conversions"]] for i, (name, s) in enumerate(top, 1)]
    if rows:
        ws.update(values=rows, range_name="A4")
    print(f"   ✅ {len(rows)} publishers")

def update_appflyer(sheet):
    print("\n📱 Appflyer...")
    ws    = get_tab(sheet, "📱 Appflyer")
    start = (now_ist() - timedelta(days=7)).strftime("%Y-%m-%d")
    stats = supabase.table("appflyer_stats").select("*").gte("date", start).order("date", desc=True).execute()
    ws.clear()
    ws.update(values=[[f"Appflyer Stats — Last 7 Days IST (updated {now_ist().strftime('%d %b %I:%M %p IST')})"]], range_name="A1")
    ws.update(values=[["Date (IST)", "App Name", "Media Source", "Installs", "Clicks", "Impressions", "Revenue (₹)"]], range_name="A3")
    rows = [[s.get("date",""), s.get("app_name",""), s.get("media_source",""), s.get("installs",0), s.get("clicks",0), s.get("impressions",0), round(float(s.get("revenue") or 0), 0)] for s in stats.data]
    if rows:
        ws.update(values=rows, range_name="A4")
    else:
        ws.update(values=[["No Appflyer data yet"]], range_name="A4")
    print(f"   ✅ {len(rows)} rows")

def update_alerts(sheet):
    print("\n🚨 Alerts...")
    ws    = get_tab(sheet, "🚨 Alerts")
    start = (now_ist() - timedelta(days=2)).strftime("%Y-%m-%d")
    convs = supabase.table("trackier_conversions").select("campaign_id, goal_value, revenue").gte("created_at", start).execute()
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
    zero = sorted([(n, s) for n, s in by_camp.items() if s["revenue"] == 0], key=lambda x: x[1]["conversions"], reverse=True)
    ws.clear()
    ws.update(values=[[f"Zero Revenue Alerts IST (updated {now_ist().strftime('%d %b %I:%M %p IST')})"]], range_name="A1")
    ws.update(values=[["Campaign Name", "Conversions", "Revenue", "Action Needed"]], range_name="A3")
    rows = [[n, s["conversions"], "₹0", "Check payout rate in Trackier"] for n, s in zero]
    if rows:
        ws.update(values=rows, range_name="A4")
    else:
        ws.update(values=[["✅ All campaigns generating revenue!"]], range_name="A4")
    print(f"   ✅ {len(rows)} zero-revenue campaigns")

def update_trend(sheet):
    print("\n📅 30-Day Trend...")
    ws    = get_tab(sheet, "📅 30-Day Trend")
    start = (now_ist() - timedelta(days=30)).strftime("%Y-%m-%d")
    convs = supabase.table("trackier_conversions").select("revenue, payout, created_at").gte("created_at", start).execute()
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
    ws.update(values=[[f"30-Day Trend IST (updated {now_ist().strftime('%d %b %I:%M %p IST')})"]], range_name="A1")
    ws.update(values=[["Date (IST)", "Revenue (₹)", "Payout (₹)", "Profit (₹)", "Conversions"]], range_name="A3")
    rows = [[d, round(s["revenue"],0), round(s["payout"],0), round(s["revenue"]-s["payout"],0), s["conversions"]] for d, s in sorted_dates]
    if rows:
        ws.update(values=rows, range_name="A4")
    print(f"   ✅ {len(rows)} days")

def run_full_update():
    print(f"\n{'='*55}")
    print(f"🤖 AGENT 4 v2.0 IST — {now_ist().strftime('%d %b %Y %I:%M %p IST')}")
    print(f"{'='*55}")
    sheet = connect_sheets()
    if not sheet:
        return
    update_daily_summary(sheet)
    time.sleep(2)
    update_top_campaigns(sheet)
    time.sleep(2)
    update_publishers(sheet)
    time.sleep(2)
    update_appflyer(sheet)
    time.sleep(2)
    update_alerts(sheet)
    time.sleep(2)
    update_trend(sheet)
    print(f"\n✅ Dashboard updated — {now_ist().strftime('%d %b %Y %I:%M %p IST')}")
    if SLACK_TOKEN:
        requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_TOKEN}", "Content-Type": "application/json"},
            json={"channel": CHANNEL_ALERTS, "text": f"📊 *Google Sheets Dashboard Updated (IST)*\n🔗 https://docs.google.com/spreadsheets/d/{SHEET_ID}\n_Updated at {now_ist().strftime('%d %b %Y %I:%M %p IST')}_"}
        )

if __name__ == "__main__":
    print("🤖 Agent 4 v2.0 IST — Starting...")
    run_full_update()
    schedule.every(6).hours.do(run_full_update)
    schedule.every().day.at("02:00").do(run_full_update)  # 7:30 AM IST
    print("⏰ Scheduler active — every 6 hours IST")
    while True:
        schedule.run_pending()
        time.sleep(60)
