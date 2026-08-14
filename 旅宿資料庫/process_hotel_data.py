import json
import torch
from sentence_transformers import SentenceTransformer

# 載入 Embedding 模型
# 採用非大陸來源的多語系模型，與餐飲資料集一致 (intfloat/multilingual-e5-large)
# 並設定使用 GPU (CUDA) 執行
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Using device: {device} for embedding model.")
model = SentenceTransformer("intfloat/multilingual-e5-large", device=device, model_kwargs={"use_safetensors": True})

def get_hotel_class_name(class_codes):
    """
    將 HotelClasses 數字轉換為明碼 (依據觀光資料標準V2)
    作為關聯欄位，以陣列形式儲存
    """
    class_map = {
        1: "國際觀光旅館",
        2: "一般觀光旅館",
        3: "一般旅館",
        4: "民宿"
    }
    if not class_codes:
        return []
    return [class_map.get(c, str(c)) for c in class_codes]

def parse_service_time(time_str):
    """
    營業時間統一欄位，包含週一至週日，並考慮一天開放兩個時段。
    建立預設的 JSON 格式讓後續可以手動填空。
    """
    template = {
        "Monday": [{"open": "", "close": ""}, {"open": "", "close": ""}],
        "Tuesday": [{"open": "", "close": ""}, {"open": "", "close": ""}],
        "Wednesday": [{"open": "", "close": ""}, {"open": "", "close": ""}],
        "Thursday": [{"open": "", "close": ""}, {"open": "", "close": ""}],
        "Friday": [{"open": "", "close": ""}, {"open": "", "close": ""}],
        "Saturday": [{"open": "", "close": ""}, {"open": "", "close": ""}],
        "Sunday": [{"open": "", "close": ""}, {"open": "", "close": ""}]
    }
    # 若有原始字串，可在此擴充解析邏輯，目前先回傳模板供手動填空
    return template

def normalize_service_info(service_str):
    """
    ServiceInfo 進行正規化，例如："無線網路,,,,,自行車友善旅宿"
    轉為陣列形式供關聯使用
    """
    if not service_str:
        return []
    services = [s.strip() for s in service_str.split(',') if s.strip()]
    return services

def clean_address(address, city, town):
    """
    地址內不能有縣市與鄉鎮市區 (去除開頭的縣市與鄉鎮市區)
    """
    if not address:
        return ""
    if city and address.startswith(city):
        address = address[len(city):]
    if town and address.startswith(town):
        address = address[len(town):]
    return address.strip()

def process_data(input_file, output_file):
    print("讀取原始 JSON 資料...")
    with open(input_file, 'r', encoding='utf-8-sig') as f:
        data = json.load(f)
    
    hotels = data.get("Hotels", [])
    processed_hotels = []
    
    # 收集所有的 Description 以進行批次 Embedding 加速處理
    descriptions = [h.get("Description", "") or "" for h in hotels]
    
    print("正在執行 Description 的 Embedding (使用 GPU)...")
    embeddings = model.encode(descriptions, batch_size=32, show_progress_bar=True)
    
    print("資料清洗與轉換中...")
    for i, h in enumerate(hotels):
        # 處理地點 (Point 格式)
        lat = h.get("PositionLat")
        lon = h.get("PositionLon")
        location = f"point({{srid:4326, x:{lon}, y:{lat}}})" if lat is not None and lon is not None else None
        
        # 處理地址與縣市鄉鎮
        postal = h.get("PostalAddress", {})
        city = postal.get("City", "")
        town = postal.get("Town", "")
        raw_address = postal.get("StreetAddress", "")
        clean_addr = clean_address(raw_address, city, town)
        
        hotel_data = {
            "HotelID": h.get("HotelID"),
            "HotelName": h.get("HotelName"),
            "Description": h.get("Description"),
            "DescriptionEmbedding": embeddings[i].tolist() if descriptions[i] else None,
            "PositionLat": lat,
            "PositionLon": lon,
            "location": location,
            "HotelClasses": get_hotel_class_name(h.get("HotelClasses", [])),
            "HotelStars": h.get("HotelStars"),
            "City": city,
            "Town": town,
            "StreetAddress": clean_addr,
            "Images": h.get("Images", []),
            "ServiceTimeInfo": parse_service_time(h.get("ServiceTimeInfo", "")),
            "ServiceInfo": normalize_service_info(h.get("ServiceInfo", "")),
            "LowestPrice": h.get("LowestPrice"),
            "CeilingPrice": h.get("CeilingPrice"),
            "UpdateTime": h.get("UpdateTime")
        }
        
        processed_hotels.append(hotel_data)
        
    print(f"將處理好的資料匯出至 {output_file} ...")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(processed_hotels, f, ensure_ascii=False, indent=2)
    print("完成！")

if __name__ == "__main__":
    import os
    base_dir = r"C:\Users\USER\Desktop\play-taiwan-parser\旅宿資料庫"
    input_json = os.path.join(base_dir, r"Hotel-json\HotelList.json")
    output_json = os.path.join(base_dir, "cleaned_hotels.json")
    process_data(input_json, output_json)
