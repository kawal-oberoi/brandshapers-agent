# Fix script for Agent 1 — patches the fetch function
import re

content = open('agent1.py').read()

# New fetch function that properly enriches and groups data
new_fetch = '''def fetch_data_for_question(question):
    question_lower = question.lower()
    data           = {}
    today          = datetime.now().strftime("%Y-%m-%d")
    week_ago       = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago      = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    if any(w in question_lower for w in ["month", "30 days", "monthly"]):
        start_date = month_ago
        period     = "last 30 days"
    elif any(w in question_lower for w in ["week", "7 days", "weekly"]):
        start_date = week_ago
        period     = "last 7 days"
    else:
        start_date = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        period     = "last 2 days"

    data["time_range"] = f"{start_date} to {today} ({period})"

    # Fetch campaigns and publishers for lookup
    camps = supabase.table("trackier_campaigns").select("campaign_id, title, status").execute()
    pubs  = supabase.table("trackier_publishers").select("publisher_id, name, email").execute()
    data["publishers"] = pubs.data

    # Fetch ALL conversions with revenue
    convs = supabase.table("trackier_conversions")\
        .select("campaign_id, publisher_id, goal_value, revenue, payout, status, created_at")\
        .gte("created_at", start_date)\
        .order("revenue", desc=True)\
        .limit(500)\
        .execute()

    # Build campaign name lookup
    camp_lookup = {c["campaign_id"]: c["title"] for c in camps.data}

    # Group and enrich by campaign name
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
    total_rev = sum(v["revenue"] for v in by_camp.values())
    total_pay = sum(v["payout"] for v in by_camp.values())

    data["top_campaigns"] = [{"name": k, **v} for k, v in top[:20]]
    data["summary"] = {
        "total_revenue": total_rev,
        "total_payout":  total_pay,
        "total_profit":  total_rev - total_pay,
        "total_records": len(convs.data),
        "with_revenue":  len([c for c in convs.data if float(c.get("revenue") or 0) > 0])
    }

    # Appflyer if relevant
    if any(w in question_lower for w in ["install", "click", "app", "appflyer", "paybis", "novio"]):
        af = supabase.table("appflyer_stats").select("*").gte("date", start_date).execute()
        data["appflyer"] = af.data

    return data'''

# Replace the entire fetch function
pattern = r'def fetch_data_for_question\(question\):.*?(?=\ndef )'
if re.search(pattern, content, re.DOTALL):
    content = re.sub(pattern, new_fetch + '\n\n', content, flags=re.DOTALL)
    open('agent1.py', 'w').write(content)
    print("SUCCESS — fetch function patched perfectly")
else:
    print("ERROR — pattern not found")
