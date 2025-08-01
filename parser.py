import json
import re

INPUT_FILE = 'input.txt'
OUTPUT_FILE = 'items.json'

def parse_raw_text_to_json():
    """
    거래 내역 텍스트 파일을 읽어 items.json 형식으로 변환합니다.
    (숫자로 시작해서 상태 값으로 끝나는 패턴을 인식)
    """
    try:
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            raw_text = f.read()
    except FileNotFoundError:
        print(f"오류: '{INPUT_FILE}' 파일을 찾을 수 없습니다.")
        print("거래 내역을 복사한 'input.txt' 파일을 생성해주세요.")
        with open(INPUT_FILE, 'w', encoding='utf-8') as f:
            f.write("여기에 마켓플레이스 거래 내역을 붙여넣으세요.")
        return

    # "숫자로 시작"해서 "상태(완료, 취소됨, 만료됨 등)로 끝나는" 블록을 찾음
    # re.DOTALL은 개행 문자(\n)도 . 에 포함시켜 여러 줄을 한 번에 찾게 함
    # re.MULTILINE은 각 줄의 시작(^)과 끝($)을 인식하게 함
    pattern = re.compile(r'^\d[\d,]*.*?^(?:완료|취소됨|만료됨)$', re.DOTALL | re.MULTILINE)
    blocks = pattern.findall(raw_text)
    
    if not blocks:
        print("오류: 텍스트에서 유효한 거래 내역 패턴을 찾지 못했습니다.")
        print("데이터가 '숫자'로 시작해서 '완료', '취소됨', '만료됨' 중 하나로 끝나는지 확인해주세요.")
        return
        
    parsed_items = []
    print(f"총 {len(blocks)}개의 거래 내역을 발견했습니다. 파싱을 시작합니다...")

    for i, block in enumerate(blocks):
        # 블록 내의 빈 줄들을 제거하고 라인별로 나눔
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        
        if len(lines) < 8:
            print(f"  - 경고: {i+1}번째 블록의 정보가 부족하여 건너뜁니다. 내용: {block}")
            continue

        try:
            # --- 이 부분이 수정되었습니다 ---
            # 가격에서 쉼표(,)를 제거한 후 숫자로 변환
            price = int(lines[0].replace(',', ''))
            # ---------------------------

            name = lines[1]
            item_type = lines[2]
            rarity = lines[3]
            season = lines[4]
            
            # '유형', '유효일', '상태'를 직접 찾아서 더 안정적으로 추출
            transaction_type = next((line for line in lines if "주문" in line), "")
            transaction_status = lines[-1] # 상태는 항상 마지막 줄에 있음

            date_line_index = -1
            for idx, line in enumerate(lines):
                if "유효일" in line:
                    date_line_index = idx + 1
                    break
            
            if not transaction_type or date_line_index == -1:
                print(f"  - 경고: {i+1}번째 블록에서 거래 유형 또는 날짜를 찾지 못해 건너뜁니다.")
                continue

            transaction_date_raw = lines[date_line_index]
            date_parts = re.findall(r'\d+', transaction_date_raw)
            transaction_date = f"{date_parts[0]}-{int(date_parts[1]):02d}-{int(date_parts[2]):02d}"

            item_data = {
                "item_id": "", # 사용자가 직접 채워야 할 필드
                "price": price,
                "name": name,
                "type": item_type,
                "rarity": rarity,
                "season": season,
                "transaction_type": transaction_type,
                "transaction_date": transaction_date,
                "status": transaction_status # 상태 정보도 추가
            }
            parsed_items.append(item_data)
            
        except (ValueError, IndexError) as e:
            print(f"  - 오류: {i+1}번째 블록을 파싱하는 중 문제가 발생했습니다. 건너뜁니다. (오류: {e}, 블록: {block})")
            continue
    
    # 기존 items.json이 있다면 내용을 유지하고 새로운 내용만 추가
    try:
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            existing_items = json.load(f)
        print(f"기존 '{OUTPUT_FILE}' 파일을 불러왔습니다. 새로운 내용을 추가합니다.")
        
        # 중복을 방지하기 위해 기존에 없는 아이템만 추가 (이름, 날짜, 가격으로 식별)
        existing_signatures = { (item['name'], item['transaction_date'], item['price']) for item in existing_items }
        new_items_to_add = [
            item for item in parsed_items 
            if (item['name'], item['transaction_date'], item['price']) not in existing_signatures
        ]
        
        final_items = existing_items + new_items_to_add
        print(f"{len(new_items_to_add)}개의 새로운 거래 내역이 추가되었습니다.")
        
    except (FileNotFoundError, json.JSONDecodeError):
        # 파일이 없거나 비어있으면 새로 생성
        final_items = parsed_items
        print(f"기존 파일이 없어, 새로 파싱된 {len(final_items)}개의 내용으로 파일을 생성합니다.")

    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(final_items, f, ensure_ascii=False, indent=2)
        print(f"\n파싱 완료! '{OUTPUT_FILE}' 파일이 업데이트되었습니다.")
        print(f"이제 '{OUTPUT_FILE}' 파일을 열어 각 아이템의 'item_id' 값을 직접 채워주세요.")
    except Exception as e:
        print(f"오류: 결과를 파일로 저장하는 중 문제가 발생했습니다. (오류: {e})")


if __name__ == "__main__":
    parse_raw_text_to_json()