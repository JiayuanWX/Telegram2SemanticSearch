import json
import os
import re
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Any, Optional

async def fetch_with_playwright(url: str) -> Optional[str]:
    """Fallback using playwright to handle JS-heavy or protected sites."""
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            # Set a realistic user agent
            await page.set_extra_http_headers({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            # Try to get og:description, then twitter:description, then title
            description = await page.evaluate("""() => {
                const getMeta = (name) => {
                    const el = document.querySelector(`meta[property="${name}"]`) || document.querySelector(`meta[name="${name}"]`);
                    return el ? el.content : null;
                };
                return getMeta('og:description') || getMeta('twitter:description') || getMeta('description') || document.title;
            }""")
            
            await browser.close()
            return description.strip() if description else None
    except Exception as e:
        print(f"Playwright fallback failed for {url}: {e}")
        return None

async def fetch_url_info(session: aiohttp.ClientSession, url: str, date: str) -> Dict[str, Any]:
    original_url = url
    fetched_url = url
    
    # Twitter handling - only using fixupx.com, no rotation, no playwright fallback
    if "x.com" in url or "twitter.com" in url:
        fetched_url = url.replace("twitter.com", "fixupx.com").replace("x.com", "fixupx.com")
        # Minimal headers to avoid 400 Bad Request
        minimal_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            async with session.get(fetched_url, timeout=10, allow_redirects=True, headers=minimal_headers) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    meta_desc = (
                        soup.find("meta", property="og:description") or 
                        soup.find("meta", attrs={"name": "twitter:description"}) or
                        soup.find("meta", attrs={"name": "description"})
                    )
                    if meta_desc and meta_desc.get("content"):
                        return {
                            "original_url": original_url,
                            "fetched_url": fetched_url,
                            "date": date,
                            "description": meta_desc["content"].strip()
                        }
            print(f"Failed to fetch {original_url} via fixupx.com")
            return None
        except Exception as e:
            print(f"Error fetching {original_url} via fixupx: {e}")
            return None
    
    try:
        # Standard fallback for non-Twitter URLs
        async with session.get(url, timeout=15, allow_redirects=True) as response:
            if response.status in [403, 401]:
                print(f"Status {response.status} for {url}. Trying playwright fallback...")
                pw_desc = await fetch_with_playwright(url)
                if pw_desc:
                    return {
                        "original_url": original_url,
                        "fetched_url": url,
                        "date": date,
                        "description": pw_desc
                    }
                return None
            
            if response.status != 200:
                print(f"Status {response.status} for {url}")
                return None
            
            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')
            
            # For general sites, title is often more reliable than meta if meta is missing
            meta_desc = (
                soup.find("meta", property="og:description") or 
                soup.find("meta", attrs={"name": "twitter:description"}) or
                soup.find("meta", attrs={"name": "description"})
            )
            
            description = meta_desc["content"] if meta_desc and meta_desc.get("content") else (soup.title.string if soup.title else "No description found")
            
            return {
                "original_url": original_url,
                "fetched_url": url,
                "date": date,
                "description": description.strip()
            }
    except Exception as e:
        print(f"Error fetching {url}: {e}. Trying playwright fallback...")
        pw_desc = await fetch_with_playwright(url)
        if pw_desc:
            return {
                "original_url": original_url,
                "fetched_url": url,
                "date": date,
                "description": pw_desc
            }
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
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.google.com/",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        },
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
