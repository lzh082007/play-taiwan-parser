# 遊憩據點資料集 - Neo4j 圖形資料庫匯入規範與 Schema

## 1. 檔案架構與前置作業
- process_attractions.py: 讀取 XML (CP950 編碼), 清洗, 合併描述, GPU Embedding
- crawler_business_hours.py: Google Maps 爬蟲補營業時間
- import_to_neo4j.py: Neo4j 匯入 + 匯入報告

## 2. 圖形資料模型
### 節點
1. (:Attraction) - id(UNIQUE), name, description, lat, lon, location(Point), address, phone, website, update_time, source, description_embedding(1024-dim)
2. (:AttractionClass) - name(UNIQUE)
3. (:City) - name(UNIQUE)  
4. (:Town) - name(UNIQUE)
5. (:Image) - id(UNIQUE, MD5 of URL), url, name, description
6. (:OperatingHours) - dayOfWeek, openTime, closeTime

### 關聯
- (Attraction)-[:HAS_CLASS]->(AttractionClass)
- (Attraction)-[:LOCATED_IN_CITY]->(City)
- (Attraction)-[:LOCATED_IN_TOWN]->(Town)
- (Town)-[:PART_OF]->(City)
- (Attraction)-[:HAS_IMAGE]->(Image)
- (Attraction)-[:HAS_OPERATING_HOURS]->(OperatingHours)

## 3. 欄位映射表
| 原始欄位 (XML) | 處理後欄位 (JSON) | Neo4j 屬性/關聯 |
| --- | --- | --- |
| ORI_ID | AttractionID | (a:Attraction).id |
| NAME | AttractionName | (a:Attraction).name |
| TOLDESCRIBE + DESCRIPTION | Description | (a:Attraction).description |
| PY + PX | PositionLat + PositionLon | (a:Attraction).lat, lon, location |
| ADD | StreetAddress | (a:Attraction).address |
| TEL | Phone | (a:Attraction).phone |
| WEBSITE | Website | (a:Attraction).website |
| UPDATETIME | UpdateTime | (a:Attraction).update_time |
| REGION | City | (City).name + LOCATED_IN_CITY |
| TOWN | Town | (Town).name + LOCATED_IN_TOWN |
| CLASS1~3 | AttractionClasses | (AttractionClass).name + HAS_CLASS |
| PICTURE1~3 | Images | (Image) + HAS_IMAGE |
| OPENTIME (爬蟲) | ServiceTimeInfo | (OperatingHours) + HAS_OPERATING_HOURS |
| N/A (動態產生) | DescriptionEmbedding | (a:Attraction).description_embedding |

## 4. 分類代碼對照表
| 代碼 | 名稱 | 代碼 | 名稱 |
| --- | --- | --- | --- |
| 1 | 文化類 | 10 | 國家公園類 |
| 2 | 生態類 | 11 | 國家風景區類 |
| 3 | 古蹟類 | 12 | 休閒農業類 |
| 4 | 廟宇類 | 13 | 溫泉類 |
| 5 | 藝術類 | 14 | 自然風景類 |
| 6 | 小吃/特產類 | 15 | 遊憩類 |
| 7 | 國家公園類 (舊) | 16 | 體育健身類 |
| 8 | 觀光工廠類 | 17 | 觀光工廠類 (舊) |
| 9 | 都會公園類 | 18 | 其他 |

## 5. 營業時間格式
```json
{
  "ServiceTimeInfo": {
    "Monday": [
      {
        "open": "09:00",
        "close": "12:00"
      },
      {
        "open": "13:00",
        "close": "17:00"
      }
    ],
    "Tuesday": [
      {
        "open": "09:00",
        "close": "17:00"
      }
    ]
  }
}
```
每週一至週日，可包含多個營業時段。

## 6. 執行流程 (CMD + VENV)
### 6.1 建立虛擬環境
```cmd
python -m venv venv
venv\Scripts\activate
```

### 6.2 安裝套件
```cmd
pip install -r requirements.txt
```

### 6.3 資料清洗與向量計算 (GPU)
```cmd
python process_attractions.py
```

### 6.4 爬取營業時間
```cmd
python crawler_business_hours.py
```

### 6.5 手動填補空值
編輯 `cleaned_attractions.json`

### 6.6 匯入 Neo4j
```cmd
python import_to_neo4j.py
```

## 7. 向量索引
- 維度 (Dimensions): 1024
- 相似度計算 (Similarity Function): Cosine
- 索引名稱: `attraction_description_embedding`
