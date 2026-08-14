import json
import os
import torch
from sentence_transformers import SentenceTransformer

# 載入 Embedding 模型
# 採用非大陸來源的多語系模型 (與餐飲、旅宿一致)
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Using device: {device} for embedding model.")
model = SentenceTransformer("intfloat/multilingual-e5-large", device=device)

def get_attraction_class_name(class_codes):
    """
    將 AttractionClasses 數字轉換為明碼字串
    作為關聯欄位，以陣列形式儲存。
    以下為常見觀光資料庫分類對照表，若有缺漏可自行補上。
    """
    class_map = {
        1: "文化類",
        2: "生態類",
        3: "古蹟類",
        4: "廟宇類",
        5: "藝術類",
        6: "小吃/特產類",
        7: "國家公園類",
        8: "國家風景區類",
        9: "休閒農業類",
        10: "溫泉類",
        11: "自然風景類",
        12: "遊憩類",
        13: "體育健身類",
        14: "觀光工廠類",
        15: "都會公園類",
        16: "森林遊樂區類",
        17: "林場類",
        18: "其他"
    }
    if not class_codes:
        return []
    return [class_map.get(c, str(c)) for c in class_codes]

def clean_address(address, city, town):
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
    
    attractions = data.get("Attractions", [])
    processed_attractions = []
    
    # 收集所有的 Description 以進行批次 Embedding 加速處理
    descriptions = [a.get("Description", "") or "" for a in attractions]
    
    print("正在執行 Description 的 Embedding (使用 GPU)...")
    embeddings = model.encode(descriptions, batch_size=32, show_progress_bar=True)
    
    print("資料清洗與轉換中...")
    for i, a in enumerate(attractions):
        # 複製原始資料以保持大部分欄位不變
        new_a = a.copy()
        
        # 1. 刪除停車資訊
        new_a.pop("ParkingInfo", None)
        new_a.pop("ParkingPositionLat", None)
        new_a.pop("ParkingPositionLon", None)
        
        # 2. 處理地點 (Point 格式)
        lat = new_a.get("PositionLat")
        lon = new_a.get("PositionLon")
        if lat is not None and lon is not None:
            new_a["location"] = f"point({{srid:4326, x:{lon}, y:{lat}}})"
        else:
            new_a["location"] = None
            
        # 3. 將 Class 轉為明碼陣列
        raw_classes = new_a.get("AttractionClasses", [])
        new_a["AttractionClasses"] = get_attraction_class_name(raw_classes)
        
        # 4. 地址處理 (將 City, Town 提到外層，並清理 StreetAddress)
        postal = new_a.get("PostalAddress", {})
        city = postal.get("City", "")
        town = postal.get("Town", "")
        raw_address = postal.get("StreetAddress", "")
        clean_addr = clean_address(raw_address, city, town)
        
        new_a["City"] = city
        new_a["Town"] = town
        new_a["StreetAddress"] = clean_addr
        
        # 5. 加入 Embedding
        if descriptions[i]:
            new_a["DescriptionEmbedding"] = embeddings[i].tolist()
        else:
            new_a["DescriptionEmbedding"] = None
            
        processed_attractions.append(new_a)
        
    print(f"將處理好的資料匯出至 {output_file} ...")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(processed_attractions, f, ensure_ascii=False, indent=2)
    print("清洗處理完成！")

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_json = os.path.join(script_dir, r"資料集\AttractionList.json")
    output_json = os.path.join(script_dir, "cleaned_attractions.json")
    
    if os.path.exists(input_json):
        process_data(input_json, output_json)
    else:
        print(f"找不到輸入檔案: {input_json}")
