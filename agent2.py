# =====================================================
# BRANDSHAPERS - AGENT 2 (Data Collector) v3.0
# Fixed: Custom Trackier domain + correct API parsing
# Fixed: Appflyer app discovery endpoint
# Runs every 6 hours on Render
# =====================================================

import os
import json
import time
import requests
import schedule
from datetime import datetime, timedelta
from supabase import create_client, Client

# =====================================================
# CONFIGURATION — Loaded from Render Environment
# =====================================================
SUPABASE_URL        = os.environ.get("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY")
TRACKIER_API_KEY    = os.environ.get("TRACKIER_API_KEY")
TRACKIER_BASE_URL   = os.environ.get("TRACKIER_BASE_URL", "https://brandshapers.trackier.io")
APPFLYER_API_TOKEN  = os.environ.get("APPFLYER_API_TOKEN")

# Connect to Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)

# =====================================================
# HELPER — SAFE API CALL WITH ERROR LOGGING
# =====================================================
def safe_get(url, headers, params=None):
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        return response
    except Exception as e:
        print(f"   ❌ Request failed: {e}")
        return None

# =====================================================
# HELPER — LOG EVERY SYNC TO DATABASE
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
        print(f"⚠️  Could not write to sync_log: {e}")


# =====================================================
# TRACKIER — FETCH CAMPAIGNS
# =====================================================
def fetch_trackier_campaigns():
    print("\n📦 Fetching Trackier Campaigns...")
    headers = {"X-Api-Key": TRACKIER_API_KEY}
    url     = f"{TRACKIER_BASE_URL}/api/v2/campaigns"
    count   = 0

    try:
        page = 1
        while True:
            response = safe_get(url, headers, params={"limit": 100, "page": page})
            if not response:
                break

            # Debug: print raw response structure on first page
            if page == 1:
                print(f"   📡 API Status: {response.status_code}")

            if response.status_code != 200:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                print(f"   ❌ {error_msg}")
                log_sync("trackier_campaigns", "error", error=error_msg)
                break

            data = response.json()

            # Trackier returns campaigns directly without success wrapper
            campaigns = data.get("campaigns", [])

            # Fallback: try nested data structure
            if not campaigns and "data" in data:
                campaigns = data["data"].get("campaigns", [])

            if not campaigns:
                print(f"   ℹ️  No campaigns on page {page}")
                break

            for c in campaigns:
                campaign_id = str(c.get("id") or c.get("_id") or "")
                if not campaign_id:
                    continue

                supabase.table("trackier_campaigns").upsert({
                    "campaign_id":   campaign_id,
                    "title":         c.get("title", ""),
                    "status":        c.get("status", ""),
                    "model":         c.get("comm_type", "") or c.get("objective", ""),
                    "os":            json.dumps(c.get("os", [])),
                    "updated_at":    datetime.now().isoformat()
                }).execute()
                count += 1

            print(f"   ✅ Page {page} — {len(campaigns)} campaigns synced")
            page += 1

            if len(campaigns) < 100:
                break

        print(f"   ✅ Trackier Campaigns done — Total: {count}")
        log_sync("trackier_campaigns", "success", records=count)

    except Exception as e:
        print(f"   ❌ Error: {e}")
        log_sync("trackier_campaigns", "error", error=str(e))


# =====================================================
# TRACKIER — FETCH PUBLISHERS
# =====================================================
def fetch_trackier_publishers():
    print("\n👥 Fetching Trackier Publishers...")
    headers = {"X-Api-Key": TRACKIER_API_KEY}
    url     = f"{TRACKIER_BASE_URL}/api/v2/publishers"
    count   = 0

    try:
        page = 1
        while True:
            response = safe_get(url, headers, params={"limit": 100, "page": page})
            if not response:
                break

            if page == 1:
                print(f"   📡 API Status: {response.status_code}")

            if response.status_code != 200:
                error_msg = f"HTTP {response.status_code}: {response.text[:200]}"
                print(f"   ❌ {error_msg}")
                log_sync("trackier_publishers", "error", error=error_msg)
                break

            data = response.json()

            # Trackier returns publishers directly
            publishers = data.get("publishers", [])

            # Fallback: try nested data structure
            if not publishers and "data" in data:
                publishers = data["data"].get("publishers", [])

            if not publishers:
                print(f"   ℹ️  No publishers on page {page}")
                break

            for p in publishers:
                pub_id = str(p.get("id") or p.get("_id") or "")
                if not pub_id:
                    continue

                supabase.table("trackier_publishers").upsert({
                    "publisher_id": pub_id,
                    "name":         p.get("company") or p.get("name", ""),
                    "email":        p.get("email", ""),
                    "status":       p.get("status", ""),
                    "updated_at":   datetime.now().isoformat()
                }).execute()
                count += 1

            print(f"   ✅ Page {page} — {len(publishers)} publishers synced")
            page += 1

            if len(publishers) < 100:
                break

        print(f"   ✅ Trackier Publishers done — Total: {count}")
        log_sync("trackier_publishers", "success", records=count)

    except Exception as e:
        print(f"   ❌ Error: {e}")
        log_sync("trackier_publishers", "error", error=str(e))


# =====================================================
# TRACKIER — FETCH PERFORMANCE REPORT (Stats)
# =====================================================
def fetch_trackier_stats():
    print("\n💰 Fetching Trackier Performance Stats...")
    headers  = {"X-Api-Key": TRACKIER_API_KEY}
    url      = f"{TRACKIER_BASE_URL}/api/v2/report/campaign"
    today    = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    count    = 0

    try:
        response = safe_get(url, headers, params={
            "start_date": yesterday,
            "end_date":   today,
            "limit":      500,
            "page":       1
        })

        if not response:
            log_sync("trackier_stats", "error", error="No response")
            return

        print(f"   📡 API Status: {response.status_code}")

        if response.status_code != 200:
            # Try alternative endpoint
            url2 = f"{TRACKIER_BASE_URL}/api/v2/reports/campaign"
            response = safe_get(url2, headers, params={
                "start_date": yesterday,
                "end_date":   today,
                "limit":      500
            })
            if not response or response.status_code != 200:
                error_msg = f"HTTP {response.status_code if response else 'None'}"
                print(f"   ❌ {error_msg}")
                log_sync("trackier_stats", "error", error=error_msg)
                return

        data = response.json()

        # Try different response structures
        records = (
            data.get("data", []) or
            data.get("records", []) or
            data.get("report", []) or
            data.get("campaigns", []) or
            []
        )

        for record in records:
            campaign_id = str(record.get("campaign_id") or record.get("id") or "")
            supabase.table("trackier_conversions").upsert({
                "conversion_id": str(record.get("id") or record.get("_id") or f"stat_{campaign_id}_{today}"),
                "campaign_id":   campaign_id,
                "publisher_id":  str(record.get("publisher_id") or ""),
                "goal_value":    str(record.get("goal_value") or ""),
                "revenue":       float(record.get("revenue") or 0),
                "payout":        float(record.get("payout") or 0),
                "status":        str(record.get("status") or ""),
                "created_at":    today,
                "synced_at":     datetime.now().isoformat()
            }).execute()
            count += 1

        print(f"   ✅ Trackier Stats done — Total: {count} records")
        log_sync("trackier_stats", "success", records=count)

    except Exception as e:
        print(f"   ❌ Error: {e}")
        log_sync("trackier_stats", "error", error=str(e))


# =====================================================
# APPFLYER — STEP 1: DISCOVER ALL APPS AUTOMATICALLY
# =====================================================
def fetch_all_appflyer_apps():
    print("\n🔍 Discovering ALL Appflyer apps...")
    headers = {"Authorization": f"Bearer {APPFLYER_API_TOKEN}"}
    apps    = []

    # Try multiple known Appflyer app listing endpoints
    endpoints = [
        "https://hq1.appsflyer.com/api/mng/apps/v2",
        "https://hq1.appsflyer.com/api/mng/apps",
        "https://hq1.appsflyer.com/hq/api/user/apps"
    ]

    for endpoint in endpoints:
        print(f"   🔗 Trying: {endpoint}")
        response = safe_get(endpoint, headers)

        if not response:
            continue

        print(f"   📡 Status: {response.status_code}")

        if response.status_code == 200:
            try:
                data = response.json()
                # Handle different response structures
                raw_apps = (
                    data if isinstance(data, list) else
                    data.get("apps", []) or
                    data.get("data", []) or
                    []
                )

                for app in raw_apps:
                    app_id   = app.get("app_id") or app.get("id") or app.get("appId")
                    app_name = app.get("app_name") or app.get("name") or app.get("appName", "Unknown")
                    platform = app.get("platform") or app.get("os", "unknown")

                    if not app_id:
                        continue

                    supabase.table("appflyer_apps").upsert({
                        "app_id":     str(app_id),
                        "app_name":   str(app_name),
                        "platform":   str(platform),
                        "is_active":  True,
                        "updated_at": datetime.now().isoformat()
                    }).execute()

                    apps.append({
                        "app_id":   str(app_id),
                        "app_name": str(app_name)
                    })
                    print(f"   📱 Found: {app_name} ({app_id})")

                if apps:
                    break  # Stop trying endpoints once we have apps

            except Exception as e:
                print(f"   ⚠️  Parse error: {e}")
                continue

    if not apps:
        print("   ⚠️  Could not auto-discover apps via API")
        print("   📋 Loading apps from Supabase (previously stored)...")
        try:
            result = supabase.table("appflyer_apps").select("*").eq("is_active", True).execute()
            apps   = [{"app_id": r["app_id"], "app_name": r["app_name"]} for r in result.data]
            print(f"   ✅ Loaded {len(apps)} apps from database")
        except Exception as e:
            print(f"   ❌ Could not load from database: {e}")

    print(f"\n   ✅ Total apps to process: {len(apps)}")
    log_sync("appflyer_app_discovery", "success", records=len(apps))
    return apps


# =====================================================
# APPFLYER — STEP 2: PULL STATS FOR EVERY APP
# =====================================================
def fetch_appflyer_stats_for_all_apps(apps):
    if not apps:
        print("\n⚠️  No Appflyer apps to fetch stats for.")
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
            response = safe_get(url, headers, params={
                "from":     yesterday,
                "to":       today,
                "timezone": "Asia/Dubai"
            })

            if not response:
                continue

            if response.status_code == 404:
                print(f"      ⚠️  No data for {app_name}")
                continue

            if response.status_code != 200:
                print(f"      ❌ HTTP {response.status_code}")
                continue

            lines = response.text.strip().split("\n")
            if len(lines) <= 1:
                print(f"      ⚠️  Empty response for {app_name}")
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

            print(f"      ✅ {count} rows synced")
            total += count

        except Exception as e:
            print(f"      ❌ Error: {e}")
            continue

    print(f"\n   ✅ Appflyer complete — {total} rows across {len(apps)} apps")
    log_sync("appflyer_stats_all_apps", "success", records=total)


# =====================================================
# MASTER SYNC
# =====================================================
def run_full_sync():
    print(f"\n{'='*55}")
    print(f"🤖 AGENT 2 v3.0 — Sync Started {datetime.now()} UTC")
    print(f"   Trackier URL: {TRACKIER_BASE_URL}")
    print(f"{'='*55}")

    fetch_trackier_campaigns()
    fetch_trackier_publishers()
    fetch_trackier_stats()

    apps = fetch_all_appflyer_apps()
    fetch_appflyer_stats_for_all_apps(apps)

    print(f"\n{'='*55}")
    print(f"✅ AGENT 2 — Sync Complete {datetime.now()}")
    print(f"{'='*55}\n")


# =====================================================
# ENTRY POINT
# =====================================================
if __name__ == "__main__":
    print("🤖 Agent 2 v3.0 — Starting up...")
    print(f"   Trackier: {TRACKIER_BASE_URL}")

    run_full_sync()

    schedule.every(6).hours.do(run_full_sync)
    schedule.every().day.at("03:00").do(run_full_sync)

    print("⏰ Scheduler active — syncing every 6 hours")

    while True:
        schedule.run_pending()
        time.sleep(60)
