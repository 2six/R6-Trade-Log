import json
import re
from datetime import datetime, timezone
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
import time

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
        options.add_argument('--headless=new') # 새로운 헤드리스 모드
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-extensions")
        options.add_argument("--proxy-server='direct://'")
        options.add_argument("--proxy-bypass-list=*")
        options.add_argument("--start-maximized")

        driver = uc.Chrome(options=options, version_main=114)
        print("Driver initialized successfully.")

        for item in items_to_scrape:
            item_id = item.get('item_id')
            if not item_id: continue

            url = f"https://stats.cc/siege/marketplace/{item_id}"
            print(f"Scraping data for: {item.get('name')} ({item_id})")

            try:
                driver.get(url)
                # Cloudflare가 챌린지를 완료할 시간을 줍니다.
                time.sleep(7) 

                html_content = driver.page_source
                soup = BeautifulSoup(html_content, 'lxml')
                
                # "Whoops!"가 있는지 확인하여 봇 탐지를 감지
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
                # 실패한 경우에도 기본 데이터 구조는 유지하되, 크롤링된 값은 null로 채웁니다.
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