# 餐廳資料庫標準欄位與資料格式 (Restaurant Database Schema)

此文件定義了台灣觀光餐飲資料匯入至 Neo4j 圖形資料庫時，所採用的標準化欄位與資料格式。透過將營業時間拆分為週一至週日，使得資料庫能夠更精確地支援「今天/某天是否有營業」等進階查詢。

## 核心節點 (Restaurant Node)

代表一間餐廳的實體。

| 欄位名稱 (Property) | 資料型別 (Type) | 說明 (Description) | 範例 (Example) |
| :--- | :--- | :--- | :--- |
| `id` | String | 餐廳唯一識別碼 (Primary Key) | `"C1_315080000H_000001"` |
| `name` | String | 餐廳名稱 | `"鼎泰豐 (信義店)"` |
| `description` | String | 餐廳介紹與描述 | `"以小籠包聞名全球的台灣小吃..."` |
| `lat` | Float | 緯度 (WGS84) | `25.033611` |
| `lon` | Float | 經度 (WGS84) | `121.565000` |
| `website` | String | 官方網站網址 | `"https://www.dintaifung.com.tw/"` |
| `address` | String | 街道地址 (不含縣市鄉鎮區) | `"信義路二段194號"` |
| `Description_embedding` | List[Float] | 介紹文本的向量表示 (1024 維)，用於語意搜尋 | `[0.012, -0.045, ...]` |

### 營業時間欄位 (Open/Close Times)
所有時間格式皆標準化為 `HH:MM` (24 小時制)。若該日未營業或查無資料，則對應欄位會是空字串 `""`。

| 欄位名稱 (Property) | 資料型別 (Type) | 說明 (Description) | 範例 (Example) |
| :--- | :--- | :--- | :--- |
| `monday_open` | String | 週一開門時間 | `"09:00"` |
| `monday_close` | String | 週一關門時間 | `"21:00"` |
| `tuesday_open` | String | 週二開門時間 | `"09:00"` |
| `tuesday_close` | String | 週二關門時間 | `"21:00"` |
| `wednesday_open` | String | 週三開門時間 | `""` (公休) |
| `wednesday_close` | String | 週三關門時間 | `""` (公休) |
| `thursday_open` | String | 週四開門時間 | `"09:00"` |
| `thursday_close` | String | 週四關門時間 | `"21:00"` |
| `friday_open` | String | 週五開門時間 | `"09:00"` |
| `friday_close` | String | 週五關門時間 | `"21:30"` |
| `saturday_open` | String | 週六開門時間 | `"10:00"` |
| `saturday_close` | String | 週六關門時間 | `"22:00"` |
| `sunday_open` | String | 週日開門時間 | `"10:00"` |
| `sunday_close` | String | 週日關門時間 | `"22:00"` |

---

## 關聯實體與關係 (Relationships & Entities)

除了餐廳主體外，資料庫透過以下節點建立知識圖譜關聯：

### 1. 菜系/料理分類 (Cuisine)
* **節點標籤**: `Cuisine`
* **欄位**:
  * `id`: String (例如 `"Cuisine_01"`)
* **關聯**: `(Restaurant)-[:HAS_CUISINE]->(Cuisine)`

### 2. 縣市 (City)
* **節點標籤**: `City`
* **欄位**:
  * `name`: String (唯一值，例如 `"臺北市"`)
* **關聯**: `(Restaurant)-[:LOCATED_IN_CITY]->(City)`

### 3. 鄉鎮市區 (Town)
* **節點標籤**: `Town`
* **欄位**:
  * `name`: String (唯一值，例如 `"大安區"`)
* **關聯**: 
  * `(Restaurant)-[:LOCATED_IN_TOWN]->(Town)`
  * `(Town)-[:PART_OF]->(City)`

### 4. 圖片 (Image)
* **節點標籤**: `Image`
* **欄位**:
  * `id`: String (圖片的 MD5 Hash 或原生 ID)
  * `name`: String (圖片名稱)
  * `url`: String (圖片完整網址)
  * `description`: String (圖片描述)
* **關聯**: `(Restaurant)-[:HAS_IMAGE]->(Image)`

---

## 清洗報告格式 (Cleaning Report)

當原始資料的 `ServiceTimeInfo` (營業時間) 格式過於複雜、不合規或為空，無法自動轉換為週一至週日獨立欄位時，系統會將該筆紀錄輸出至 `cleaning_report.json` 中，以便人工補齊。

**清洗報告欄位**:
* `RestaurantID`: 餐廳唯一識別碼。
* `RestaurantName`: 餐廳名稱。
* `ServiceTimeInfo`: 原始的營業時間字串。
* `ErrorReason`: 無法解析的原因 (例如: "Empty value", "Complex format with multiple specific day times", "No time format (HH:MM) found" 等)。

人工處理後，即可直接在資料中補上對應的 Mon-Sun 開門與關門時間。
