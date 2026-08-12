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

def extract_service_times(info_str):
    if not info_str:
        return "", "", "", ""
        
    def get_open_close(text):
        times = re.findall(r'(\d{1,2}:\d{2})', text)
        if not times:
            return "", ""
        parsed_times = []
        for t in times:
            try:
                parts = t.split(':')
                h, m = int(parts[0]), int(parts[1])
                parsed_times.append((h, m, t))
            except:
                continue
        if not parsed_times:
            return "", ""
        parsed_times.sort()
        return parsed_times[0][2], parsed_times[-1][2]

    weekday_text = info_str
    weekend_text = info_str
    
    # 若字串中包含區分平假日的關鍵字，進行切分
    if any(k in info_str for k in ["假日", "週末", "平日"]):
        # 利用 regex 切割出包含假日相關字眼的段落
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
    
    # 若某一方沒有解析到時間，則共用解析到的時間
    if not wd_open and we_open:
        wd_open, wd_close = we_open, we_close
    elif not we_open and wd_open:
        we_open, we_close = wd_open, wd_close
        
    return wd_open, wd_close, we_open, we_close

def main():
    print(f"載入 Embedding 模型: {CONFIG['embedding_model']} ...")
    model = SentenceTransformer(CONFIG['embedding_model'])
    
    base_dir = r"C:\Users\lzh08\OneDrive\桌面\日遊所思夜遊所夢資料集\餐飲資料集"
    input_file = os.path.join(base_dir, r"餐飲 - 觀光資訊資料庫\資料集\RestaurantList.json")
    output_file = os.path.join(base_dir, "cleaned_restaurants.json")
    
    print(f"讀取原始資料: {input_file}")
    # 使用 utf-8-sig 來避開 BOM 錯誤
    with open(input_file, 'r', encoding='utf-8-sig') as f:
        data = json.load(f)
        
    restaurants = data.get("Restaurants", [])
    cleaned_restaurants = []
    
    print(f"開始處理 {len(restaurants)} 筆餐廳資料...")
    for i, r in enumerate(restaurants):
        r_id = r.get("RestaurantID")
        r_name = r.get("RestaurantName")
        desc = r.get("Description", "")
        lat = r.get("PositionLat")
        lon = r.get("PositionLon")
        website = r.get("WebsiteURL", "")
        
        # 解析平日與假日的開門與關門時間
        wd_open, wd_close, we_open, we_close = extract_service_times(r.get("ServiceTimeInfo", ""))
        
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
            
        cuisines = r.get("CuisineClasses", [])
        
        new_r = {
            "RestaurantID": r_id,
            "RestaurantName": r_name,
            "Description": desc,
            "PositionLat": lat,
            "PositionLon": lon,
            "WebsiteURL": website,
            "WeekdayOpenTime": wd_open,
            "WeekdayCloseTime": wd_close,
            "WeekendOpenTime": we_open,
            "WeekendCloseTime": we_close,
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
        
    print("處理完成！請接著執行 import_to_neo4j.py 將其匯入 Neo4j")

if __name__ == "__main__":
    main()
