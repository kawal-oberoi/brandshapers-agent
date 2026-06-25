# =====================================================
# BRANDSHAPERS - AGENT 2 (Data Collector) v5.0
# Fixed: IST timezone (Asia/Kolkata) throughout
# =====================================================

import os
import json
import time
import requests
import schedule
from datetime import datetime, timedelta
import pytz
from supabase import create_client, Client

SUPABASE_URL        = os.environ.get("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY")
TRACKIER_API_KEY    = os.environ.get("TRACKIER_API_KEY")
APPFLYER_API_TOKEN  = os.environ.get("APPFLYER_API_TOKEN")
TRACKIER_BASE       = "https://api.trackier.com"

IST = pytz.timezone("Asia/Kolkata")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)

def now_ist():
    return datetime.now(IST)

def today_ist():
    return now_ist().strftime("%Y-%m-%d")

def yesterday_ist():
    return (now_ist() - timedelta(days=1)).strftime("%Y-%m-%d")

def log_sync(sync_type, status, records=0, error=None):
    try:
        supabase.table("sync_log").insert({
            "sync_type":      sync_type,
            "status":         status,
            "records_synced": records,
            "error_message":  str(error)[:500] if error else None,
            "created_at":     now_ist().isoformat()
        }).execute()
    except:
        pass

def fetch_trackier_publishers():
    print("\n👥 Fetching Trackier Publishers...")
    headers = {"X-Api-Key": TRACKIER_API_KEY}
    url     = f"{TRACKIER_BASE}/v2/publishers"
    count   = 0
    last_id = None
    try:
        while True:
            params = {"limit": 100}
            if last_id:
                params["lastId"] = last_id
            r = requests.get(url, headers=headers, params=params, timeout=30)
            if r.status_code != 200:
                log_sync("trackier_publishers", "error", error=f"HTTP {r.status_code}")
                break
            data       = r.json()
            publishers = data.get("publishers", [])
            if not publishers:
                break
            for p in publishers:
                pub_id = str(p.get("id", ""))
                if not pub_id:
                    continue
                supabase.table("trackier_publishers").upsert({
                    "publisher_id": pub_id,
                    "name":         p.get("name", ""),
                    "email":        p.get("email", ""),
                    "status":       p.get("status", ""),
                    "updated_at":   now_ist().isoformat()
                }).execute()
                count   += 1
                last_id  = pub_id
            print(f"   ✅ Batch — {len(publishers)} publishers | Total: {count}")
            if len(publishers) < 100:
                break
        log_sync("trackier_publishers", "success", records=count)
    except Exception as e:
        log_sync("trackier_publishers", "error", error=str(e))

def fetch_trackier_campaigns():
    print("\n📦 Fetching Trackier Campaigns...")
    headers = {"X-Api-Key": TRACKIER_API_KEY}
    url     = f"{TRACKIER_BASE}/v2/campaigns"
    count   = 0
    last_id = None
    try:
        while True:
            params = {"limit": 100}
            if last_id:
                params["lastId"] = last_id
            r = requests.get(url, headers=headers, params=params, timeout=30)
            if r.status_code != 200:
                log_sync("trackier_campaigns", "error", error=f"HTTP {r.status_code}")
                break
            data      = r.json()
            campaigns = data.get("campaigns", [])
            if not campaigns:
                break
            for c in campaigns:
                camp_id = str(c.get("id", ""))
                if not camp_id:
                    continue
                supabase.table("trackier_campaigns").upsert({
                    "campaign_id": camp_id,
                    "title":       c.get("title", ""),
                    "status":      c.get("status", ""),
                    "model":       c.get("comm_type", ""),
                    "os":          json.dumps(c.get("os", [])),
                    "updated_at":  now_ist().isoformat()
                }).execute()
                count   += 1
                last_id  = camp_id
            print(f"   ✅ Batch — {len(campaigns)} campaigns | Total: {count}")
            if len(campaigns) < 100:
                break
        log_sync("trackier_campaigns", "success", records=count)
    except Exception as e:
        log_sync("trackier_campaigns", "error", error=str(e))

def fetch_trackier_performance():
    print("\n💰 Fetching Trackier Performance...")
    headers = {"X-Api-Key": TRACKIER_API_KEY}
    url     = f"{TRACKIER_BASE}/v2/reports/campaign"
    today   = today_ist()
    yest    = yesterday_ist()
    count   = 0
    try:
        page = 1
        while True:
            r = requests.get(url, headers=headers,
                params={"start_date": yest, "end_date": today, "limit": 500, "page": page},
                timeout=30)
            if r.status_code != 200:
                break
            records = r.json().get("records", [])
            if not records:
                break
            for rec in records:
                camp_id = str(rec.get("campaign_id", ""))
                if not camp_id:
                    continue
                supabase.table("trackier_conversions").upsert({
                    "conversion_id": f"perf_{camp_id}_{today}",
                    "campaign_id":   camp_id,
                    "publisher_id":  str(rec.get("publisher_id", "")),
                    "goal_value":    rec.get("campaign_name", ""),
                    "revenue":       float(rec.get("revenue") or 0),
                    "payout":        float(rec.get("payout") or 0),
                    "status":        "approved",
                    "created_at":    today,
                    "synced_at":     now_ist().isoformat()
                }).execute()
                count += 1
            print(f"   ✅ Page {page} — {len(records)} records")
            page += 1
            if len(records) < 500:
                break
        print(f"   ✅ Performance done — Total: {count}")
        log_sync("trackier_performance", "success", records=count)
    except Exception as e:
        log_sync("trackier_performance", "error", error=str(e))

def fetch_all_appflyer_apps():
    print("\n🔍 Discovering Appflyer apps...")
    headers = {"Authorization": f"Bearer {APPFLYER_API_TOKEN}"}
    apps    = []
    for endpoint in ["https://hq1.appsflyer.com/api/mng/apps/v2", "https://hq1.appsflyer.com/api/mng/apps"]:
        try:
            r = requests.get(endpoint, headers=headers, timeout=30)
            if r.status_code == 200:
                data     = r.json()
                raw_apps = data if isinstance(data, list) else data.get("apps", data.get("data", []))
                for app in raw_apps:
                    app_id   = str(app.get("app_id") or app.get("id") or "")
                    app_name = str(app.get("app_name") or app.get("name") or "Unknown")
                    platform = str(app.get("platform") or "unknown")
                    if not app_id:
                        continue
                    supabase.table("appflyer_apps").upsert({
                        "app_id":     app_id,
                        "app_name":   app_name,
                        "platform":   platform,
                        "is_active":  True,
                        "updated_at": now_ist().isoformat()
                    }).execute()
                    apps.append({"app_id": app_id, "app_name": app_name})
                if apps:
                    break
        except:
            continue
    if not apps:
        try:
            result = supabase.table("appflyer_apps").select("*").eq("is_active", True).execute()
            apps   = [{"app_id": r["app_id"], "app_name": r["app_name"]} for r in result.data]
        except:
            pass
    log_sync("appflyer_app_discovery", "success", records=len(apps))
    return apps

def fetch_appflyer_stats(apps):
    if not apps:
        return
    today   = today_ist()
    yest    = yesterday_ist()
    headers = {"Authorization": f"Bearer {APPFLYER_API_TOKEN}"}
    total   = 0
    print(f"\n📊 Fetching Appflyer stats for {len(apps)} apps...")
    for app in apps:
        app_id   = app["app_id"]
        app_name = app["app_name"]
        try:
            r = requests.get(
                f"https://hq1.appsflyer.com/api/agg-data/export/app/{app_id}/partners_report/v5",
                headers=headers,
                params={"from": yest, "to": today, "timezone": "Asia/Kolkata"},
                timeout=30
            )
            if r.status_code != 200:
                continue
            lines = r.text.strip().split("\n")
            if len(lines) <= 1:
                continue
            col_headers = [h.strip() for h in lines[0].split(",")]
            count = 0
            for line in lines[1:]:
                values = [v.strip() for v in line.split(",")]
                row    = dict(zip(col_headers, values))
                supabase.table("appflyer_stats").upsert({
                    "app_id":       app_id,
                    "app_name":     app_name,
                    "date":         row.get("Date", today),
                    "media_source": row.get("Media Source", ""),
                    "campaign":     row.get("Campaign", ""),
                    "installs":     int(row.get("Installs", 0) or 0),
                    "clicks":       int(row.get("Clicks", 0) or 0),
                    "impressions":  int(row.get("Impressions", 0) or 0),
                    "revenue":      float(row.get("Revenue", 0) or 0),
                    "synced_at":    now_ist().isoformat()
                }).execute()
                count += 1
            total += count
            print(f"   ✅ {app_name}: {count} rows")
        except Exception as e:
            print(f"   ❌ {app_name}: {e}")
    log_sync("appflyer_stats", "success", records=total)

def run_full_sync():
    print(f"\n{'='*55}")
    print(f"🤖 AGENT 2 v5.0 IST — {now_ist().strftime('%d %b %Y %I:%M %p IST')}")
    print(f"{'='*55}")
    fetch_trackier_publishers()
    fetch_trackier_campaigns()
    fetch_trackier_performance()
    apps = fetch_all_appflyer_apps()
    fetch_appflyer_stats(apps)
    print(f"\n✅ Sync Complete — {now_ist().strftime('%d %b %Y %I:%M %p IST')}")

if __name__ == "__main__":
    print("🤖 Agent 2 v5.0 IST — Starting...")
    run_full_sync()
    schedule.every(6).hours.do(run_full_sync)
    schedule.every().day.at("00:30").do(run_full_sync)  # 6 AM IST
    print("⏰ Scheduler active — every 6 hours IST")
    while True:
        schedule.run_pending()
        time.sleep(60)
