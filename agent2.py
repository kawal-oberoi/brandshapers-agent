# =====================================================
# BRANDSHAPERS - AGENT 2 (Data Collector)
# Pulls data from Trackier + Appflyer → Supabase
# Runs automatically every 6 hours
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
APPFLYER_APP_ID     = os.environ.get("APPFLYER_APP_ID")

# Connect to Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)


# =====================================================
# HELPER — LOG EVERY SYNC TO DATABASE
# =====================================================
def log_sync(sync_type, status, records=0, error=None):
    try:
        supabase.table("sync_log").insert({
            "sync_type":       sync_type,
            "status":          status,
            "records_synced":  records,
            "error_message":   error,
            "created_at":      datetime.utcnow().isoformat()
        }).execute()
    except Exception as e:
        print(f"⚠️  Could not write to sync_log: {e}")


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
                print(f"❌ Trackier campaigns API error: {data}")
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
                print(f"❌ Trackier publishers API error: {data}")
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
# TRACKIER — FETCH CONVERSIONS (Last 2 Days)
# =====================================================
def fetch_trackier_conversions():
    print("\n💰 Fetching Trackier Conversions...")
    headers    = {"X-Api-Key": TRACKIER_API_KEY}
    url        = "https://api.trackier.com/v2/reports/conversions"
    today      = datetime.utcnow().strftime("%Y-%m-%d")
    yesterday  = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    count      = 0

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
                print(f"❌ Trackier conversions API error: {data}")
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

            print(f"   ✅ Page {page} — {len(conversions)} conversions synced")
            page += 1

            if len(conversions) < 500:
                break

        print(f"   ✅ Trackier Conversions done — Total: {count}")
        log_sync("trackier_conversions", "success", records=count)

    except Exception as e:
        print(f"   ❌ Error: {e}")
        log_sync("trackier_conversions", "error", error=str(e))


# =====================================================
# APPFLYER — FETCH AGGREGATE STATS
# =====================================================
def fetch_appflyer_stats():
    print("\n📱 Fetching Appflyer Stats...")

    if not APPFLYER_APP_ID:
        print("   ⚠️  APPFLYER_APP_ID not set. Skipping.")
        return

    today     = datetime.utcnow().strftime("%Y-%m-%d")
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    headers   = {"Authorization": f"Bearer {APPFLYER_API_TOKEN}"}
    url       = f"https://hq1.appsflyer.com/api/agg-data/export/app/{APPFLYER_APP_ID}/partners_report/v5"
    count     = 0

    try:
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

        if response.status_code != 200:
            print(f"   ❌ Appflyer error {response.status_code}: {response.text[:200]}")
            log_sync("appflyer_stats", "error", error=f"HTTP {response.status_code}")
            return

        lines = response.text.strip().split("\n")
        if len(lines) <= 1:
            print("   ⚠️  No data returned from Appflyer")
            return

        col_headers = [h.strip() for h in lines[0].split(",")]

        for line in lines[1:]:
            values = [v.strip() for v in line.split(",")]
            row    = dict(zip(col_headers, values))

            supabase.table("appflyer_stats").upsert({
                "app_id":       APPFLYER_APP_ID,
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

        print(f"   ✅ Appflyer Stats done — Total: {count} rows")
        log_sync("appflyer_stats", "success", records=count)

    except Exception as e:
        print(f"   ❌ Error: {e}")
        log_sync("appflyer_stats", "error", error=str(e))


# =====================================================
# MASTER SYNC — RUNS ALL COLLECTORS
# =====================================================
def run_full_sync():
    print(f"\n{'='*55}")
    print(f"🤖 AGENT 2 — Full Sync Started at {datetime.utcnow()} UTC")
    print(f"{'='*55}")

    fetch_trackier_campaigns()
    fetch_trackier_publishers()
    fetch_trackier_conversions()
    fetch_appflyer_stats()

    print(f"\n{'='*55}")
    print(f"✅ AGENT 2 — Sync Complete at {datetime.utcnow()} UTC")
    print(f"{'='*55}\n")


# =====================================================
# ENTRY POINT — Runs immediately then every 6 hours
# =====================================================
if __name__ == "__main__":
    print("🤖 Agent 2 — Data Collector is LIVE")
    print("📡 Connecting to Trackier and Appflyer...")

    # Run immediately on startup
    run_full_sync()

    # Schedule every 6 hours
    schedule.every(6).hours.do(run_full_sync)

    # Also run fresh every day at 7 AM Dubai time (3 AM UTC)
    schedule.every().day.at("03:00").do(run_full_sync)

    print("⏰ Agent 2 is now running on schedule (every 6 hours)")

    while True:
        schedule.run_pending()
        time.sleep(60)
