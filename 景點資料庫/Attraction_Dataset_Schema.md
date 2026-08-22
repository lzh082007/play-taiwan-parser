# 觀光景點圖形資料庫 - 統一 Schema (Master Schema)

本文件定義了景點資料庫 (包含「觀光資訊資料集」與「遊憩據點」等來源) 在 **Neo4j 圖形資料庫 (Graph Database)** 中的最終統一架構。
因應不同來源資料的特性，我們採用了關聯式的節點設計，將地理位置、營業時間、圖片與分類等維度獨立，以利發揮圖形資料庫的檢索與推薦優勢。

---

## 1. 圖形資料模型設計 (Graph Data Model)

### 節點 (Nodes) 與 屬性 (Properties)

1. **`(:Attraction)`** - 景點主體
   - `id` (String, Unique) - 景點唯一識別碼 (通常為各資料集原始的 ID)
   - `name` (String) - 景點名稱
   - `description` (String) - 景點介紹 (若原資料有多個描述欄位則合併)
   - `lat` (Float), `lon` (Float) - 經緯度
   - `location` (Point) - 空間地理型別 `point({longitude: ..., latitude: ...})`
   - `address` (String) - 街道地址 (已去除縣市與鄉鎮)
   - `phone` (String) - 聯絡電話
   - `website` (String) - 官方網站
   - `update_time` (String) - 資料最後更新時間
   - `source` (String) - 資料來源 (例如："觀光資訊資料集" 或 "遊憩據點")
   - `description_embedding` (Array of Float) - 1024 維的向量屬性，供語意檢索使用
   - *(其他次要屬性，依資料集不同而異)*：`ticket_info` (票價)、`travel_info` (交通)、`parking` (停車資訊)

2. **`(:AttractionClass)`** - 景點分類
   - `name` (String, Unique) - 分類名稱 (如：「文化類」、「國家公園類」)

3. **`(:City)`** - 縣市
   - `name` (String, Unique) - 縣市名稱 (如：「臺北市」、「屏東縣」)

4. **`(:Town)`** - 鄉鎮市區
   - `name` (String, Unique) - 鄉鎮名稱 (如：「大安區」、「恆春鎮」)

5. **`(:OperatingHours)`** - 營業時間
   - `dayOfWeek` (String) - 星期幾 (例如："Monday")
   - `openTime` (String) - 開始營業時間 (如："09:00")
   - `closeTime` (String) - 結束營業時間 (如："17:00")

6. **`(:Image)`** - 圖片
   - `id` (String, Unique) - 通常為 URL 的 MD5 Hash
   - `url` (String) - 圖片網址
   - `name` (String) - 圖片標題 (若有)
   - `description` (String) - 圖片描述 (若有)

7. **`(:Tag)`** - 標籤 (部分資料集提供)
   - `name` (String, Unique) - 標籤名稱

8. **`(:SocialMedia)`** - 社群媒體 (部分資料集提供)
   - `url` (String, Unique) - 網址
   - `name` (String) - 平台或帳號名稱

---

### 關聯 (Relationships)

為了將景點的各個屬性串聯起來，我們建立以下關聯：

#### 類別與標籤
* `(a:Attraction)-[:HAS_CLASS]->(c:AttractionClass)`
* `(a:Attraction)-[:HAS_TAG]->(t:Tag)`

#### 地理層級
* `(a:Attraction)-[:LOCATED_IN_CITY]->(c:City)`
* `(a:Attraction)-[:LOCATED_IN_TOWN]->(t:Town)`
* `(t:Town)-[:PART_OF]->(c:City)`

#### 營業時間與媒體
* `(a:Attraction)-[:HAS_OPERATING_HOURS]->(o:OperatingHours)`
* `(a:Attraction)-[:HAS_IMAGE]->(i:Image)`
* `(a:Attraction)-[:HAS_SOCIAL_MEDIA]->(s:SocialMedia)`

---

## 2. 資料庫唯一性約束與索引 (Constraints & Indexes)

在匯入任何資料前，應確保資料庫建立以下約束以加速匯入並確保節點不重複：

```cypher
CREATE CONSTRAINT IF NOT EXISTS FOR (a:Attraction) REQUIRE a.id IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (c:AttractionClass) REQUIRE c.name IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (ct:City) REQUIRE ct.name IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (t:Town) REQUIRE t.name IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (i:Image) REQUIRE i.id IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (t:Tag) REQUIRE t.name IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (s:SocialMedia) REQUIRE s.url IS UNIQUE;
```

**向量索引 (Vector Index)**
針對景點描述所算出的 1024 維度 Embedding 建立索引，以支援語意搜尋：

```cypher
CREATE VECTOR INDEX attraction_description_embedding IF NOT EXISTS
FOR (a:Attraction) ON (a.description_embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 1024,
  `vector.similarity_function`: 'cosine'
}};
```

## 3. 備份與還原 Dump 檔

根目錄中存有資料庫的 Dump 備份檔 (如 `attraction-2026-08-20T10-08-48.dump`)，這是包含上述所有結構的完整快照。
若要還原此資料庫，可以使用 Neo4j 內建的指令 (需在 Neo4j 停止運作的狀態下執行)：

```bash
neo4j-admin database load attraction --from-path=./ --overwrite-destination=true
```
*(請根據您的 Dump 檔確切檔名與 Neo4j 版本調整指令)*
