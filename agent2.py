# =====================================================
# BRANDSHAPERS - AGENT 2 (Data Collector) v2.0
# Dynamic App Discovery — No manual App ID needed
# Pulls ALL apps from Appflyer automatically
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
APPFLYER_API_TOKEN  = os.environ.get("APPFLYER_API_TOKEN")

# Connect to Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)


# =====================================================
# HELPER — LOG EVERY SYNC TO DATABASE
# =====================================================
def log_sync(sync_type, status, records=0, error=None):
    try:
        supabase.table("sync_log").insert({
            "sync_type":      sync_type,
            "status":         status,
            "records_synced": records,
            "error_message":  error,
            "created_at":     datetime.utcnow().isoformat()
        }).execute()
    except Exception as e:
        print(f"⚠️  Could not write to sync_log: {e}")


# =====================================================
# APPFLYER — STEP 1: DISCOVER ALL APPS AUTOMATICALLY
# No manual App ID needed ever again
# =====================================================
def fetch_all_appflyer_apps():
    """
    Automatically fetches ALL apps across ALL advertiser 
    accounts in your Appflyer dashboard.
    New advertisers are picked up automatically on next sync.
    """
    print("\n🔍 Discovering ALL apps in Appflyer account...")
    
    headers = {"Authorization": f"Bearer {APPFLYER_API_TOKEN}"}
    url     = "https://hq1.appsflyer.com/api/mng/apps"
    apps    = []
    offset  = 0
    limit   = 100

    try:
        while True:
            response = requests.get(
                url,
                headers=headers,
                params={"limit": limit, "offset": offset},
                timeout=30
            )

            if response.status_code != 200:
                print(f"   ❌ Appflyer app list error {response.status_code}: {response.text[:200]}")
                log_sync("appflyer_app_discovery", "error", error=f"HTTP {response.status_code}")
                return []

            data       = response.json()
            batch      = data.get("apps", [])
            total      = data.get("meta", {}).get("total_items", 0)

            if not batch:
                break

            for app in batch:
                app_id   = app.get("app_id")
                app_name = app.get("app_name", "Unknown")
                platform = app.get("platform", "unknown")

                # Save each discovered app to Supabase
                supabase.table("appflyer_apps").upsert({
                    "app_id":       app_id,
                    "app_name":     app_name,
                    "platform":     platform,
                    "is_active":    True,
                    "updated_at":   datetime.utcnow().isoformat()
                }).execute()

                apps.append({"app_id": app_id, "app_name": app_name, "platform": platform})
                print(f"   📱 Found: {app_name} ({app_id}) — {platform}")

            offset += limit

            # Stop if we have fetched everything
            if offset >= total or len(batch) < limit:
                break

        print(f"\n   ✅ Total apps discovered: {len(apps)}")
        log_sync("appflyer_app_discovery", "success", records=len(apps))
        return apps

    except Exception as e:
        print(f"   ❌ Error discovering apps: {e}")
        log_sync("appflyer_app_discovery", "error", error=str(e))
        return []


# =====================================================
# APPFLYER — STEP 2: PULL STATS FOR EVERY APP
# Loops through all discovered apps automatically
# =====================================================
def fetch_appflyer_stats_for_all_apps(apps):
    """
    Pulls performance stats for every single app discovered.
    When you add a new advertiser in Appflyer,
    it gets picked up here automatically on the next sync.
    """
    if not apps:
        print("\n⚠️  No apps found to fetch stats for.")
        return

    today     = datetime.utcnow().strftime("%Y-%m-%d")
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    headers   = {"Authorization": f"Bearer {APPFLYER_API_TOKEN}"}
    total     = 0

    print(f"\n📊 Fetching stats for {len(apps)} apps...")

    for app in apps:
        app_id   = app["app_id"]
        app_name = app["app_name"]
        count    = 0

        print(f"\n   → {app_name} ({app_id})")

        try:
            url = f"https://hq1.appsflyer.com/api/agg-data/export/app/{app_id}/partners_report/v5"

            response = requests.get(
                url,
                headers=headers,
                params={
                    "from":     yesterday,
                    "to":       today,
                    "timezone": "Asia/Dubai"
                },
                timeout=30
            )

            if response.status_code == 404:
                print(f"      ⚠️  No data yet for {app_name} — skipping")
                continue

            if response.status_code != 200:
                print(f"      ❌ Error {response.status_code} for {app_name}")
                continue

            lines = response.text.strip().split("\n")
            if len(lines) <= 1:
                print(f"      ⚠️  No rows returned for {app_name}")
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
                    "synced_at":    datetime.utcnow().isoformat()
                }).execute()
                count += 1

            print(f"      ✅ {count} rows synced")
            total += count

        except Exception as e:
            print(f"      ❌ Error for {app_name}: {e}")
            log_sync(f"appflyer_stats_{app_id}", "error", error=str(e))
            continue

    print(f"\n   ✅ Appflyer Stats complete — {total} total rows across {len(apps)} apps")
    log_sync("appflyer_stats_all_apps", "success", records=total)


# =====================================================
# TRACKIER — FETCH CAMPAIGNS
# =====================================================
def fetch_trackier_campaigns():
    print("\n📦 Fetching Trackier Campaigns...")
    headers = {"X-Api-Key": TRACKIER_API_KEY}
    url     = "https://api.trackier.com/v2/campaigns"
    count   = 0

    try:
        page = 1
        while True:
            response = requests.get(
                url,
                headers=headers,
                params={"limit": 100, "page": page},
                timeout=30
            )
            data = response.json()

            if not data.get("success"):
                print(f"   ❌ Trackier campaigns error: {data}")
                log_sync("trackier_campaigns", "error", error=str(data))
                break

            campaigns = data.get("data", {}).get("campaigns", [])
            if not campaigns:
                break

            for c in campaigns:
                supabase.table("trackier_campaigns").upsert({
                    "campaign_id": c.get("_id"),
                    "title":       c.get("title"),
                    "status":      c.get("status"),
                    "model":       c.get("comm_type"),
                    "os":          json.dumps(c.get("os", [])),
                    "updated_at":  datetime.utcnow().isoformat()
                }).execute()
                count += 1

            print(f"   ✅ Page {page} — {len(campaigns)} campaigns")
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
    url     = "https://api.trackier.com/v2/publishers"
    count   = 0

    try:
        page = 1
        while True:
            response = requests.get(
                url,
                headers=headers,
                params={"limit": 100, "page": page},
                timeout=30
            )
            data = response.json()

            if not data.get("success"):
                print(f"   ❌ Trackier publishers error: {data}")
                log_sync("trackier_publishers", "error", error=str(data))
                break

            publishers = data.get("data", {}).get("publishers", [])
            if not publishers:
                break

            for p in publishers:
                supabase.table("trackier_publishers").upsert({
                    "publisher_id": p.get("_id"),
                    "name":         p.get("company"),
                    "email":        p.get("email"),
                    "status":       p.get("status"),
                    "updated_at":   datetime.utcnow().isoformat()
                }).execute()
                count += 1

            print(f"   ✅ Page {page} — {len(publishers)} publishers")
            page += 1
            if len(publishers) < 100:
                break

        print(f"   ✅ Trackier Publishers done — Total: {count}")
        log_sync("trackier_publishers", "success", records=count)

    except Exception as e:
        print(f"   ❌ Error: {e}")
        log_sync("trackier_publishers", "error", error=str(e))


# =====================================================
# TRACKIER — FETCH CONVERSIONS (Last 2 Days)
# =====================================================
def fetch_trackier_conversions():
    print("\n💰 Fetching Trackier Conversions...")
    headers   = {"X-Api-Key": TRACKIER_API_KEY}
    url       = "https://api.trackier.com/v2/reports/conversions"
    today     = datetime.utcnow().strftime("%Y-%m-%d")
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    count     = 0

    try:
        page = 1
        while True:
            response = requests.get(
                url,
                headers=headers,
                params={
                    "start_date": yesterday,
                    "end_date":   today,
                    "limit":      500,
                    "page":       page
                },
                timeout=30
            )
            data = response.json()

            if not data.get("success"):
                print(f"   ❌ Trackier conversions error: {data}")
                log_sync("trackier_conversions", "error", error=str(data))
                break

            conversions = data.get("data", {}).get("conversions", [])
            if not conversions:
                break

            for conv in conversions:
                supabase.table("trackier_conversions").upsert({
                    "conversion_id": conv.get("_id"),
                    "campaign_id":   conv.get("campaign_id"),
                    "publisher_id":  conv.get("publisher_id"),
                    "goal_value":    conv.get("goal_value"),
                    "revenue":       conv.get("revenue", 0),
                    "payout":        conv.get("payout", 0),
                    "status":        conv.get("status"),
                    "created_at":    conv.get("created_at"),
                    "synced_at":     datetime.utcnow().isoformat()
                }).execute()
                count += 1

            print(f"   ✅ Page {page} — {len(conversions)} conversions")
            page += 1
            if len(conversions) < 500:
                break

        print(f"   ✅ Trackier Conversions done — Total: {count}")
        log_sync("trackier_conversions", "success", records=count)

    except Exception as e:
        print(f"   ❌ Error: {e}")
        log_sync("trackier_conversions", "error", error=str(e))


# =====================================================
# MASTER SYNC — RUNS ALL COLLECTORS IN ORDER
# =====================================================
def run_full_sync():
    print(f"\n{'='*55}")
    print(f"🤖 AGENT 2 v2.0 — Sync Started {datetime.utcnow()} UTC")
    print(f"{'='*55}")

    # --- TRACKIER ---
    fetch_trackier_campaigns()
    fetch_trackier_publishers()
    fetch_trackier_conversions()

    # --- APPFLYER ---
    # Step 1: Discover all apps dynamically (no manual App ID)
    apps = fetch_all_appflyer_apps()

    # Step 2: Pull stats for every discovered app
    fetch_appflyer_stats_for_all_apps(apps)

    print(f"\n{'='*55}")
    print(f"✅ AGENT 2 — Sync Complete {datetime.utcnow()} UTC")
    print(f"{'='*55}\n")


# =====================================================
# ENTRY POINT — Runs immediately then every 6 hours
# =====================================================
if __name__ == "__main__":
    print("🤖 Agent 2 v2.0 — Dynamic Data Collector LIVE")
    print("📡 No manual App IDs needed — auto-discovers everything")

    # Run once immediately on startup
    run_full_sync()

    # Schedule every 6 hours for fresh data
    schedule.every(6).hours.do(run_full_sync)

    # Full refresh every day at 3 AM UTC (7 AM Dubai time)
    schedule.every().day.at("03:00").do(run_full_sync)

    print("⏰ Running on schedule — every 6 hours automatically")

    while True:
        schedule.run_pending()
        time.sleep(60)
