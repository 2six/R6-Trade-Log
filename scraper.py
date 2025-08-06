# scraper.py (최종 완성본: 한글 이름 적용)

import json
import os
import time
from datetime import datetime, timezone
from curl_cffi import requests

# --- 상수 정의 ---
CONFIG_FILE = 'config.json'
TRANSACTIONS_FILE = 'transactions.json'
RESULTS_FILE = 'results.json'
GRAPHQL_DIR = 'graphql'
API_URL = "https://public-ubiservices.ubi.com/v1/profiles/me/uplay/graphql"
APP_ID = "3587dc57-db54-4429-b69a-18b546397706"

# --- 도우미 함수 ---
def load_json_file(file_path):
    """JSON 파일을 안전하게 로드합니다."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"오류: '{file_path}' 파일을 찾을 수 없습니다.")
        return None
    except json.JSONDecodeError:
        print(f"오류: '{file_path}' 파일의 형식이 잘못되었습니다.")
        return None

def save_json_file(data, file_path):
    """JSON 데이터를 파일에 저장합니다."""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"성공: 데이터가 '{file_path}' 파일에 저장되었습니다.")

def make_api_call(session, headers, payload):
    """GraphQL API를 호출하고 응답을 반환합니다."""
    response = session.post(API_URL, headers=headers, json=[payload], timeout=30, impersonate="chrome110")
    
    if response.status_code == 401:
        raise Exception("인증 실패(401). 'config.json'의 토큰/세션 ID가 만료되었습니다.")
    response.raise_for_status()
    
    data = response.json()
    # 일부 단일 요청은 리스트가 아닐 수 있으므로 확인 후 처리
    if isinstance(data, list):
        data = data[0]
        
    if data.get("errors"):
        raise Exception(f"GraphQL API 오류: {data['errors']}")
    return data

# --- 메인 로직 ---
def fetch_all_transactions(session, headers, graphql_query):
    """모든 거래 내역을 페이지네이션을 통해 가져옵니다."""
    all_transactions = []
    offset = 0
    limit = 100
    
    print("\n[1단계] 전체 거래 내역 수집을 시작합니다...")
    while True:
        print(f"  - {offset}번째부터 {limit}개 거래 내역을 요청합니다...")
        graphql_query["variables"]["offset"] = offset
        
        response_data = make_api_call(session, headers, graphql_query)
        transactions_data = response_data.get("data", {}).get("game", {}).get("viewer", {}).get("meta", {}).get("trades", {})
        transactions = transactions_data.get("nodes", [])
        
        if not transactions:
            print("  - 더 이상 가져올 거래 내역이 없습니다.")
            break
            
        all_transactions.extend(transactions)
        
        total_count = transactions_data.get("totalCount", 0)
        if len(all_transactions) >= total_count:
            print("  - 모든 거래 내역을 수집했습니다.")
            break

        offset += len(transactions)
        time.sleep(1)
        
    print(f"총 {len(all_transactions)}개의 거래 내역을 수집했습니다.")
    return all_transactions

def process_item_details(session, headers, transactions):
    """거래 내역을 기반으로 각 아이템의 상세 정보와 가격을 가져옵니다."""
    print("\n[2단계] 아이템별 상세 정보 수집을 시작합니다...")
    
    details_query_template = load_json_file(os.path.join(GRAPHQL_DIR, 'GetItemDetails.json'))
    history_query_template = load_json_file(os.path.join(GRAPHQL_DIR, 'GetItemPriceHistory.json'))
    if not details_query_template or not history_query_template: return []

    final_results = []
    processed_item_ids = set()

    unique_items = []
    for tx in transactions:
        item_info = tx.get("tradeItems", [{}])[0].get("item", {})
        item_id = item_info.get("itemId")
        if item_id and item_id not in processed_item_ids:
            unique_items.append(item_info)
            processed_item_ids.add(item_id)

    print(f"분석할 고유 아이템 개수: {len(unique_items)}개")

    for item_info in unique_items:
        item_id = item_info.get("itemId")
        try:
            print(f"  - 아이템 '{item_info.get('name')}'의 정보를 요청합니다...")
            
            details_query_template["variables"]["itemId"] = item_id
            history_query_template["variables"]["itemId"] = item_id
            
            batch_payload = [details_query_template, history_query_template]
            
            response = session.post(API_URL, headers=headers, json=batch_payload, timeout=30, impersonate="chrome110")
            response.raise_for_status()
            batch_response_data = response.json()
            
            details_data = batch_response_data[0]
            history_data = batch_response_data[1]

            market_item_details = details_data.get("data", {}).get("game", {}).get("marketableItem", {}) or {}
            market_data = market_item_details.get("marketData", {}) or {}
            
            market_item_history = history_data.get("data", {}).get("game", {}).get("marketableItem", {}) or {}
            price_history = market_item_history.get("priceHistory", [])

            result_item = {
                "itemId": item_id,
                "name": item_info.get("name"),
                "type": item_info.get("type"),
                "tags": item_info.get("tags", []),
                "assetUrl": item_info.get("assetUrl"),
                "lowestSellOrder": market_data.get("sellStats", [{}])[0].get("lowestPrice") if market_data.get("sellStats") else None,
                "highestBuyOrder": market_data.get("buyStats", [{}])[0].get("highestPrice") if market_data.get("buyStats") else None,
                "lastSoldPrice": market_data.get("lastSoldAt", [{}])[0].get("price") if market_data.get("lastSoldAt") else None,
                "priceHistory": price_history,
                "lastUpdated": datetime.now(timezone.utc).isoformat()
            }
            final_results.append(result_item)
            time.sleep(1)

        except Exception as e:
            item_name = item_info.get("name", "Unknown")
            print(f"  - 처리 실패: '{item_name}' 처리 중 오류 발생. 오류: {e}")
            
    print(f"총 {len(final_results)}개 아이템의 상세 정보를 수집했습니다.")
    return final_results

def main():
    """메인 실행 함수"""
    config = load_json_file(CONFIG_FILE)
    if not config: return

    # --- 여기가 핵심 수정 사항입니다 ---
    # 당신이 찾아낸 ubi-localecode 헤더를 추가하여 모든 응답을 한글로 받습니다.
    headers = {
        "Authorization": config.get('uplay_token'),
        "Ubi-AppId": APP_ID,
        "Ubi-SessionId": config.get('ubi_session_id'),
        "Content-Type": "application/json",
        "Ubi-LocaleCode": "ko-KR" 
    }
    # ------------------------------------

    session = requests.Session()
    
    try:
        transactions_query = load_json_file(os.path.join(GRAPHQL_DIR, 'GetTransactions.json'))
        if not transactions_query: return
        
        transactions = fetch_all_transactions(session, headers, transactions_query)
        save_json_file(transactions, TRANSACTIONS_FILE)

        results = process_item_details(session, headers, transactions)
        save_json_file(results, RESULTS_FILE)
        
    except Exception as e:
        print(f"\n치명적인 오류 발생: {e}")

    print("\n모든 작업이 완료되었습니다.")

if __name__ == "__main__":
    main()