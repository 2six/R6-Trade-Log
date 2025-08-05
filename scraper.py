import json
import requests
import os
from datetime import datetime, timezone

# 상수 정의
ITEMS_FILE = 'items.json'
RESULTS_FILE = 'results.json'
GRAPHQL_QUERY_FILE = os.path.join('graphql', 'GetItemDetails.json')
API_URL = "https://public-ubiservices.ubi.com/v1/profiles/me/uplay/graphql"
APP_ID = "3587dc57-db54-4429-b69a-18b546397706"

def get_data_from_api():
    """
    R6 공식 GraphQL API를 호출하여 아이템 데이터를 가져옵니다.
    """
    # 1. GitHub Secrets에서 인증 정보 가져오기
    uplay_token = os.getenv('UPLAY_TOKEN')
    session_id = os.getenv('UBI_SESSION_ID')

    if not uplay_token or not session_id:
        print("오류: UPLAY_TOKEN 또는 UBI_SESSION_ID가 설정되지 않았습니다.")
        print("GitHub Repository의 Settings > Secrets에 값을 설정해주세요.")
        return

    # 2. 필요한 파일들 읽기
    try:
        with open(ITEMS_FILE, 'r', encoding='utf-8') as f:
            items_to_scrape = json.load(f)
    except FileNotFoundError:
        print(f"오류: '{ITEMS_FILE}'을 찾을 수 없습니다.")
        return

    try:
        with open(GRAPHQL_QUERY_FILE, 'r', encoding='utf-8') as f:
            graphql_template = f.read()
    except FileNotFoundError:
        print(f"오류: '{GRAPHQL_QUERY_FILE}'을 찾을 수 없습니다.")
        return

    # 3. API 요청을 위한 헤더 설정
    headers = {
        "Authorization": uplay_token,
        "Ubi-AppId": APP_ID,
        "Ubi-SessionId": session_id,
        "Content-Type": "application/json"
    }

    final_results = []
    session = requests.Session() # 세션을 사용하여 연결을 재사용합니다.

    for item in items_to_scrape:
        item_id = item.get('item_id')
        if not item_id:
            continue
        
        print(f"Requesting data for: {item.get('name')} ({item_id})")

        # GraphQL 쿼리 본문(body) 생성
        body = graphql_template.replace("{item_id}", item_id)

        try:
            response = session.post(API_URL, headers=headers, data=body, timeout=30)
            response.raise_for_status() # 200 OK가 아니면 예외 발생

            api_data = response.json()
            
            # 응답 데이터에서 필요한 정보 추출
            if api_data.get("errors"):
                 print(f"  - FAILED: GraphQL API returned errors: {api_data['errors']}")
                 raise Exception("GraphQL Error")

            market_item = api_data.get("data", {}).get("game", {}).get("marketableItem", {})
            item_details = market_item.get("item", {})
            market_data = market_item.get("marketData", {})
            
            # 정보 조합
            combined_item = item.copy()
            combined_item.update({
                "name_en": item_details.get("name"),
                "tags": item_details.get("tags", []),
                # 참고: 현재 GraphQL 쿼리로는 24h, 7d 평균 등은 가져오지 않음
                # 이 값들은 priceHistory를 별도로 호출해야 함 (추후 확장 가능)
                "avg_price_24h": None, 
                "avg_price_7d": None,
                "avg_price_1y": None,
                # 현재는 최고 구매가(buy order)와 최저 판매가(sell order)를 가져옴
                "daily_max_price": market_data.get("buyStats", [{}])[0].get("highestPrice"),
                "daily_min_price": market_data.get("sellStats", [{}])[0].get("lowestPrice"),
                "last_updated": datetime.now(timezone.utc).isoformat()
            })
            final_results.append(combined_item)
            print(f"  - Success: '{item_details.get('name')}' data processed.")

        except requests.exceptions.RequestException as e:
            print(f"  - FAILED: An exception occurred while processing {item.get('name')}. Error: {e}")
            # 실패 시에도 기본 데이터 구조는 유지
            failed_item = item.copy()
            failed_item.update({
                "name_en": "API_REQUEST_FAILED", "tags": [], "avg_price_24h": None, "avg_price_7d": None,
                "avg_price_1y": None, "daily_max_price": None, "daily_min_price": None,
                "last_updated": datetime.now(timezone.utc).isoformat()
            })
            final_results.append(failed_item)

    # 최종 결과를 파일에 저장
    with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_results, f, ensure_ascii=False, indent=2)

    print(f"\nAPI requests finished. Results saved to '{RESULTS_FILE}'.")


if __name__ == "__main__":
    get_data_from_api()