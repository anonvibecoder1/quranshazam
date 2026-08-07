import urllib.request
import re

url = "https://t.me/s/AlminshawiEncyclopedia/7652"
req = urllib.request.Request(url, headers={
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})
html = urllib.request.urlopen(req).read().decode("utf-8", errors="ignore")

# Find message div for post 7652
match = re.search(r'data-post="AlminshawiEncyclopedia/7652".*?</div\s*>\s*</div\s*>', html, re.DOTALL)
if match:
    print("Found message block for 7652:")
    print(match.group(0)[:2000])
else:
    print("Post block not found in s/ page, searching all links:")
    links = re.findall(r'href="([^"]+)"', html)
    for l in links:
        if "7652" in l or "Alminshawi" in l:
            print("Link:", l)
