# analyze_market.py (통합 시장 분석 최종본)

import json
import os
import time
from datetime import datetime, timedelta, timezone

try:
    from curl_cffi import requests
except ImportError:
    print("오류: curl_cffi 라이브러리를 찾을 수 없습니다.")
    print("터미널에 'pip install curl_cffi'를 입력하여 설치해주세요.")
    exit()

# --- 상수 및 설정 ---
CONFIG_FILE = 'config.json'
GRAPHQL_DIR = 'graphql'
REPORTS_DIR = 'reports'
OUTPUT_FILE = os.path.join(REPORTS_DIR, 'market_analysis.json')
API_URL = "https://public-ubiservices.ubi.com/v1/profiles/me/uplay/graphql"
APP_ID = "3587dc57-db54-4429-b69a-18b546397706"

# --- 사용자 투자 전략 설정 ---
TARGET_ITEM_COUNT = 200      # 분석할 시장 인기 상위 아이템 개수
MIN_PRICE = 101              # 분석 대상 최소 가격 (100 초과)
MAX_PRICE = 4999             # 분석 대상 최대 가격 (5000 미만)
MIN_ORDERS = 20              # 최소 판매/구매 주문 수 (거래 활성도 필터)
SPREAD_PROFIT_RATIO = 0.10   # N일 평균가의 10% 이상 스프레드 발생 시 '유의미'로 판단

# --- 도우미 함수 ---
def load_json_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"오류: '{file_path}' 파일을 읽는 중 문제 발생. {e}")
        return None

def save_json_file(data, file_path):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n성공: 최종 분석 보고서가 '{file_path}'에 저장되었습니다.")

def make_api_call(session, headers, payload):
    if not isinstance(payload, list):
        payload = [payload]
    response = session.post(API_URL, headers=headers, json=payload, timeout=60, impersonate="chrome110")
    if response.status_code == 401:
        raise Exception("인증 실패(401). 'config.json'의 토큰/세션 ID가 만료되었거나 올바르지 않습니다.")
    response.raise_for_status()
    return response.json()

# --- 메인 로직 ---
def fetch_top_market_items(session, headers, graphql_query):
    """최근 거래가 순으로 정렬된 상위 아이템 목록을 수집하고 1차 필터링합니다."""
    candidate_items = []
    offset = 0
    limit = 50
    
    print(f"\n[1단계] 시장 인기 아이템 수집 및 1차 필터링을 시작합니다...")
    while len(candidate_items) < TARGET_ITEM_COUNT:
        print(f"  - {offset}번째부터 {limit}개 아이템을 요청합니다...")
        graphql_query["variables"]["offset"] = offset
        
        response_data = make_api_call(session, headers, graphql_query)[0]
        items = response_data.get("data", {}).get("game", {}).get("marketableItems", {}).get("nodes", [])
        
        if not items:
            print("  - 더 이상 가져올 아이템이 없습니다.")
            break

        for item in items:
            try:
                market_data = item.get("marketData", {})
                if not market_data: continue

                sell_stats = market_data.get("sellStats", [{}])[0]
                buy_stats = market_data.get("buyStats", [{}])[0]
                
                price = sell_stats.get("lowestPrice")
                sell_orders = sell_stats.get("activeCount", 0)
                buy_orders = buy_stats.get("activeCount", 0)

                if price and (MIN_PRICE <= price <= MAX_PRICE) and (sell_orders >= MIN_ORDERS) and (buy_orders >= MIN_ORDERS):
                    candidate_items.append(item)
                    if len(candidate_items) >= TARGET_ITEM_COUNT:
                        break
            except (IndexError, TypeError):
                continue
        
        offset += len(items)
        if len(items) < limit: break
        time.sleep(1)

    print(f"1차 필터링 후, 분석 대상 유망 후보 아이템 {len(candidate_items)}개를 선정했습니다.")
    return candidate_items

def analyze_items_deep_dive(session, headers, items_to_analyze):
    """선정된 아이템들의 과거 가격을 분석하여 두 가지 투자 전략을 적용합니다."""
    print("\n[2단계] 유망 후보 심층 분석을 시작합니다...")
    
    history_query_template = load_json_file(os.path.join(GRAPHQL_DIR, 'GetItemPriceHistory.json'))
    if not history_query_template: return []

    analysis_results = []
    batch_size = 10
    item_batches = [items_to_analyze[i:i + batch_size] for i in range(0, len(items_to_analyze), batch_size)]

    for batch in item_batches:
        payloads = []
        item_map = {}
        for item in batch:
            item_id = item.get("item", {}).get("itemId")
            if item_id:
                query_copy = json.loads(json.dumps(history_query_template))
                query_copy["variables"]["itemId"] = item_id
                payloads.append(query_copy)
                item_map[item_id] = item

        if not payloads: continue
        
        print(f"  - {len(batch)}개 아이템의 가격 히스토리 일괄 요청 중...")
        try:
            batch_responses = make_api_call(session, headers, payloads)
            time.sleep(1.5)

            for i, response in enumerate(batch_responses):
                history_data = response.get("data", {}).get("game", {}).get("marketableItem", {}) or {}
                price_history = history_data.get("priceHistory", [])
                if not price_history: continue

                # 7일, 14일 평균가 계산
                today = datetime.now(timezone.utc).date()
                recent_prices_7d = [h['averagePrice'] for h in price_history if (today - datetime.fromisoformat(h['date']).date()).days < 7]
                recent_prices_14d = [h['averagePrice'] for h in price_history if (today - datetime.fromisoformat(h['date']).date()).days < 14]

                avg_7d = sum(recent_prices_7d) / len(recent_prices_7d) if recent_prices_7d else 0
                avg_14d = sum(recent_prices_14d) / len(recent_prices_14d) if recent_prices_14d else 0

                original_item_id = payloads[i]["variables"]["itemId"]
                original_item = item_map[original_item_id]
                market_data = original_item.get("marketData", {})
                current_price = market_data.get("sellStats", [{}])[0].get("lowestPrice")
                highest_buy_order = market_data.get("buyStats", [{}])[0].get("highestPrice")
                
                if not current_price or not highest_buy_order: continue
                
                # 전략 1: '존버' 가치 분석
                undervalue_7d = ((avg_7d - current_price) / avg_7d) * 100 if avg_7d > 0 else 0
                undervalue_14d = ((avg_14d - current_price) / avg_14d) * 100 if avg_14d > 0 else 0

                # 전략 2: '스프레드' 차익 분석
                spread = highest_buy_order - current_price
                is_spread_profitable_7d = spread > (avg_7d * SPREAD_PROFIT_RATIO) if avg_7d > 0 else False
                is_spread_profitable_14d = spread > (avg_14d * SPREAD_PROFIT_RATIO) if avg_14d > 0 else False

                analysis_results.append({
                    "name": original_item.get("item", {}).get("name"),
                    "undervalue_ratio_7d(%)": round(undervalue_7d, 2),
                    "undervalue_ratio_14d(%)": round(undervalue_14d, 2),
                    "is_spread_profitable_7d": is_spread_profitable_7d,
                    "is_spread_profitable_14d": is_spread_profitable_14d,
                    "spread": spread,
                    "current_lowest_price": current_price,
                    "current_highest_buy_order": highest_buy_order,
                    "avg_price_7d": round(avg_7d, 2),
                    "avg_price_14d": round(avg_14d, 2),
                    "sell_orders": market_data.get("sellStats", [{}])[0].get("activeCount"),
                    "buy_orders": market_data.get("buyStats", [{}])[0].get("activeCount"),
                    "item_id": original_item_id,
                    "asset_url": original_item.get("item", {}).get("assetUrl")
                })
        except Exception as e:
            print(f"  - 일괄 처리 중 오류 발생: {e}")

    # 최종 정렬: 스프레드 수익 가능성 > 7일 저평가 순으로 정렬
    analysis_results.sort(key=lambda x: (x["is_spread_profitable_7d"], x["undervalue_ratio_7d(%)"]), reverse=True)
    return analysis_results

def main():
    """메인 실행 함수"""
    config = load_json_file(CONFIG_FILE)
    if not config: return

    headers = {
        "Authorization": config.get('uplay_token'),
        "Ubi-AppId": APP_ID,
        "Ubi-SessionId": config.get('ubi_session_id'),
        "Content-Type": "application/json",
        "Ubi-LocaleCode": "ko-KR"
    }

    session = requests.Session()
    
    try:
        market_query = load_json_file(os.path.join(GRAPHQL_DIR, 'GetMarketableItems.json'))
        if not market_query: return
        
        potential_candidates = fetch_top_market_items(session, headers, market_query)
        
        if not potential_candidates:
            print("\n분석할 유망 후보 아이템이 없습니다. 필터링 조건을 확인해보세요.")
        else:
            final_report = analyze_items_deep_dive(session, headers, potential_candidates)
            save_json_file(final_report, OUTPUT_FILE)
        
    except Exception as e:
        print(f"\n치명적인 오류 발생: {e}")

    print("\n모든 분석 작업이 완료되었습니다.")

if __name__ == "__main__":
    main()