# Fix: Better date handling + campaign filtering for Agent 1
content = open("agent1.py").read()

old = '''def fetch_data(question):
    q     = question.lower()
    today = now_ist().strftime("%Y-%m-%d")
    days  = 30 if "month" in q else 7 if "week" in q else 2
    start = (now_ist() - timedelta(days=days)).strftime("%Y-%m-%d")'''

new = '''def fetch_data(question):
    q     = question.lower()
    today = now_ist().strftime("%Y-%m-%d")
    yest  = (now_ist() - timedelta(days=1)).strftime("%Y-%m-%d")

    # Precise date detection
    if "today" in q:
        start = today
    elif "yesterday" in q:
        start = yest
    elif "month" in q or "30 days" in q:
        start = (now_ist() - timedelta(days=30)).strftime("%Y-%m-%d")
    elif "week" in q or "7 days" in q:
        start = (now_ist() - timedelta(days=7)).strftime("%Y-%m-%d")
    else:
        start = yest  # Default: yesterday to today'''

if old in content:
    content = content.replace(old, new)
    open("agent1.py", "w").write(content)
    print("SUCCESS — Date fix applied")
else:
    print("Pattern not found — trying alternative")

# Also fix campaign filtering in ask_claude system prompt
old2 = '''                "system": """You are Agent 1, senior data analyst for Brandshapers Dubai affiliate company.
Talk to Kawal the founder. Be direct. Use rupee symbol.
Use *bold* and bullets for Slack. Data has top_campaigns with revenue/payout/profit.
All dates and times are in IST (India Standard Time).
ALWAYS give actual numbers from top_campaigns.""",'''

new2 = '''                "system": """You are Agent 1, senior data analyst for Brandshapers Dubai affiliate company.
Talk to the user directly. Be direct. Use rupee symbol (₹).
Use *bold* and bullets for Slack formatting.
All dates and times are in IST (India Standard Time).

CRITICAL RULES:
1. If question mentions a specific campaign name — filter top_campaigns to show ONLY that campaign
2. If question says "today" — only show data with today\'s date
3. If question says "yesterday" — only show yesterday\'s data
4. ALWAYS show the exact date range you are reporting on
5. ALWAYS give actual numbers from the data
6. If campaign not found, say so clearly""",'''

if old2 in content:
    content = content.replace(old2, new2)
    open("agent1.py", "w").write(content)
    print("SUCCESS — Claude prompt fix applied")
else:
    print("Prompt pattern not found")

print("Done")
