import json
import re
from datetime import datetime, timezone
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
import time
import os # 환경 변수를 읽기 위해 os 모듈을 추가합니다.

ITEMS_FILE = 'items.json'
RESULTS_FILE = 'results.json'

def get_price_from_element(soup, text_pattern):
    try:
        element = soup.find(lambda tag: tag.name == 'div' and re.search(text_pattern, tag.get_text()))
        if not element: return None
        price_element = element.find_next_sibling('div')
        if not price_element:
            price_element = element.parent.find_next_sibling('div')
            if not price_element: return None
        price_text = price_element.get_text(strip=True).replace('R6 Credits', '').replace(',', '')
        return int(price_text)
    except (ValueError, AttributeError):
        return None

def get_chart_data(soup):
    try:
        script_tag = soup.find('script', string=re.compile(r'new Chart\s*\(\s*document\.getElementById\(\'chart-daily\'\)'))
        if not script_tag: return None, None
        script_content = script_tag.string
        match = re.search(r'data:\s*\[((?:[\d.]+,?\s*)*)\]', script_content)
        if not match: return None, None
        prices_str = match.group(1).strip()
        if not prices_str: return None, None
        prices = [int(float(p.strip())) for p in prices_str.split(',') if p.strip()]
        if not prices: return None, None
        return max(prices), min(prices)
    except Exception:
        return None, None

def scrape_site():
    try:
        with open(ITEMS_FILE, 'r', encoding='utf-8') as f:
            items_to_scrape = json.load(f)
    except FileNotFoundError:
        print(f"Error: '{ITEMS_FILE}' not found.")
        return

    results_data = []
    driver = None
    try:
        print("Initializing undetected-chromedriver...")
        options = uc.ChromeOptions()
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        
        # --- 여기가 핵심 수정 사항입니다 ---
        # 1. 환경 변수에서 미리 설치된 드라이버의 경로를 읽어옵니다.
        driver_path = os.getenv('CHROME_DRIVER_PATH')
        
        # 2. 드라이버를 직접 다운로드하는 대신, 지정된 경로의 드라이버를 사용합니다.
        if driver_path:
            print(f"Using pre-installed driver from: {driver_path}")
            driver = uc.Chrome(driver_executable_path=driver_path, options=options)
        else:
            # 로컬 환경 등에서 실행될 경우 (환경 변수가 없을 때) 기존 방식대로 동작
            print("CHROME_DRIVER_PATH not set. Falling back to auto-download.")
            driver = uc.Chrome(options=options)
        # ------------------------------------
        
        print("Driver initialized successfully.")

        for item in items_to_scrape:
            item_id = item.get('item_id')
            if not item_id: continue

            url = f"https://stats.cc/siege/marketplace/{item_id}"
            print(f"Scraping data for: {item.get('name')} ({item_id})")

            try:
                driver.get(url)
                time.sleep(7) 

                html_content = driver.page_source
                soup = BeautifulSoup(html_content, 'lxml')
                
                if "Whoops!" in soup.get_text():
                    print("  - FAILED: Bot detection triggered (Whoops! page).")
                    raise Exception("Bot detection")

                name_en = soup.find('h1').get_text(strip=True) if soup.find('h1') else 'N/A'
                
                tags = []
                tags_header = soup.find('h4', string='Tags')
                if tags_header:
                    tags_container = tags_header.find_next_sibling('div')
                    if tags_container:
                        tags = [a.get_text(strip=True) for a in tags_container.find_all('a')]

                avg_price_24h = get_price_from_element(soup, r'Average price \(24h\)')
                avg_price_7d = get_price_from_element(soup, r'Average price \(7d\)')
                avg_price_1y = get_price_from_element(soup, r'Average price \(1y\)')
                
                daily_max_price, daily_min_price = get_chart_data(soup)

                combined_item = item.copy()
                combined_item.update({
                    "name_en": name_en,
                    "tags": tags,
                    "avg_price_24h": avg_price_24h,
                    "avg_price_7d": avg_price_7d,
                    "avg_price_1y": avg_price_1y,
                    "daily_max_price": daily_max_price,
                    "daily_min_price": daily_min_price,
                    "last_updated": datetime.now(timezone.utc).isoformat()
                })
                results_data.append(combined_item)
                print(f"  - Success: '{name_en}' data processed.")

            except Exception as e:
                print(f"  - FAILED during processing {item.get('name')}. Error: {e}")
                failed_item = item.copy()
                failed_item.update({
                    "name_en": "CRAWL_FAILED", "tags": [], "avg_price_24h": None, "avg_price_7d": None,
                    "avg_price_1y": None, "daily_max_price": None, "daily_min_price": None,
                    "last_updated": datetime.now(timezone.utc).isoformat()
                })
                results_data.append(failed_item)

    finally:
        if driver:
            driver.quit()
            print("Driver quit.")
        with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(results_data, f, ensure_ascii=False, indent=2)
        print(f"\nScraping finished. Results saved to '{RESULTS_FILE}'.")

if __name__ == "__main__":
    scrape_site()