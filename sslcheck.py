import ssl, certifi, urllib.request
import truststore
truststore.inject_into_ssl()

print("certifi bundle:", certifi.where())

ctx = ssl.create_default_context(cafile=certifi.where())
try:
    with urllib.request.urlopen("https://techcrunch.com/feed/", context=ctx) as r:
        print("OK with certifi bundle — status", r.status)
except Exception as e:
    print("Still failing with certifi:", e)