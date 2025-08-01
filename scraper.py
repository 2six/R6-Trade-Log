import json
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timezone

ITEMS_FILE = 'items.json'
RESULTS_FILE = 'results.json'

def get_price_from_element(soup, text_pattern):
    """지정된 텍스트 패턴을 포함하는 요소를 찾아 가격을 추출합니다."""
    try:
        # 텍스트를 포함하는 요소를 찾습니다.
        element = soup.find(lambda tag: tag.name == 'div' and re.search(text_pattern, tag.get_text()))
        if not element:
            return None
        
        # 가격 정보는 보통 다음 형제(sibling) 요소에 있습니다.
        price_element = element.find_next_sibling('div')
        if not price_element:
            # 경우에 따라 부모의 다음 형제일 수도 있습니다.
            price_element = element.parent.find_next_sibling('div')
            if not price_element:
                return None

        price_text = price_element.get_text(strip=True).replace('R6 Credits', '').replace(',', '')
        return int(price_text)
    except (ValueError, AttributeError):
        return None

def get_chart_data(soup):
    """스크립트 태그에서 차트 데이터를 추출하여 최고/최저가를 찾습니다."""
    try:
        script_tag = soup.find('script', string=re.compile(r'new Chart\s*\(\s*document\.getElementById\(\'chart-daily\'\)'))
        if not script_tag:
            return None, None
            
        script_content = script_tag.string
        # 데이터 배열을 추출하는 정규식
        match = re.search(r'data:\s*\[((?:\d+\.?\d*,\s*)*\d+\.?\d*)\]', script_content)
        if not match:
            return None, None
            
        prices_str = match.group(1)
        prices = [int(float(p.strip())) for p in prices_str.split(',') if p.strip()]
        
        if not prices:
            return None, None
            
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
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    for item in items_to_scrape:
        item_id = item.get('item_id')
        if not item_id:
            continue

        url = f"https://stats.cc/siege/marketplace/{item_id}"
        print(f"Scraping data for: {item.get('name')} ({item_id})")

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status() # 200 OK가 아니면 예외 발생

            soup = BeautifulSoup(response.text, 'html.parser')

            # 기본 정보 크롤링
            name_en = soup.find('h1').get_text(strip=True) if soup.find('h1') else 'N/A'
            
            tags = []
            tags_header = soup.find('h4', string='Tags')
            if tags_header:
                tags_container = tags_header.find_next_sibling('div')
                if tags_container:
                    tags = [a.get_text(strip=True) for a in tags_container.find_all('a')]

            # 가격 정보 크롤링
            avg_price_24h = get_price_from_element(soup, r'Average price \(24h\)')
            avg_price_7d = get_price_from_element(soup, r'Average price \(7d\)')
            avg_price_1y = get_price_from_element(soup, r'Average price \(1y\)')
            
            # 차트 최고/최저가 크롤링
            daily_max_price, daily_min_price = get_chart_data(soup)

            # 데이터 병합
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

        except requests.RequestException as e:
            print(f"  - Could not fetch data for {item.get('name')}. Error: {e}")
        except Exception as e:
            print(f"  - An error occurred while processing {item.get('name')}. Error: {e}")

    # 최종 결과를 JSON 파일로 저장
    with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(results_data, f, ensure_ascii=False, indent=2)

    print(f"\nScraping finished. Results saved to '{RESULTS_FILE}'.")


if __name__ == "__main__":
    scrape_site()