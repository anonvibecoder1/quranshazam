import requests
import re

url = "https://t.me/AlminshawiEncyclopedia/11098?embed=1"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
r = requests.get(url, headers=headers)
text = r.text

print("Length:", len(text))
print("--- FULL BODY OF EMBED FRAME ---")
print(text)
