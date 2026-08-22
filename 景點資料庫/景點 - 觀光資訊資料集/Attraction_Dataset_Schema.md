# 觀光資訊資料庫 - Neo4j 圖形資料庫匯入規範與 Schema (Graph Schema)

本文件定義了景點資料集經過 Python 程式正規化後，針對 **Neo4j 圖形資料庫 (Graph Database)** 的節點 (Nodes)、關聯 (Relationships) 設計，以及匯入腳本說明。

## 1. 檔案架構與前置作業

本資料集採用 Python 進行自動化處理，主要包含兩支腳本：
- **`process_attractions.py`**：讀取原始 JSON，進行資料清洗（移除停車資訊）、類別代碼明碼化，並使用 `intfloat/multilingual-e5-large` 進行 GPU 向量化（Embedding）。最後匯出 `cleaned_attractions.json`。
- **`import_to_neo4j.py`**：讀取 `cleaned_attractions.json`，透過 Neo4j Python 驅動程式建立節點、關聯以及向量索引（Vector Index）。

## 2. 圖形資料模型設計 (Graph Data Model)

在 Neo4j 中，我們將實體拆分為不同的節點，並建立關聯，以便進行圖形檢索與關聯推薦。

### 節點 (Nodes) 與屬性 (Properties)

1. **`(:Attraction)`** - 景點主體
   - `id` (String, Unique)
   - `name` (String)
   - `address` (String) - 已移除縣市與鄉鎮區名稱
   - `description` (String)
   - `lat` (Float), `lon` (Float)
   - `location` (Point) - 原生空間座標格式 `point({longitude: ..., latitude: ...})`
   - `update_time` (String)
   - `ticket_info` (String)
   - `travel_info` (String)
   - `business_status` (String) - 營業狀態（例如：正常營業、永久歇業、暫停營業、無提供時間）
   - `description_embedding` (Array of Float) - 1024 維的向量屬性

2. **`(:OperatingHours)`** - 營業時間
   - `dayOfWeek` (String) - 星期（例如：Monday, Tuesday）
   - `openTime` (String) - 開店時間（例如：08:30）
   - `closeTime` (String) - 關店時間（例如：17:00）

3. **`(:AttractionClass)`** - 景點分類
   - `name` (String, Unique) - 例如：「森林遊樂區類」、「自然風景類」等

4. **`(:City)`** - 縣市
   - `name` (String, Unique)

5. **`(:Town)`** - 鄉鎮市區
   - `name` (String, Unique)

6. **`(:Image)`** - 圖片
   - `id` (String, Unique) - 利用 URL 進行 MD5 hash 產生
   - `url` (String)
   - `name` (String)
   - `description` (String)

7. **`(:Tag)`** - 標籤
   - `name` (String, Unique)

### 關聯 (Relationships)

- `(a:Attraction)-[:HAS_OPERATING_HOURS]->(o:OperatingHours)`
- `(a:Attraction)-[:HAS_CLASS]->(c:AttractionClass)`
- `(a:Attraction)-[:LOCATED_IN_CITY]->(city:City)`
- `(a:Attraction)-[:LOCATED_IN_TOWN]->(town:Town)`
- `(town:Town)-[:PART_OF]->(city:City)`
- `(a:Attraction)-[:HAS_IMAGE]->(i:Image)`
- `(a:Attraction)-[:HAS_TAG]->(t:Tag)`

---

## 3. 匯入執行流程

所有流程接已封裝在 Python 腳本內，不需手動執行 Cypher (APOC)。

### 步驟 3.1：資料清洗與向量計算
執行清洗腳本（需安裝 `sentence-transformers` 及支援 CUDA 的 `torch` 以啟用 GPU）：
```bash
python process_attractions.py
```
執行後會產生 `cleaned_attractions.json`，若有部分欄位欲手動補齊，請修改此檔案。

### 步驟 3.2：匯入 Neo4j
確保 Neo4j 服務已啟動，並修改 `import_to_neo4j.py` 內的帳號、密碼。接著執行：
```bash
python import_to_neo4j.py
```

### 步驟 3.3：向量索引 (Vector Index) 自動建立
腳本內會自動建立 1024 維的 `cosine` 相似度索引 (`attraction_description_embedding`)，您可以在匯入後使用 Neo4j 的 Vector Search 進行語義搜尋：
```cypher
CALL db.index.vector.queryNodes('attraction_description_embedding', 5, [你的搜尋向量...])
YIELD node, score
RETURN node.name, score
```
