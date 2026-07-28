import json
from difflib import SequenceMatcher

articles = json.load(open("news_data.json", encoding="utf-8"))["articles"]

pairs = []
for i, a in enumerate(articles):
    for b in articles[i + 1:]:
        if a["source"] == b["source"]:
            continue
        ratio = SequenceMatcher(None, a["title"].lower(), b["title"].lower()).ratio()
        if ratio > 0.6:
            pairs.append((round(ratio, 2), a["source"], a["title"], b["source"], b["title"]))

pairs.sort(reverse=True)
print(f"{len(pairs)} similar pairs found\n")
for r, s1, t1, s2, t2 in pairs[:10]:
    print(f"{r}  {s1}: {t1}")
    print(f"      {s2}: {t2}\n")