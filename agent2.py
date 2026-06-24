# =====================================================
# BRANDSHAPERS - AGENT 2 (Data Collector) v4.0 FINAL
# Built from real API response inspection
# Confirmed working field names and URL
# =====================================================

import os
import json
import time
import requests
import schedule
from datetime import datetime, timedelta
from supabase import create_client, Client

# =====================================================
# CONFIGURATION
# =====================================================
SUPABASE_URL        = os.environ.get("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY")
TRACKIER_API_KEY    = os.environ.get("TRACKIER_API_KEY")
APPFLYER_API_TOKEN  = os.environ.get("APPFLYER_API_TOKEN")

# Confirmed working base URL
TRACKIER_BASE = "https://api.trackier.com"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)


# =====================================================
# HELPER — LOG SYNC
# =====================================================
def log_sync(sync_type, status, records=0, error=None):
    try:
        supabase.table("sync_log").insert({
            "sync_type":      sync_type,
            "status":         status,
            "records_synced": records,
            "error_message":  str(error)[:500] if error else None,
            "created_at":     datetime.now().isoformat()
        }).execute()
    except Exception as e:
        print(f"⚠️  sync_log error: {e}")


# =====================================================
# TRACKIER — PUBLISHERS
# Confirmed fields: name, email, status, id (numeric)
# Pagination: uses 'lastId' not page numbers
# =====================================================
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
                print(f"   ❌ HTTP {r.status_code}")
                log_sync("trackier_publishers", "error", error=f"HTTP {r.status_code}")
                break

            data = r.json()
            publishers = data.get("publishers", [])

            if not publishers:
                break

            for p in publishers:
                # ID is a numeric field confirmed from testing
                pub_id = str(p.get("id", ""))
                if not pub_id:
                    continue

                supabase.table("trackier_publishers").upsert({
                    "publisher_id": pub_id,
                    "name":         p.get("name", ""),
                    "email":        p.get("email", ""),
                    "status":       p.get("status", ""),
                    "updated_at":   datetime.now().isoformat()
                }).execute()
                count += 1
                last_id = pub_id  # Track last ID for pagination

            print(f"   ✅ Batch done — {len(publishers)} publishers | Total so far: {count}")

            # Stop if we got less than limit — means no more pages
            if len(publishers) < 100:
                break

        print(f"   ✅ Publishers complete — Total: {count}")
        log_sync("trackier_publishers", "success", records=count)

    except Exception as e:
        print(f"   ❌ Error: {e}")
        log_sync("trackier_publishers", "error", error=str(e))


# =====================================================
# TRACKIER — CAMPAIGNS
# Confirmed fields: id, title, status, os
# Extra fields: currency, device, region, categories
# =====================================================
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
                print(f"   ❌ HTTP {r.status_code}")
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
                    "model":       c.get("comm_type", "") or c.get("currency", ""),
                    "os":          json.dumps(c.get("os", [])),
                    "updated_at":  datetime.now().isoformat()
                }).execute()
                count += 1
                last_id = camp_id

            print(f"   ✅ Batch done — {len(campaigns)} campaigns | Total so far: {count}")

            if len(campaigns) < 100:
                break

        print(f"   ✅ Campaigns complete — Total: {count}")
        log_sync("trackier_campaigns", "success", records=count)

    except Exception as e:
        print(f"   ❌ Error: {e}")
        log_sync("trackier_campaigns", "error", error=str(e))


# =====================================================
# TRACKIER — PERFORMANCE STATS (Revenue & Conversions)
# =====================================================
def fetch_trackier_performance():
    print("\n💰 Fetching Trackier Performance Stats...")
    headers   = {"X-Api-Key": TRACKIER_API_KEY}
    today     = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    count     = 0

    # Try known report endpoints
    endpoints = [
        f"{TRACKIER_BASE}/v2/report/campaign",
        f"{TRACKIER_BASE}/v2/reports/campaign",
        f"{TRACKIER_BASE}/v2/report/performance",
        f"{TRACKIER_BASE}/v2/reports/conversions",
    ]

    for endpoint in endpoints:
        try:
            r = requests.get(
                endpoint,
                headers=headers,
                params={"start_date": yesterday, "end_date": today, "limit": 500},
                timeout=30
            )
            print(f"   🔗 {endpoint} → {r.status_code}")

            if r.status_code == 200 and r.text.strip():
                data    = r.json()
                records = (
                    data.get("records", []) or
                    data.get("data", []) or
                    data.get("report", []) or
                    data.get("conversions", []) or
                    []
                )

                if records:
                    for rec in records:
                        rec_id = str(rec.get("id") or rec.get("_id") or
                                     f"{rec.get('campaign_id','x')}_{today}")
                        supabase.table("trackier_conversions").upsert({
                            "conversion_id": rec_id,
                            "campaign_id":   str(rec.get("campaign_id", "")),
                            "publisher_id":  str(rec.get("publisher_id", "")),
                            "goal_value":    str(rec.get("goal_value", "")),
                            "revenue":       float(rec.get("revenue") or 0),
                            "payout":        float(rec.get("payout") or 0),
                            "status":        str(rec.get("status", "")),
                            "created_at":    today,
                            "synced_at":     datetime.now().isoformat()
                        }).execute()
                        count += 1

                    print(f"   ✅ Performance stats done — {count} records")
                    log_sync("trackier_performance", "success", records=count)
                    return

        except Exception as e:
            print(f"   ⚠️  {endpoint} failed: {e}")
            continue

    print("   ⚠️  No performance endpoint found yet — will retry next sync")
    log_sync("trackier_performance", "skipped", error="No working endpoint found")


# =====================================================
# APPFLYER — DISCOVER ALL APPS
# =====================================================
def fetch_all_appflyer_apps():
    print("\n🔍 Discovering Appflyer apps...")
    headers = {"Authorization": f"Bearer {APPFLYER_API_TOKEN}"}
    apps    = []

    endpoints = [
        "https://hq1.appsflyer.com/api/mng/apps/v2",
        "https://hq1.appsflyer.com/api/mng/apps",
    ]

    for endpoint in endpoints:
        try:
            r = requests.get(endpoint, headers=headers, timeout=30)
            print(f"   🔗 {endpoint} → {r.status_code}")

            if r.status_code == 200:
                data     = r.json()
                raw_apps = data if isinstance(data, list) else data.get("apps", data.get("data", []))

                for app in raw_apps:
                    app_id   = str(app.get("app_id") or app.get("id") or "")
                    app_name = str(app.get("app_name") or app.get("name") or "Unknown")
                    platform = str(app.get("platform") or app.get("os") or "unknown")

                    if not app_id:
                        continue

                    supabase.table("appflyer_apps").upsert({
                        "app_id":     app_id,
                        "app_name":   app_name,
                        "platform":   platform,
                        "is_active":  True,
                        "updated_at": datetime.now().isoformat()
                    }).execute()
                    apps.append({"app_id": app_id, "app_name": app_name})
                    print(f"   📱 {app_name} ({app_id})")

                if apps:
                    break

        except Exception as e:
            print(f"   ⚠️  {endpoint}: {e}")
            continue

    # Fallback — load from Supabase if discovery failed
    if not apps:
        print("   📋 Loading from Supabase (previously stored apps)...")
        try:
            result = supabase.table("appflyer_apps").select("*").eq("is_active", True).execute()
            apps   = [{"app_id": r["app_id"], "app_name": r["app_name"]} for r in result.data]
            print(f"   ✅ Loaded {len(apps)} apps from database")
        except Exception as e:
            print(f"   ❌ {e}")

    print(f"   ✅ Total apps: {len(apps)}")
    log_sync("appflyer_app_discovery", "success", records=len(apps))
    return apps


# =====================================================
# APPFLYER — STATS PER APP
# =====================================================
def fetch_appflyer_stats_for_all_apps(apps):
    if not apps:
        print("\n⚠️  No apps to fetch Appflyer stats for.")
        return

    today     = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    headers   = {"Authorization": f"Bearer {APPFLYER_API_TOKEN}"}
    total     = 0

    print(f"\n📊 Fetching Appflyer stats for {len(apps)} apps...")

    for app in apps:
        app_id   = app["app_id"]
        app_name = app["app_name"]
        count    = 0

        print(f"\n   → {app_name} ({app_id})")

        try:
            url = f"https://hq1.appsflyer.com/api/agg-data/export/app/{app_id}/partners_report/v5"
            r   = requests.get(url, headers=headers,
                               params={"from": yesterday, "to": today, "timezone": "Asia/Dubai"},
                               timeout=30)

            if r.status_code == 404:
                print(f"      ⚠️  No data yet")
                continue
            if r.status_code != 200:
                print(f"      ❌ HTTP {r.status_code}")
                continue

            lines = r.text.strip().split("\n")
            if len(lines) <= 1:
                print(f"      ⚠️  Empty")
                continue

            col_headers = [h.strip() for h in lines[0].split(",")]
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
                    "synced_at":    datetime.now().isoformat()
                }).execute()
                count += 1

            print(f"      ✅ {count} rows")
            total += count

        except Exception as e:
            print(f"      ❌ {e}")
            continue

    print(f"\n   ✅ Appflyer total: {total} rows across {len(apps)} apps")
    log_sync("appflyer_stats_all_apps", "success", records=total)


# =====================================================
# MASTER SYNC
# =====================================================
def run_full_sync():
    print(f"\n{'='*55}")
    print(f"🤖 AGENT 2 v4.0 FINAL — {datetime.now()}")
    print(f"{'='*55}")

    fetch_trackier_publishers()
    fetch_trackier_campaigns()
    fetch_trackier_performance()

    apps = fetch_all_appflyer_apps()
    fetch_appflyer_stats_for_all_apps(apps)

    print(f"\n{'='*55}")
    print(f"✅ Sync Complete — {datetime.now()}")
    print(f"{'='*55}\n")


# =====================================================
# ENTRY POINT
# =====================================================
if __name__ == "__main__":
    print("🤖 Agent 2 v4.0 FINAL — Starting...")
    run_full_sync()
    schedule.every(6).hours.do(run_full_sync)
    schedule.every().day.at("03:00").do(run_full_sync)
    print("⏰ Scheduler active — every 6 hours")
    while True:
        schedule.run_pending()
        time.sleep(60)
