import json
import os
import re
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
OUTPUT_FILE = os.path.join(REPORTS_DIR, 'my_profits_report.json')
API_URL = "https://public-ubiservices.ubi.com/v1/profiles/me/uplay/graphql"
APP_ID = "80a4a0e8-8797-440f-8f4c-eaba87d0fdda"

# --- 사용자 설정 ---
TRANSACTION_FEE = 0.10
API_CALL_DELAY = 1.0
MAX_RETRIES = 5
RETRY_DELAY = 10

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

# --- 1단계: 현재 보유 자산 및 매수가 확정 ---
def fetch_my_current_assets(session, headers, query):
    print("\n[1단계] 나의 모든 거래 내역 수집 시작...")
    all_trades = []
    offset = 0
    limit = 100
    while True:
        query["variables"]["offset"] = offset
        try:
            res = make_api_call(session, headers, query)[0]
            trades = res.get("data", {}).get("game", {}).get("viewer", {}).get("meta", {}).get("trades")
            if not trades or not trades.get("nodes"):
                break
            
            # 성공한 거래만 필터링
            successful_trades = [t for t in trades["nodes"] if t.get("state") == "Succeeded"]
            all_trades.extend(successful_trades)
            
            if len(trades["nodes"]) < limit:
                break
            offset += limit
            time.sleep(API_CALL_DELAY)
        except Exception as e:
            print(f"  - 거래 내역 수집 중 오류: {e}")
            break
    
    print(f"  - 총 {len(all_trades)}건의 성공한 거래 내역 확인.")
    
    # 시간순(오래된 순)으로 정렬하여 현재 보유 자산을 확정
    all_trades.sort(key=lambda x: x.get("lastModifiedAt", ""))
    
    current_assets = {}
    for trade in all_trades:
        item_info = trade.get("tradeItems", [{}])[0].get("item", {})
        item_id = item_info.get("itemId")
        if not item_id: continue
        
        category = trade.get("category")
        if category == "Buy":
            payment_info = trade.get("payment")
            if not payment_info: continue
            
            current_assets[item_id] = {
                "name": item_info.get("name"),
                "assetUrl": item_info.get("assetUrl"),
                "myBuyPrice": payment_info.get("price"),
                "buyDate": trade.get("lastModifiedAt")
            }
        elif category == "Sell":
            if item_id in current_assets:
                del current_assets[item_id]

    print(f"  - 현재 보유 자산 {len(current_assets)} 종류 확정.")
    return current_assets

# --- 2단계: 보유 자산 현재 시세 및 과거 데이터 조회 ---
def fetch_assets_market_data(session, headers, asset_ids):
    print("\n[2단계] 보유 자산의 시장 데이터 조회 시작...")
    history_q_template = load_json_file(os.path.join(GRAPHQL_DIR, 'GetItemPriceHistory.json'))
    details_q_template = load_json_file(os.path.join(GRAPHQL_DIR, 'GetItemDetails.json'))
    if not history_q_template or not details_q_template:
        return None

    market_data_map = {}
    batch_size = 10
    id_batches = [asset_ids[i:i + batch_size] for i in range(0, len(asset_ids), batch_size)]

    for id_batch in id_batches:
        # --- 요청 1: 가격 이력(History)만 일괄 조회 ---
        history_payloads = []
        for item_id in id_batch:
            h_vars = history_q_template["variables"].copy()
            h_vars["itemId"] = item_id
            history_payloads.append(dict(history_q_template, variables=h_vars))
        
        print(f"  - {len(id_batch)}개 아이템의 [가격 이력] 요청...")
        try:
            history_responses = make_api_call(session, headers, history_payloads)
            
            # 성공한 응답만 임시 저장
            temp_history_data = {}
            for i, res in enumerate(history_responses):
                item_id = id_batch[i]
                if res and not res.get("errors"):
                    temp_history_data[item_id] = res.get("data", {}).get("game", {}).get("marketableItem", {}).get("priceHistory", [])
                else:
                    print(f"    - 가격 이력 조회 실패 (ID: {item_id})")

        except Exception as e:
            print(f"  - [가격 이력] API 호출 중 오류 발생. 이 묶음을 건너뜁니다: {e}")
            continue # 이 묶음 전체 실패 시 다음 묶음으로
            
        time.sleep(API_CALL_DELAY)

        # --- 요청 2: 현재 시세(Details)만 일괄 조회 ---
        details_payloads = []
        for item_id in id_batch:
            d_vars = details_q_template["variables"].copy()
            d_vars["itemId"] = item_id
            details_payloads.append(dict(details_q_template, variables=d_vars))
        
        print(f"  - {len(id_batch)}개 아이템의 [현재 시세] 요청...")
        try:
            details_responses = make_api_call(session, headers, details_payloads)

            # 성공한 응답을 취합하여 최종 데이터맵 구성
            for i, res in enumerate(details_responses):
                item_id = id_batch[i]
                # 가격 이력과 현재 시세가 모두 성공적으로 조회된 경우에만 최종 데이터에 추가
                if item_id in temp_history_data and res and not res.get("errors"):
                    market_data_map[item_id] = {
                        "priceHistory": temp_history_data[item_id],
                        "marketData": res.get("data", {}).get("game", {}).get("marketableItem", {}).get("marketData", {})
                    }
                else:
                     print(f"    - 현재 시세 조회 실패 또는 가격 이력 없음 (ID: {item_id})")

        except Exception as e:
            print(f"  - [현재 시세] API 호출 중 오류 발생. 이 묶음을 건너뜁니다: {e}")
            continue # 이 묶음 전체 실패 시 다음 묶음으로

        time.sleep(API_CALL_DELAY)
        
    print(f"\n  - 최종적으로 {len(market_data_map)}개 자산의 시장 데이터 조회 완료.")
    return market_data_map

# --- 3단계: 수익성 분석 및 보고서 생성 ---
def analyze_and_generate_report(current_assets, market_data_map):
    print("\n[3단계] 수익성 분석 및 최종 보고서 생성 시작...")
    final_report = []

    def _calculate_profit(sell_price, buy_price):
        if sell_price is None or buy_price is None:
            return {"netProfit": None, "profitRatio(%)": None, "isProfitable": None}
        net_profit = (sell_price * (1 - TRANSACTION_FEE)) - buy_price
        profit_ratio = (net_profit / buy_price) * 100 if buy_price > 0 else 0
        return {
            "netProfit": round(net_profit, 2),
            "profitRatio(%)": round(profit_ratio, 2),
            "isProfitable": net_profit > 0
        }

    for item_id, asset_info in current_assets.items():
        if item_id not in market_data_map:
            continue

        data = market_data_map[item_id]
        price_history = data.get("priceHistory", [])
        market_data = data.get("marketData", {})
        
        # 'None' 또는 빈 리스트인 경우를 안전하게 처리하도록 수정
        sell_stats_list = market_data.get("sellStats")
        buy_stats_list = market_data.get("buyStats")

        sell_stats = sell_stats_list[0] if sell_stats_list else {}
        buy_stats = buy_stats_list[0] if buy_stats_list else {}
        
        current_sell = sell_stats.get("lowestPrice")
        current_buy = buy_stats.get("highestPrice")
        my_buy_price = asset_info["myBuyPrice"]

        today = datetime.now(timezone.utc).date()
        
        # 기간별 가격 데이터 추출
        prices_7d = [h for h in price_history if h and h.get('date') and (today - datetime.fromisoformat(h['date']).date()).days < 7]
        prices_14d = [h for h in price_history if h and h.get('date') and (today - datetime.fromisoformat(h['date']).date()).days < 14]

        # 7일/14일 평균가 계산
        avg_prices_7d = [p['averagePrice'] for p in prices_7d if p.get('averagePrice') is not None]
        avg_7d = sum(avg_prices_7d) / len(avg_prices_7d) if avg_prices_7d else current_sell
        
        avg_prices_14d = [p['averagePrice'] for p in prices_14d if p.get('averagePrice') is not None]
        avg_14d = sum(avg_prices_14d) / len(avg_prices_14d) if avg_prices_14d else current_sell

        # 7일/14일 '일일 최고가'의 평균 계산
        high_prices_7d = [p['highestPrice'] for p in prices_7d if p.get('highestPrice') is not None]
        avg_high_7d = sum(high_prices_7d) / len(high_prices_7d) if high_prices_7d else current_sell

        high_prices_14d = [p['highestPrice'] for p in prices_14d if p.get('highestPrice') is not None]
        avg_high_14d = sum(high_prices_14d) / len(high_prices_14d) if high_prices_14d else current_sell

        # 각 기준별 수익성 분석
        profitability = {
            "by_currentPrice": _calculate_profit(current_sell, my_buy_price),
            "by_avg7dPrice": _calculate_profit(avg_7d, my_buy_price),
            "by_avg14dPrice": _calculate_profit(avg_14d, my_buy_price),
        }

        final_report.append({
            "name": asset_info["name"],
            "itemId": item_id,
            "assetUrl": asset_info["assetUrl"],
            "myBuyPrice": my_buy_price,
            "buyDate": asset_info["buyDate"],
            "currentLowestSellPrice": current_sell,
            "currentHighestBuyPrice": current_buy,
            "avgPrice_7d": round(avg_7d, 2) if avg_7d is not None else None,
            "avgPrice_14d": round(avg_14d, 2) if avg_14d is not None else None,
            "avgHighestPrice_7d": round(avg_high_7d, 2) if avg_high_7d is not None else None,
            "avgHighestPrice_14d": round(avg_high_14d, 2) if avg_high_14d is not None else None,
            "estimatedProfitability": profitability
        })

    # 현재가 기준 수익률로 내림차순 정렬
    final_report.sort(key=lambda x: x["estimatedProfitability"]["by_currentPrice"]["profitRatio(%)"] or -9999, reverse=True)
    print(f"  - {len(final_report)}개 보유 자산 분석 완료.")
    return final_report

def main():
    config = load_json_file(CONFIG_FILE)
    tx_history_query = load_json_file(os.path.join(GRAPHQL_DIR, 'GetTransactionsHistory.json'))
    if not config or not tx_history_query:
        return

    headers = {"Authorization": config.get('uplay_token'), "Ubi-AppId": APP_ID, "Ubi-SessionId": config.get('ubi_session_id'), "Content-Type": "application/json", "Ubi-LocaleCode": "ko-KR"}
    session = requests.Session()

    try:
        current_assets = fetch_my_current_assets(session, headers, tx_history_query)
        
        if not current_assets:
            print("\n분석할 보유 자산이 없습니다.")
            return

        asset_ids = list(current_assets.keys())
        market_data_map = fetch_assets_market_data(session, headers, asset_ids)

        if not market_data_map:
            print("\n보유 자산의 시장 데이터를 조회하지 못했습니다.")
            return

        final_report = analyze_and_generate_report(current_assets, market_data_map)
        save_json_file(final_report, OUTPUT_FILE)

    except Exception as e:
        print(f"\n치명적인 오류 발생: {e}")

    print("\n모든 분석 작업이 완료되었습니다.")


if __name__ == "__main__":
    main()