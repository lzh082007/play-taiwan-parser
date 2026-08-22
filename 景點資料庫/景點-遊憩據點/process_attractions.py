import os
import re
import json
import torch
from sentence_transformers import SentenceTransformer

# 載入 Embedding 模型
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Using device: {device} for embedding model.")
model = SentenceTransformer("intfloat/multilingual-e5-large", device=device)

# 類別代碼對應表 (必須與第一組資料集相同)
class_map = {
    1: "文化類", 2: "生態類", 3: "古蹟類", 4: "廟宇類",
    5: "藝術類", 6: "小吃/特產類", 7: "國家公園類", 8: "國家風景區類",
    9: "休閒農業類", 10: "溫泉類", 11: "自然風景類", 12: "遊憩類",
    13: "體育健身類", 14: "觀光工廠類", 15: "都會公園類", 16: "森林遊樂區類",
    17: "林場類", 18: "其他"
}

# 城市列表
CITIES = [
    "臺北市","新北市","桃園市","臺中市","臺南市","高雄市",
    "基隆市","新竹市","嘉義市",
    "新竹縣","苗栗縣","彰化縣","南投縣","雲林縣","嘉義縣",
    "屏東縣","宜蘭縣","花蓮縣","臺東縣","澎湖縣",
    "金門縣","連江縣",
    "台北市","台中市","台南市","台東縣",
]

def get_field(item, tag):
    """從 XML 項目中提取指定標籤的內容"""
    m = re.search(rf"<{tag}>(.*?)</{tag}>", item, re.DOTALL)
    return m.group(1).strip() if m else ""

def parse_address(addr):
    """解析地址，分離出城市、鄉鎮市區與街道地址"""
    # 移除開頭的郵遞區號 (可能有括號)
    addr = re.sub(r"^[\(\（]?\d{3,5}[\)\）]?\s*", "", addr)
    
    city = ""
    town = ""
    street = addr
    
    # 找出城市
    for c in CITIES:
        if street.startswith(c):
            city = c
            street = street[len(c):].strip()
            break
            
    # 處理城市與鄉鎮市區之間的數字 (例如：高雄市811楠梓區)
    street = re.sub(r"^\d+", "", street).strip()
    
    # 找出鄉鎮市區
    district_match = re.match(r"^([\u4e00-\u9fff]{1,3}(?:區|鄉|鎮|市))", street)
    if district_match:
        town = district_match.group(1)
        street = street[len(town):].strip()
        
    return city, town, street

def parse_service_time(time_str):
    """產生營業時間模板"""
    template = {
        "Monday": [{"open": "", "close": ""}, {"open": "", "close": ""}],
        "Tuesday": [{"open": "", "close": ""}, {"open": "", "close": ""}],
        "Wednesday": [{"open": "", "close": ""}, {"open": "", "close": ""}],
        "Thursday": [{"open": "", "close": ""}, {"open": "", "close": ""}],
        "Friday": [{"open": "", "close": ""}, {"open": "", "close": ""}],
        "Saturday": [{"open": "", "close": ""}, {"open": "", "close": ""}],
        "Sunday": [{"open": "", "close": ""}, {"open": "", "close": ""}]
    }
    return template

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_xml = os.path.join(script_dir, "special_poi_sec.xml")
    output_json = os.path.join(script_dir, "cleaned_attractions.json")
    
    print("開始讀取 XML 檔案...")
    # 讀取 XML，使用 CP950 編碼並以正則表達式解析
    try:
        with open(input_xml, "rb") as f:
            raw = f.read()
        text = raw.decode("cp950", errors="replace")
    except Exception as e:
        print(f"讀取檔案失敗: {e}")
        return

    items = re.findall(r"<ITEM>(.*?)</ITEM>", text, re.DOTALL)
    print(f"共找到 {len(items)} 筆紀錄。")
    
    records = []
    descriptions = []
    
    print("開始解析並轉換資料...")
    for item in items:
        # 提取各欄位資料
        ori_id = get_field(item, "ID")
        name = get_field(item, "NAME")
        toldescribe = get_field(item, "TOLDESCRIBE")
        description_field = get_field(item, "DESCRIPTION")
        addr = get_field(item, "ADD")
        px = get_field(item, "PX")
        py = get_field(item, "PY")
        class1 = get_field(item, "CLASS1")
        tel = get_field(item, "TEL")
        website = get_field(item, "WEBSITE")
        opentime = get_field(item, "OPENTIME")
        
        # 合併描述
        merged_description = ""
        if toldescribe and description_field:
            merged_description = toldescribe + "\n" + description_field
        elif toldescribe:
            merged_description = toldescribe
        elif description_field:
            merged_description = description_field
            
        descriptions.append(merged_description)
        
        # 解析地址
        city, town, street = parse_address(addr)
        
        # 處理分類
        attr_classes = []
        if class1:
            try:
                class_int = int(class1)
                attr_classes = [class_map.get(class_int, str(class1))]
            except ValueError:
                attr_classes = [class1]
                
        # 解析經緯度
        pos_lon = float(px) if px else None
        pos_lat = float(py) if py else None
        location_str = f"point({{srid:4326, x:{px}, y:{py}}})" if px and py else None
        
        # 處理圖片
        images_list = []
        for i in range(1, 4):
            pic_url = get_field(item, f"Picture{i}")
            pic_desc = get_field(item, f"picdescribe{i}")
            if pic_url:
                images_list.append({
                    "Name": pic_desc,
                    "Description": pic_desc,
                    "URL": pic_url
                })
                
        # 建立記錄
        record = {
            "AttractionID": ori_id,
            "AttractionName": name,
            "Description": merged_description,
            "City": city,
            "Town": town,
            "StreetAddress": street,
            "PositionLat": pos_lat,
            "PositionLon": pos_lon,
            "location": location_str,
            "AttractionClasses": attr_classes,
            "Phone": tel,
            "Website": website,
            "UpdateTime": "",
            "ServiceTimeInfo": parse_service_time(opentime),
            "Images": images_list,
            "DescriptionEmbedding": None, # 稍後填入
            "source": "遊憩據點",
            "raw_opentime": opentime
        }
        records.append(record)
        
    print("開始產生描述向量 (Embedding)...")
    embeddings = model.encode(descriptions, batch_size=32, show_progress_bar=True)
    
    # 統計資訊
    stats = {
        "total": len(records),
        "has_city": 0,
        "has_town": 0,
        "has_images": 0,
        "has_embedding": 0
    }
    
    print("將向量整合回記錄並計算統計資訊...")
    for i, record in enumerate(records):
        if len(descriptions[i].strip()) > 0:
            record["DescriptionEmbedding"] = embeddings[i].tolist()
            stats["has_embedding"] += 1
            
        if record["City"]:
            stats["has_city"] += 1
        if record["Town"]:
            stats["has_town"] += 1
        if record["Images"]:
            stats["has_images"] += 1
            
    print("開始寫入 JSON 檔案...")
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
        
    print("處理完成！")
    print(f"總共處理了 {stats['total']} 筆資料")
    print(f"  - 包含城市 (City): {stats['has_city']} 筆")
    print(f"  - 包含鄉鎮區 (Town): {stats['has_town']} 筆")
    print(f"  - 包含圖片 (Images): {stats['has_images']} 筆")
    print(f"  - 產生向量 (Embedding): {stats['has_embedding']} 筆")

if __name__ == "__main__":
    main()
