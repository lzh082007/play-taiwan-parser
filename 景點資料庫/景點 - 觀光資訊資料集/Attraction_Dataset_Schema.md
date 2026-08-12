# 觀光資訊資料庫 - Neo4j 圖形資料庫匯入規範與 Schema (Graph Schema)

本文件定義了景點資料集經過正規化後，針對 **Neo4j 圖形資料庫 (Graph Database)** 的節點 (Nodes)、關聯 (Relationships) 設計，以及對應的匯入 Cypher 腳本。

## 1. 圖形資料模型設計 (Graph Data Model)

在關聯式或 Document 資料庫中，我們通常將所有資料塞在同一個 JSON Object。但在 Neo4j 中，為了發揮圖形資料庫的檢索與推薦優勢，我們將實體拆分為不同的節點，並建立關聯。

### 節點 (Nodes) 與 屬性 (Properties)

1. **`(:Attraction)`** - 景點主體
   - `id` (String, Unique)
   - `name` (String)
   - `address` (String)
   - `description` (String)
   - `lat` (Float), `lon` (Float)
   - `parking` (String)
   - `traffic_info` (String)
   - `service_time_info` (String)
   - `web_url` (String)
   - `reservation_urls` (Array of String)
   - `update_time` (String)
   - `embedding` (Array of Float) - 後續由向量模型產出並匯入，供向量檢索使用。
   - `raw_json` (String) - 序列化為字串的原始 JSON（Neo4j 不支援巢狀 Object 屬性）。

2. **`(:Tag)`** - 標籤
   - `name` (String, Unique)

3. **`(:AttractionClass)`** - 景點分類
   - `class_id` (Integer, Unique)

4. **`(:Image)`** - 圖片
   - `url` (String, Unique)
   - `name` (String)
   - `description` (String)

5. **`(:SocialMedia)`** - 社群媒體
   - `url` (String, Unique)
   - `name` (String)

### 關聯 (Relationships)

- `(a:Attraction)-[:HAS_TAG]->(t:Tag)`
- `(a:Attraction)-[:BELONGS_TO_CLASS]->(c:AttractionClass)`
- `(a:Attraction)-[:HAS_IMAGE]->(i:Image)`
- `(a:Attraction)-[:HAS_SOCIAL_MEDIA]->(s:SocialMedia)`

---

## 2. Neo4j 匯入腳本 (Cypher Import Script)

請先確保 Neo4j 已經安裝了 **APOC** 套件。將正規化後的 `AttractionList_Normalized.json` 放置於 Neo4j 的 `import` 目錄下，然後在 Neo4j Browser 執行以下 Cypher 指令：

### 步驟 2.1：建立唯一性約束 (Constraints)
這能確保資料不重複，並大幅提升匯入效能。
```cypher
CREATE CONSTRAINT FOR (a:Attraction) REQUIRE a.id IS UNIQUE;
CREATE CONSTRAINT FOR (t:Tag) REQUIRE t.name IS UNIQUE;
CREATE CONSTRAINT FOR (c:AttractionClass) REQUIRE c.class_id IS UNIQUE;
CREATE CONSTRAINT FOR (i:Image) REQUIRE i.url IS UNIQUE;
CREATE CONSTRAINT FOR (s:SocialMedia) REQUIRE s.url IS UNIQUE;
```

### 步驟 2.2：匯入資料並建立圖形 (APOC Load JSON)
```cypher
CALL apoc.load.json("file:///AttractionList_Normalized.json") YIELD value
// 1. 建立 Attraction 節點
MERGE (a:Attraction {id: value.id})
SET a.name = value.name,
    a.address = value.address,
    a.description = value.description,
    a.lat = toFloat(value.lat),
    a.lon = toFloat(value.lon),
    a.parking = value.parking,
    a.traffic_info = value.traffic_info,
    a.service_time_info = value.service_time_info,
    a.web_url = value.web_url,
    a.reservation_urls = value.reservation_urls,
    a.update_time = value.update_time,
    a.raw_json = value.raw_json

// 2. 處理 Tags
WITH a, value
UNWIND value.tags AS tagName
MERGE (t:Tag {name: tagName})
MERGE (a)-[:HAS_TAG]->(t)

// 3. 處理 AttractionClasses
WITH a, value
UNWIND value.attraction_classes AS classId
MERGE (c:AttractionClass {class_id: classId})
MERGE (a)-[:BELONGS_TO_CLASS]->(c)

// 4. 處理 Images
WITH a, value
UNWIND value.images AS img
MERGE (i:Image {url: img.url})
ON CREATE SET i.name = img.name, i.description = img.description
MERGE (a)-[:HAS_IMAGE]->(i)

// 5. 處理 Social Media
WITH a, value
UNWIND value.social_media_urls AS social
MERGE (s:SocialMedia {url: social.url})
ON CREATE SET s.name = social.name
MERGE (a)-[:HAS_SOCIAL_MEDIA]->(s);
```

### 步驟 2.3：建立向量索引 (Vector Index) - 備用
當您後續把 `embedding` 算出來並更新到 `:Attraction` 節點後，可以建立向量索引以供語意搜尋：
```cypher
CREATE VECTOR INDEX attraction_embeddings IF NOT EXISTS
FOR (a:Attraction) ON (a.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 1536, // 依照您的模型維度調整 (如 OpenAI text-embedding-3-small 為 1536)
  `vector.similarity_function`: 'cosine'
}};
```
