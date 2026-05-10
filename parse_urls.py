import json
import os
import re
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Any

async def fetch_url_info(session: aiohttp.ClientSession, url: str, date: str) -> Dict[str, Any]:
    original_url = url
    fetched_url = url
    
    # Rewrite x.com or twitter.com to fixupx.com
    if "x.com" in url or "twitter.com" in url:
        fetched_url = url.replace("twitter.com", "fixupx.com").replace("x.com", "fixupx.com")
    
    try:
        # fixvx/vxtwitter/fixupx often requires a proper User-Agent
        async with session.get(fetched_url, timeout=15, allow_redirects=True) as response:
            if response.status != 200:
                print(f"Status {response.status} for {fetched_url}")
                return None
            
            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')
            
            description = ""
            if any(p in fetched_url for p in ["fixvx.com", "vxtwitter.com", "fxtwitter.com", "fixupx.com"]):
                # These services use og:description for the tweet content
                meta_desc = (
                    soup.find("meta", property="og:description") or 
                    soup.find("meta", attrs={"name": "twitter:description"}) or
                    soup.find("meta", attrs={"name": "description"})
                )
                
                description = meta_desc["content"] if meta_desc else "No description found"
            else:
                # Other URLs: grab the page title
                description = soup.title.string if soup.title else "No title found"
            
            return {
                "original_url": original_url,
                "fetched_url": fetched_url,
                "date": date,
                "description": description.strip()
            }
    except Exception as e:
        print(f"Error fetching {fetched_url}: {e}")
        return None

async def parse_backups():
    backup_dir = "backup"
    if not os.path.exists(backup_dir):
        print("No backup directory found.")
        return

    # Regex to find URLs
    url_pattern = re.compile(r'https?://[^\s<>"]+|www\.[^\s<>"]+')
    
    tasks = []
    all_parsed_urls = []
    seen_urls = set()

    async with aiohttp.ClientSession(
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"},
        connector=aiohttp.TCPConnector(ssl=False)
    ) as session:
        for filename in os.listdir(backup_dir):
            if filename.endswith(".json") and filename != "parsed.json":
                with open(os.path.join(backup_dir, filename), "r", encoding="utf-8") as f:
                    try:
                        messages = json.load(f)
                        for msg in messages:
                            text = msg.get("text") or ""
                            date = msg.get("date")
                            urls = url_pattern.findall(text)
                            for url in urls:
                                if url not in seen_urls:
                                    seen_urls.add(url)
                                    tasks.append(fetch_url_info(session, url, date))
                    except json.JSONDecodeError:
                        continue

        if tasks:
            print(f"Found {len(tasks)} unique URLs. Fetching info...")
            results = await asyncio.gather(*tasks)
            all_parsed_urls = [r for r in results if r is not None]

    output_path = os.path.join(backup_dir, "parsed.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_parsed_urls, f, ensure_ascii=False, indent=2)
    
    print(f"Done. Saved {len(all_parsed_urls)} results to {output_path}")

if __name__ == "__main__":
    asyncio.run(parse_backups())
