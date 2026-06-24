# =====================================================
# BRANDSHAPERS - AGENT 3 (The Analyst)
# - Reads data from Supabase (collected by Agent 2)
# - Sends daily morning digest at 8 AM India time
# - Sends immediate alerts when anomalies detected
# - Runs every hour to check for problems
# =====================================================

import os
import json
import time
import schedule
import requests
from datetime import datetime, timedelta
from supabase import create_client, Client

# =====================================================
# CONFIGURATION
# =====================================================
SUPABASE_URL        = os.environ.get("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY")
SLACK_BOT_TOKEN     = os.environ.get("SLACK_BOT_TOKEN")

# Slack Channel IDs
CHANNEL_DAILY       = "C0BCV0XH830"   # brandshapers-daily-report
CHANNEL_ALERTS      = "C0BCV12LJ4E"   # brandshapers-alerts
CHANNEL_AGENT1      = "C0BCQP0P99R"   # brandshapers-agent1

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)


# =====================================================
# SLACK — SEND MESSAGE
# =====================================================
def send_slack(channel, message):
    try:
        response = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={
                "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                "Content-Type": "application/json"
            },
            json={
                "channel": channel,
                "text": message,
                "mrkdwn": True
            },
            timeout=10
        )
        result = response.json()
        if result.get("ok"):
            print(f"   ✅ Slack message sent to {channel}")
        else:
            print(f"   ❌ Slack error: {result.get('error')}")
        return result.get("ok", False)
    except Exception as e:
        print(f"   ❌ Slack send failed: {e}")
        return False


# =====================================================
# DATA — FETCH CAMPAIGN PERFORMANCE
# =====================================================
def get_campaign_performance():
    """Get revenue and conversions per campaign for today and yesterday"""
    try:
        today     = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        # Get conversions with campaign titles
        conversions = supabase.table("trackier_conversions")\
            .select("campaign_id, revenue, payout, status, created_at")\
            .gte("created_at", yesterday)\
            .execute()

        campaigns = supabase.table("trackier_campaigns")\
            .select("campaign_id, title, status")\
            .execute()

        # Build campaign lookup
        camp_lookup = {c["campaign_id"]: c["title"] for c in campaigns.data}

        # Aggregate by campaign
        stats = {}
        for conv in conversions.data:
            cid = conv["campaign_id"]
            if cid not in stats:
                stats[cid] = {
                    "title":       camp_lookup.get(cid, f"Campaign {cid}"),
                    "revenue":     0,
                    "payout":      0,
                    "conversions": 0,
                    "approved":    0
                }
            stats[cid]["revenue"]     += float(conv.get("revenue") or 0)
            stats[cid]["payout"]      += float(conv.get("payout") or 0)
            stats[cid]["conversions"] += 1
            if conv.get("status") == "approved":
                stats[cid]["approved"] += 1

        # Sort by revenue
        sorted_stats = sorted(stats.values(), key=lambda x: x["revenue"], reverse=True)
        return sorted_stats

    except Exception as e:
        print(f"   ❌ Campaign performance error: {e}")
        return []


# =====================================================
# DATA — FETCH PUBLISHER PERFORMANCE
# =====================================================
def get_publisher_performance():
    """Get top and bottom publishers by conversions"""
    try:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        conversions = supabase.table("trackier_conversions")\
            .select("publisher_id, revenue, status")\
            .gte("created_at", yesterday)\
            .execute()

        publishers = supabase.table("trackier_publishers")\
            .select("publisher_id, name, email")\
            .execute()

        pub_lookup = {p["publisher_id"]: p["name"] for p in publishers.data}

        stats = {}
        for conv in conversions.data:
            pid = conv["publisher_id"]
            if not pid:
                continue
            if pid not in stats:
                stats[pid] = {
                    "name":        pub_lookup.get(pid, f"Publisher {pid}"),
                    "revenue":     0,
                    "conversions": 0
                }
            stats[pid]["revenue"]     += float(conv.get("revenue") or 0)
            stats[pid]["conversions"] += 1

        sorted_stats = sorted(stats.values(), key=lambda x: x["revenue"], reverse=True)
        return sorted_stats

    except Exception as e:
        print(f"   ❌ Publisher performance error: {e}")
        return []


# =====================================================
# DATA — FETCH APPFLYER STATS
# =====================================================
def get_appflyer_summary():
    """Get installs, clicks and revenue from Appflyer"""
    try:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        today     = datetime.now().strftime("%Y-%m-%d")

        stats = supabase.table("appflyer_stats")\
            .select("app_name, installs, clicks, impressions, revenue, date")\
            .gte("date", yesterday)\
            .execute()

        summary = {
            "total_installs":    0,
            "total_clicks":      0,
            "total_impressions": 0,
            "total_revenue":     0,
            "by_app":            {}
        }

        for row in stats.data:
            app = row.get("app_name", "Unknown")
            summary["total_installs"]    += int(row.get("installs") or 0)
            summary["total_clicks"]      += int(row.get("clicks") or 0)
            summary["total_impressions"] += int(row.get("impressions") or 0)
            summary["total_revenue"]     += float(row.get("revenue") or 0)

            if app not in summary["by_app"]:
                summary["by_app"][app] = {"installs": 0, "clicks": 0, "revenue": 0}
            summary["by_app"][app]["installs"] += int(row.get("installs") or 0)
            summary["by_app"][app]["clicks"]   += int(row.get("clicks") or 0)
            summary["by_app"][app]["revenue"]  += float(row.get("revenue") or 0)

        return summary

    except Exception as e:
        print(f"   ❌ Appflyer summary error: {e}")
        return {}


# =====================================================
# DATA — FETCH OVERALL SUMMARY
# =====================================================
def get_overall_summary():
    """Get total revenue and conversions"""
    try:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        result = supabase.table("trackier_conversions")\
            .select("revenue, payout, status")\
            .gte("created_at", yesterday)\
            .execute()

        total_revenue     = sum(float(r.get("revenue") or 0) for r in result.data)
        total_payout      = sum(float(r.get("payout") or 0) for r in result.data)
        total_conversions = len(result.data)
        approved          = sum(1 for r in result.data if r.get("status") == "approved")
        profit            = total_revenue - total_payout

        return {
            "total_revenue":     total_revenue,
            "total_payout":      total_payout,
            "profit":            profit,
            "total_conversions": total_conversions,
            "approved":          approved
        }

    except Exception as e:
        print(f"   ❌ Summary error: {e}")
        return {}


# =====================================================
# ANOMALY DETECTION — CHECK FOR PROBLEMS
# =====================================================
def check_anomalies():
    """
    Checks for problems every hour and sends
    immediate alerts to brandshapers-alerts channel
    """
    print("\n🔍 Running anomaly detection...")
    alerts = []

    try:
        # Check 1: Campaigns with 0 conversions in last 24 hours
        # that had conversions before
        all_campaigns = supabase.table("trackier_campaigns")\
            .select("campaign_id, title")\
            .eq("status", "active")\
            .execute()

        recent_convs = supabase.table("trackier_conversions")\
            .select("campaign_id")\
            .gte("created_at", (datetime.now() - timedelta(hours=24)).isoformat())\
            .execute()

        active_camp_ids = {c["campaign_id"] for c in all_campaigns.data}
        recent_camp_ids = {c["campaign_id"] for c in recent_convs.data}
        silent_camps    = active_camp_ids - recent_camp_ids

        if silent_camps:
            # Get titles of silent campaigns
            silent_titles = [
                c["title"] for c in all_campaigns.data
                if c["campaign_id"] in silent_camps
            ][:5]  # Show max 5

            if silent_titles:
                alerts.append(
                    f"🔴 *ALERT: Campaigns with zero conversions in last 24hrs*\n" +
                    "\n".join([f"   • {t}" for t in silent_titles]) +
                    (f"\n   _...and {len(silent_camps)-5} more_" if len(silent_camps) > 5 else "")
                )

        # Check 2: Sync health — is Agent 2 running?
        sync_logs = supabase.table("sync_log")\
            .select("sync_type, status, created_at")\
            .order("created_at", desc=True)\
            .limit(10)\
            .execute()

        if sync_logs.data:
            last_sync = sync_logs.data[0]["created_at"]
            last_sync_dt = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
            hours_since = (datetime.now(last_sync_dt.tzinfo) - last_sync_dt).total_seconds() / 3600

            if hours_since > 8:
                alerts.append(
                    f"⚠️ *ALERT: Agent 2 hasn't synced in {int(hours_since)} hours*\n"
                    f"   Last sync: {last_sync}\n"
                    f"   Please check Render dashboard."
                )

        # Send alerts if any found
        if alerts:
            alert_msg = "*🚨 BRANDSHAPERS ALERT*\n\n" + "\n\n".join(alerts)
            send_slack(CHANNEL_ALERTS, alert_msg)
            print(f"   🚨 {len(alerts)} alert(s) sent to Slack")
        else:
            print("   ✅ No anomalies detected")

    except Exception as e:
        print(f"   ❌ Anomaly detection error: {e}")


# =====================================================
# MORNING DIGEST — DAILY REPORT
# =====================================================
def send_morning_digest():
    """
    Sends comprehensive daily report to Slack
    Every day at 8:00 AM India time (2:30 AM UTC)
    """
    print("\n📊 Building morning digest...")

    today     = datetime.now().strftime("%d %B %Y")
    campaigns = get_campaign_performance()
    publishers = get_publisher_performance()
    appflyer  = get_appflyer_summary()
    summary   = get_overall_summary()

    # ── HEADER ──────────────────────────────────────
    msg = f"""🌅 *Good Morning Kawal — Daily Performance Report*
📅 *{today}*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"""

    # ── OVERALL SUMMARY ──────────────────────────────
    if summary:
        msg += f"""💰 *OVERALL SUMMARY (Last 24 Hours)*
• Total Revenue:     ₹{summary.get('total_revenue', 0):,.0f}
• Total Payout:      ₹{summary.get('total_payout', 0):,.0f}
• Profit:            ₹{summary.get('profit', 0):,.0f}
• Total Conversions: {summary.get('total_conversions', 0):,}
• Approved:          {summary.get('approved', 0):,}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"""

    # ── TOP CAMPAIGNS ────────────────────────────────
    if campaigns:
        msg += "📈 *TOP PERFORMING CAMPAIGNS*\n"
        for i, camp in enumerate(campaigns[:5], 1):
            revenue     = camp.get("revenue", 0)
            conversions = camp.get("conversions", 0)
            title       = camp.get("title", "Unknown")[:35]
            msg += f"{i}. {title}\n"
            msg += f"   Revenue: ₹{revenue:,.0f} | Conversions: {conversions}\n"
        msg += "\n"

        # Bottom campaigns
        if len(campaigns) > 5:
            msg += "📉 *LOW PERFORMING CAMPAIGNS*\n"
            for camp in campaigns[-3:]:
                revenue = camp.get("revenue", 0)
                title   = camp.get("title", "Unknown")[:35]
                msg += f"• {title} — ₹{revenue:,.0f}\n"
            msg += "\n"

    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    # ── TOP PUBLISHERS ───────────────────────────────
    if publishers:
        msg += "👥 *TOP PUBLISHERS*\n"
        for i, pub in enumerate(publishers[:5], 1):
            name        = pub.get("name", "Unknown")[:30]
            revenue     = pub.get("revenue", 0)
            conversions = pub.get("conversions", 0)
            msg += f"{i}. {name}\n"
            msg += f"   Revenue: ₹{revenue:,.0f} | Conversions: {conversions}\n"
        msg += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    # ── APPFLYER STATS ───────────────────────────────
    if appflyer and appflyer.get("total_installs", 0) > 0:
        msg += f"""📱 *APPFLYER STATS (Last 24 Hours)*
• Total Installs:   {appflyer.get('total_installs', 0):,}
• Total Clicks:     {appflyer.get('total_clicks', 0):,}
• Total Impressions:{appflyer.get('total_impressions', 0):,}
• Revenue:          ₹{appflyer.get('total_revenue', 0):,.0f}
"""
        # Per app breakdown
        by_app = appflyer.get("by_app", {})
        if by_app:
            msg += "\n*By App:*\n"
            for app_name, stats in list(by_app.items())[:5]:
                msg += f"• {app_name[:30]}: {stats['installs']:,} installs | {stats['clicks']:,} clicks\n"

        msg += "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    # ── FOOTER ───────────────────────────────────────
    msg += "_💬 Ask Agent 1 anything in #brandshapers-agent1_\n"
    msg += "_⚠️ Alerts go to #brandshapers-alerts_\n"
    msg += f"_🕐 Generated at {datetime.now().strftime('%H:%M')} IST_"

    send_slack(CHANNEL_DAILY, msg)
    print("   ✅ Morning digest sent!")


# =====================================================
# SCHEDULER
# =====================================================
def run_scheduler():
    print("⏰ Agent 3 scheduler is running...")
    print("   📅 Daily digest: 8:00 AM India time (02:30 UTC)")
    print("   🔍 Anomaly check: Every hour")

    # Daily morning report at 8 AM India = 02:30 UTC
    schedule.every().day.at("02:30").do(send_morning_digest)

    # Anomaly check every hour
    schedule.every(1).hours.do(check_anomalies)

    while True:
        schedule.run_pending()
        time.sleep(60)


# =====================================================
# ENTRY POINT
# =====================================================
if __name__ == "__main__":
    print("🤖 Agent 3 — The Analyst is LIVE")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Send startup confirmation to Slack
    send_slack(CHANNEL_ALERTS,
        "🟢 *Agent 3 — The Analyst is now LIVE*\n"
        "• Daily reports → #brandshapers-daily-report at 8 AM IST\n"
        "• Anomaly alerts → #brandshapers-alerts (hourly checks)\n"
        "• Agent 1 chat → #brandshapers-agent1 (coming in Phase 3)"
    )

    # Run anomaly check immediately on startup
    check_anomalies()

    # Send morning digest immediately for testing
    print("\n📊 Sending test digest now...")
    send_morning_digest()

    # Start scheduler
    run_scheduler()
