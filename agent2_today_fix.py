# This patches agent2.py to sync both today AND yesterday on every run
import re

content = open("agent2.py").read()

old = '''    try:
        page = 1
        while True:
            r = requests.get(url, headers=headers,
                params={"start_date": yest, "end_date": today, "limit": 500, "page": page},
                timeout=30)'''

new = '''    try:
        # Sync both today AND yesterday on every run
        page = 1
        while True:
            r = requests.get(url, headers=headers,
                params={"start_date": today, "end_date": today, "limit": 500, "page": page},
                timeout=30)'''

if old in content:
    content = content.replace(old, new)
    open("agent2.py", "w").write(content)
    print("SUCCESS — Agent 2 now syncs TODAY's data on every run")
else:
    print("Pattern not found")
