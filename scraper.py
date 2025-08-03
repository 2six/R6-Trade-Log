import json
import re
from datetime import datetime, timezone
from requests_html import HTMLSession, MaxRetries
from bs4 import BeautifulSoup

ITEMS_FILE = 'items.json'
RESULTS_FILE = 'results.json'

def get_price_from_element(soup, text_pattern):
    """지정된 텍스트 패턴을 포함하는 요소를 찾아 가격을 추출합니다."""
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
    """스크립트 태그에서 차트 데이터를 추출하여 최고/최저가를 찾습니다."""
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
    """items.json을 읽어 사이트를 크롤링하고 results.json을 생성합니다."""
    try:
        with open(ITEMS_FILE, 'r', encoding='utf-8') as f:
            items_to_scrape = json.load(f)
    except FileNotFoundError:
        print(f"Error: '{ITEMS_FILE}' not found.")
        return

    results_data = []
    session = HTMLSession()

    for item in items_to_scrape:
        item_id = item.get('item_id')
        if not item_id:
            continue

        url = f"https://stats.cc/siege/marketplace/{item_id}"
        print(f"Scraping data for: {item.get('name')} ({item_id})")

        try:
            # --- 이 부분이 핵심 변경 사항입니다 ---
            # requests 대신 HTMLSession을 사용하고, render()로 JavaScript를 실행합니다.
            response = session.get(url, headers={'User-Agent': 'Mozilla/5.0'})
            response.raise_for_status()
            
            # JavaScript가 페이지를 완전히 그리도록 기다립니다. (중요)
            # render() 대신 browser를 직접 사용하여 playwright 옵션을 전달합니다.
            response.html.browser.close() # 기존 브라우저 인스턴스 정리
            browser = session.browser # 새 브라우저 인스턴스 생성
            page = browser.newPage()
            page.goto(url, timeout=60000)
            page.waitForLoadState('networkidle') # 모든 네트워크 요청이 끝날 때까지 대기
            html_content = page.content()
            page.close()
            # ------------------------------------

            soup = BeautifulSoup(html_content, 'lxml') # 더 빠른 lxml 파서 사용

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

        except MaxRetries:
             print(f"  - Could not fetch data for {item.get('name')}. Max retries exceeded, likely due to bot protection.")
        except Exception as e:
            print(f"  - An error occurred while processing {item.get('name')}. Error: {e}")

    session.close() # 세션 종료
    with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(results_data, f, ensure_ascii=False, indent=2)

    print(f"\nScraping finished. Results saved to '{RESULTS_FILE}'.")

if __name__ == "__main__":
    scrape_site()