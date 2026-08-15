import json
import hashlib
import os
import re
from sentence_transformers import SentenceTransformer

# 動態設定：控制哪些欄位需要 Embedding，哪些要做成節點與關聯
CONFIG = {
    "embedding_fields": ["Description"],
    "relation_fields": {
        "CuisineClasses": "Cuisine",
        "City": "City",
        "Town": "Town",
        "Images": "Image"
    },
    # 由於 CKIP 沒有釋出 1024 維的版本，我們改用微軟開源的跨語言頂級模型 (1024維)
    # 此模型對繁體中文有絕佳的支援度，且並非中國大陸的模型
    "embedding_model": "intfloat/multilingual-e5-large"
}

def generate_md5(text):
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def clean_address(city, town, address):
    if not address:
        return ""
    if city and address.startswith(city):
        address = address[len(city):]
    if town and address.startswith(town):
        address = address[len(town):]
    return address.strip()

def parse_weekly_service_times(info_str):
    if not info_str or not str(info_str).strip():
        return None, "Empty value"
        
    info_str = str(info_str).strip()
    
    # Check for times
    times = re.findall(r'(\d{1,2}:\d{2})', info_str)
    if not times:
        if "24小時" in info_str or "24 hours" in info_str:
            res = {}
            for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
                res[d] = {"open": "00:00", "close": "23:59"}
            return res, ""
        return None, "No time format (HH:MM) found"
        
    def get_open_close(text):
        t_list = re.findall(r'(\d{1,2}:\d{2})', text)
        if not t_list:
            return "", ""
        parsed_times = []
        for t in t_list:
            try:
                parts = t.split(':')
                h, m = int(parts[0]), int(parts[1])
                parsed_times.append((h, m, f"{h:02d}:{m:02d}"))
            except:
                continue
        if not parsed_times:
            return "", ""
        parsed_times.sort()
        return parsed_times[0][2], parsed_times[-1][2]

    # Check for complex specific days with multiple different time intervals
    distinct_times = set(times)
    has_specific_days = any(k in info_str for k in ["星期", "週一", "週二", "週三", "週四", "週五", "週六", "週日", "禮拜"])
    
    if has_specific_days and len(distinct_times) > 2:
        return None, "Complex format with multiple specific day times"

    weekday_text = info_str
    weekend_text = info_str
    
    if any(k in info_str for k in ["假日", "週末", "平日", "例假日"]):
        parts = re.split(r'(假日|週末|週六|週日|例假日)', info_str)
        weekend_idx = -1
        for i, p in enumerate(parts):
            if p in ["假日", "週末", "週六", "週日", "例假日"]:
                weekend_idx = i
                break
        if weekend_idx != -1:
            weekday_text = "".join(parts[:weekend_idx])
            weekend_text = "".join(parts[weekend_idx:])
            
    wd_open, wd_close = get_open_close(weekday_text)
    we_open, we_close = get_open_close(weekend_text)
    
    if not wd_open and not we_open:
        return None, "Failed to parse time"
        
    if not wd_open and we_open:
        wd_open, wd_close = we_open, we_close
    elif not we_open and wd_open:
        we_open, we_close = wd_open, wd_close
        
    # Detect explicit closed days
    closed_days = set()
    for day_name, idx in [("一", 0), ("二", 1), ("三", 2), ("四", 3), ("五", 4), ("六", 5), ("日", 6)]:
        if re.search(f"(星期|週|禮拜){day_name}?[^\d]*(公休|休息|休館|未營業)", info_str):
            closed_days.add(idx)

    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    res = {}
    for i, d in enumerate(days):
        if i in closed_days:
            res[d] = [{"open": "", "close": ""}, {"open": "", "close": ""}]
        elif i < 5:
            res[d] = [{"open": wd_open, "close": wd_close}, {"open": "", "close": ""}]
        else:
            res[d] = [{"open": we_open, "close": we_close}, {"open": "", "close": ""}]
            
    return res, ""

def get_cuisine_class_name(codes):
    cuisine_map = {
        1: '台灣小吃/台菜', 2: '中式料理', 3: '港式料理', 4: '日式料理', 5: '韓式料理',
        96: '南亞料理', 97: '東南亞料理', 98: '美式/歐式料理', 99: '其他異國料理',
        100: '夜市小吃', 101: '甜點冰品', 102: '麵包糕點', 103: '非酒精飲品',
        104: '酒類飲品', 105: '燒烤/鐵板燒', 106: '火鍋', 107: '海鮮', 108: '牛排',
        109: '速食', 110: '連鎖餐飲', 111: '吃到飽', 112: '便當/自助餐',
        113: '牛肉麵', 114: '粥品', 115: '地方特產', 116: '伴手禮/禮盒',
        200: '純素飲食', 201: '素食飲食', 202: '清真飲食', 203: '無麩質飲食',
        204: '健康飲食', 254: '其他'
    }
    return [cuisine_map.get(c, f"料理類別_{c}") for c in codes]

def main():
    print(f"載入 Embedding 模型: {CONFIG['embedding_model']} ...")
    model = SentenceTransformer(CONFIG['embedding_model'])
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = script_dir
    input_file = os.path.join(base_dir, "資料集", "RestaurantList.json")
    output_file = os.path.join(base_dir, "cleaned_restaurants.json")
    report_file = os.path.join(base_dir, "cleaning_report.json")
    
    print(f"讀取原始資料: {input_file}")
    # 使用 utf-8-sig 來避開 BOM 錯誤
    with open(input_file, 'r', encoding='utf-8-sig') as f:
        data = json.load(f)
        
    restaurants = data.get("Restaurants", [])
    cleaned_restaurants = []
    cleaning_report = []
    
    print(f"開始處理 {len(restaurants)} 筆餐廳資料...")
    for i, r in enumerate(restaurants):
        r_id = r.get("RestaurantID")
        r_name = r.get("RestaurantName")
        desc = r.get("Description", "")
        lat = r.get("PositionLat")
        lon = r.get("PositionLon")
        website = r.get("WebsiteURL", "")
        service_time_info = r.get("ServiceTimeInfo", "")
        
        # 解析週一至週日的開門與關門時間
        weekly_times, error_msg = parse_weekly_service_times(service_time_info)
        
        if not weekly_times:
            # 格式不符或為空，加入清洗報告
            cleaning_report.append({
                "RestaurantID": r_id,
                "RestaurantName": r_name,
                "ServiceTimeInfo": service_time_info,
                "ErrorReason": error_msg
            })
            # 提供預設空值
            weekly_times = {d: [{"open": "", "close": ""}, {"open": "", "close": ""}] for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]}
        
        postal = r.get("PostalAddress", {})
        city = postal.get("City", "")
        town = postal.get("Town", "")
        raw_address = postal.get("StreetAddress", "")
        address = clean_address(city, town, raw_address)
        
        images = r.get("Images", [])
        cleaned_images = []
        for img in images:
            img_url = img.get("URL", img.get("Url", ""))
            img_name = img.get("Name", "")
            img_desc = img.get("Description", "")
            img_id = img.get("ID")
            
            if not img_url:
                continue
            if not img_id:
                img_id = generate_md5(img_url)
            cleaned_images.append({
                "id": img_id,
                "name": img_name,
                "description": img_desc,
                "url": img_url
            })
            
        raw_cuisines = r.get("CuisineClasses", [])
        cuisines = get_cuisine_class_name(raw_cuisines)
        
        new_r = {
            "RestaurantID": r_id,
            "RestaurantName": r_name,
            "Description": desc,
            "PositionLat": lat,
            "PositionLon": lon,
            "WebsiteURL": website,
            "ServiceTimeInfo": weekly_times,
            "StreetAddress": address,
            "City": city,
            "Town": town,
            "CuisineClasses": cuisines,
            "Images": cleaned_images
        }
        
        for field in CONFIG["embedding_fields"]:
            field_content = new_r.get(field, "")
            if field_content:
                new_r[f"{field}_embedding"] = model.encode(field_content).tolist()
        
        cleaned_restaurants.append(new_r)
        
        if (i + 1) % 100 == 0:
            print(f"已處理 {i + 1} 筆資料...")
            
    print(f"寫入清洗後資料至: {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(cleaned_restaurants, f, ensure_ascii=False, indent=2)
        
    if cleaning_report:
        print(f"發現 {len(cleaning_report)} 筆資料需手動清洗，寫入清洗報告至: {report_file}")
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(cleaning_report, f, ensure_ascii=False, indent=2)
    else:
        print("所有資料皆成功解析，無須人工清洗！")
        
    print("處理完成！請接著執行 import_to_neo4j.py 將其匯入 Neo4j")

if __name__ == "__main__":
    main()
