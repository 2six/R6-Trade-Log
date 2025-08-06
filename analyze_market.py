import json
import os
import re # 지능형 대기를 위해 re 모듈 추가
import time
from datetime import datetime, timedelta, timezone

try:
    from curl_cffi import requests
except ImportError:
    print("오류: curl_cffi 라이브러리를 찾을 수 없습니다. 'pip install curl_cffi'를 실행해주세요.")
    exit()

# --- 상수 및 설정 ---
CONFIG_FILE = 'config.json'
GRAPHQL_DIR = 'graphql'
REPORTS_DIR = 'reports'
OUTPUT_FILE = os.path.join(REPORTS_DIR, 'market_analysis_report.json')
API_URL = "https://public-ubiservices.ubi.com/v1/profiles/me/uplay/graphql"
APP_ID = "3587dc57-db54-4429-b69a-18b546397706"

# --- 사용자 투자 전략 설정 ---
TARGET_ITEM_COUNT = 200
MIN_PRICE = 101
MAX_PRICE = 4999
MIN_ORDERS = 20
SPREAD_PROFIT_RATIO = 0.10
TRANSACTION_FEE = 0.10
API_CALL_DELAY = 1.0
MAX_RETRIES = 5 # 최대 재시도 횟수
RETRY_DELAY = 10   # 재시도 전 대기 시간 (초)

# --- 도우미 함수 ---
def load_json_file(file_path):
    if not os.path.exists(file_path):
        print(f"오류: '{file_path}' 파일이 없습니다.")
        return None
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"오류: '{file_path}' 파일의 JSON 형식이 잘못되었습니다.")
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
        raise Exception("인증 실패(401)")
    response.raise_for_status()
    return response.json()

# --- 1단계: 데이터 수집 ---
def fetch_market_candidates(session, headers, query):
    candidates = []
    processed_ids = set()
    offset = 0
    limit = 50
    print("\n[1단계] 시장 유망 아이템 후보 수집 시작...")
    while len(candidates) < TARGET_ITEM_COUNT:
        query["variables"]["offset"] = offset
        try:
            res = make_api_call(session, headers, query)[0]
            items = res.get("data", {}).get("game", {}).get("marketableItems", {}).get("nodes", [])
            if not items: break

            for item in items:
                item_id = item.get("item", {}).get("itemId")
                market_data = item.get("marketData")
                if not item_id or item_id in processed_ids or not market_data: continue
                
                sell_stats, buy_stats = market_data.get("sellStats"), market_data.get("buyStats")
                if not sell_stats or not buy_stats: continue
                
                price = sell_stats[0].get("lowestPrice")
                sell_orders, buy_orders = sell_stats[0].get("activeCount"), buy_stats[0].get("activeCount")

                if all(v is not None for v in [price, sell_orders, buy_orders]):
                    if (MIN_PRICE <= price <= MAX_PRICE) and (sell_orders >= MIN_ORDERS) and (buy_orders >= MIN_ORDERS):
                        candidates.append(item)
                        processed_ids.add(item_id)
                if len(candidates) >= TARGET_ITEM_COUNT: break
            
            if len(items) < limit: break
            offset += len(items)
            time.sleep(API_CALL_DELAY)
        except Exception as e:
            print(f"  - 시장 후보 수집 중 오류: {e}")
            break
    print(f"1차 필터링 후, 분석 대상 유망 후보 {len(candidates)}개 선정.")
    return candidates

# --- 2단계: 심층 분석 (수정된 함수) ---
def analyze_deep_dive(session, headers, all_items_map):
    print("\n[2단계] 심층 분석 시작...")
    history_q = load_json_file(os.path.join(GRAPHQL_DIR, 'GetItemPriceHistory.json'))
    if not history_q: return []
    
    analysis_results = []
    batch_size = 10
    item_list = list(all_items_map.values())
    item_batches = [item_list[i:i + batch_size] for i in range(0, len(item_list), batch_size)]

    for batch in item_batches:
        payloads = [dict(history_q, variables=dict(history_q["variables"], itemId=item['item']['itemId'])) for item in batch if item.get('item')]
        if not payloads: continue

        print(f"  - {len(batch)}개 아이템 가격 히스토리 일괄 요청...")
        
        successful_responses = {} # key: itemId, value: response
        payloads_to_retry = {p['variables']['itemId']: p for p in payloads}
        
        for attempt in range(MAX_RETRIES):
            if not payloads_to_retry:
                break

            print(f"    - 시도 {attempt + 1}/{MAX_RETRIES}: {len(payloads_to_retry)}개 아이템 요청...")
            
            current_payload_list = list(payloads_to_retry.values())
            error_str = "" # 오류 메시지 저장을 위해 초기화
            
            try:
                responses = make_api_call(session, headers, current_payload_list)
                
                if not isinstance(responses, list) or len(responses) != len(current_payload_list):
                    raise ValueError(f"API 응답 개수({len(responses)})가 요청 개수({len(current_payload_list)})와 다릅니다.")

                next_retry_payloads = {}
                for i, res in enumerate(responses):
                    item_id_in_req = current_payload_list[i]['variables']['itemId']
                    
                    if res and not res.get("errors"):
                        successful_responses[item_id_in_req] = res
                    else:
                        next_retry_payloads[item_id_in_req] = payloads_to_retry[item_id_in_req]

                payloads_to_retry = next_retry_payloads
                
            except Exception as e:
                error_str = str(e)
                print(f"    - API 호출 중 예외 발생: {error_str}")

            if payloads_to_retry and attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAY
                if "RATE_LIMIT" in error_str:
                    match = re.search(r'try again in (\d+)', error_str)
                    if match:
                        delay = int(match.group(1)) + 1
                        print(f"    - 서버가 요청한 대기 시간({delay-1}초)을 준수합니다.")
                print(f"    - {delay}초 후 실패한 {len(payloads_to_retry)}개 항목에 대해 재시도합니다...")
                time.sleep(delay)
        
        if payloads_to_retry:
            print(f"    - 최대 재시도 후에도 {len(payloads_to_retry)}개 아이템 처리 실패. 이 묶음에서 실패한 아이템은 건너뜁니다.")

        time.sleep(API_CALL_DELAY * 1.5)

        for item in batch:
            try:
                item_id = item.get("item", {}).get("itemId")
                if not item_id or item_id not in successful_responses:
                    continue

                res = successful_responses[item_id]
                
                marketable_item = res.get("data", {}).get("game", {}).get("marketableItem")
                if not marketable_item: continue
                
                price_history = marketable_item.get("priceHistory", [])
                market_data = item.get("marketData")
                if not market_data: continue
                
                sell_stats, buy_stats = market_data.get("sellStats"), market_data.get("buyStats")
                if not sell_stats or not buy_stats: continue

                current_sell = sell_stats[0].get("lowestPrice")
                current_buy = buy_stats[0].get("highestPrice")
                if not current_sell or not current_buy: continue

                today = datetime.now(timezone.utc).date()
                prices_7d = [h['averagePrice'] for h in price_history if h and all(k in h for k in ['date', 'averagePrice']) and h['averagePrice'] is not None and (today - datetime.fromisoformat(h['date']).date()).days < 7]
                avg_7d = sum(prices_7d) / len(prices_7d) if prices_7d else current_sell
                
                prices_14d = [h['averagePrice'] for h in price_history if h and all(k in h for k in ['date', 'averagePrice']) and h['averagePrice'] is not None and (today - datetime.fromisoformat(h['date']).date()).days < 14]
                avg_14d = sum(prices_14d) / len(prices_14d) if prices_14d else current_sell

                analysis_results.append({
                    "name": item.get("item", {}).get("name"),
                    "undervalueRatio_7d(%)": round(((avg_7d - current_sell) / avg_7d) * 100, 2) if avg_7d > 0 else 0,
                    "spread": current_sell - current_buy,
                    "isSpreadProfitable_7d": (current_buy * (1-TRANSACTION_FEE) - current_sell) > (avg_7d * SPREAD_PROFIT_RATIO) if avg_7d > 0 else False,
                    "currentLowestSellPrice": current_sell, "currentHighestBuyPrice": current_buy,
                    "avgPrice_7d": round(avg_7d, 2), "avgPrice_14d": round(avg_14d, 2),
                    "itemId": item_id,
                    "assetUrl": item.get("item", {}).get("assetUrl")
                })
            except Exception as e:
                 print(f"  - 아이템 데이터 처리 중 오류 (ID: {item_id}). 건너뜁니다. 오류: {e}")

    analysis_results.sort(key=lambda x: x.get("undervalueRatio_7d(%)", 0), reverse=True)
    return analysis_results

def main():
    config = load_json_file(CONFIG_FILE)
    market_query = load_json_file(os.path.join(GRAPHQL_DIR, 'GetMarketableItems.json'))
    if not all([config, market_query]): return

    headers = {"Authorization": config.get('uplay_token'), "Ubi-AppId": APP_ID, "Ubi-SessionId": config.get('ubi_session_id'), "Content-Type": "application/json", "Ubi-LocaleCode": "ko-KR"}
    session = requests.Session()
    
    try:
        market_candidates = fetch_market_candidates(session, headers, market_query)
        
        all_items_map = {item['item']['itemId']: item for item in market_candidates if item.get('item')}
        
        if not all_items_map:
            print("\n분석할 아이템이 없습니다.")
        else:
            final_report = analyze_deep_dive(session, headers, all_items_map)
            save_json_file(final_report, OUTPUT_FILE)
            
    except Exception as e:
        print(f"\n치명적인 오류 발생: {e}")

    print("\n모든 분석 작업이 완료되었습니다.")

if __name__ == "__main__":
    main()