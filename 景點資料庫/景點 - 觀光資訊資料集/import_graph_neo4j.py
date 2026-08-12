import os, json
from sentence_transformers import SentenceTransformer
from neo4j import GraphDatabase
print("載入本地 embedding 模型（BAAI/bge-m3）...")
import torch
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"使用裝置: {device}")
model = SentenceTransformer("BAAI/bge-m3", device=device, model_kwargs={"use_safetensors": True})

# 連線至 Neo4j 資料庫
driver = GraphDatabase.driver(
    "bolt://localhost:7687",
    auth=("neo4j", os.environ.get("NEO4J_PASSWORD", "Playtaiwan2026Playtaiwan2026")), # 記得在環境變數或這裡補上密碼
)

def embed_batch(texts):
    embeddings = model.encode(texts, normalize_embeddings=True)
    return [e.tolist() for e in embeddings]

def setup_constraints(session):
    queries = [
        "CREATE CONSTRAINT FOR (a:Attraction) REQUIRE a.id IS UNIQUE",
        "CREATE CONSTRAINT FOR (t:Tag) REQUIRE t.name IS UNIQUE",
        "CREATE CONSTRAINT FOR (c:AttractionClass) REQUIRE c.class_id IS UNIQUE",
        "CREATE CONSTRAINT FOR (i:Image) REQUIRE i.url IS UNIQUE",
        "CREATE CONSTRAINT FOR (s:SocialMedia) REQUIRE s.url IS UNIQUE",
        "CREATE POINT INDEX attraction_location IF NOT EXISTS FOR (a:Attraction) ON (a.location)"
    ]
    for q in queries:
        try:
            session.run(q)
        except Exception as e:
            # 約束可能已經存在，忽略錯誤
            pass

def write_batch(tx, records):
    tx.run(
        """
    UNWIND $records AS rec
    
    // 1. 建立 Attraction 節點
    MERGE (a:Attraction {id: rec.id})
    SET a.name = rec.name,
        a.description = rec.description,
        a.lat = rec.lat,
        a.lon = rec.lon,
        a.location = point({latitude: rec.lat, longitude: rec.lon}),
        a.address = rec.address,
        a.parking = rec.parking,
        a.traffic_info = rec.traffic_info,
        a.service_time_info = rec.service_time_info,
        a.web_url = rec.web_url,
        a.reservation_urls = rec.reservation_urls,
        a.update_time = rec.update_time,
        a.embedding = rec.embedding,
        a.raw_json = rec.raw_json

    // 2. 處理 Tags 關聯
    WITH a, rec
    UNWIND rec.tags AS tagName
    MERGE (t:Tag {name: tagName})
    MERGE (a)-[:HAS_TAG]->(t)

    // 3. 處理 AttractionClasses 關聯
    WITH a, rec
    UNWIND rec.attraction_classes AS classId
    MERGE (c:AttractionClass {class_id: classId})
    MERGE (a)-[:BELONGS_TO_CLASS]->(c)

    // 4. 處理 Images 關聯
    WITH a, rec
    UNWIND rec.images AS img
    MERGE (i:Image {url: img.url})
    ON CREATE SET i.name = img.name, i.description = img.description
    MERGE (a)-[:HAS_IMAGE]->(i)

    // 5. 處理 Social Media 關聯
    WITH a, rec
    UNWIND rec.social_media_urls AS social
    MERGE (s:SocialMedia {url: social.url})
    ON CREATE SET s.name = social.name
    MERGE (a)-[:HAS_SOCIAL_MEDIA]->(s)
    """,
        records=records,
    )


def main():
    print("載入正規化後的 JSON...")
    # 讀取我們之前跑好的正規化資料
    with open("資料集/AttractionList_Normalized.json", "r", encoding="utf-8") as f:
        records = json.load(f)
        
    total = len(records)
    BATCH = 200 # 批次大小
    
    with driver.session(database="attraction") as session:
        print("設定資料庫 Constraints 唯一性約束...")
        setup_constraints(session)

    for i in range(0, total, BATCH):
        chunk = records[i:i + BATCH]
        
        # 根據您的需求：將 Tags 和 description 結合進行 Embedding
        texts = []
        for r in chunk:
            tags_str = ", ".join(r.get("tags", []))
            description = r.get("description", "")
            name = r.get("name", "")
            
            # 將名稱、標籤與描述串接作為向量化的文本來源
            combine = f"名稱: {name}。標籤: {tags_str}。描述: {description}"
            texts.append(combine)
            
        # 產生向量
        embeddings = embed_batch(texts)

        payload = []
        for r, emb in zip(chunk, embeddings):
            # Neo4j properties must be primitives, so we handle dictionary address
            address = r["address"]
            if isinstance(address, dict):
                address = f"{address.get('ZipCode', '')}{address.get('City', '')}{address.get('Town', '')}{address.get('StreetAddress', '')}"
            else:
                address = str(address) if address else ""

            payload.append({
                "id": r["id"],
                "name": r["name"],
                "description": r["description"],
                "lat": r["lat"],
                "lon": r["lon"],
                "attraction_classes": r["attraction_classes"],
                "address": address,
                "traffic_info": r["traffic_info"],
                "web_url": r["web_url"],
                "reservation_urls": r["reservation_urls"],
                "service_time_info": str(r["service_time_info"]) if r["service_time_info"] else "",
                "parking": str(r["parking"]) if r["parking"] else "",
                "update_time": str(r["update_time"]) if r["update_time"] else "",
                "images": r["images"], # 陣列物件
                "social_media_urls": r["social_media_urls"], # 陣列物件
                "tags": r["tags"], # 陣列字串
                "raw_json": str(r["raw_json"]),
                "embedding": emb,
            })

        # 批次寫入 Neo4j
        with driver.session(database="attraction") as session:
            session.execute_write(write_batch, payload)

        print(f"已寫入 {min(i + BATCH, total)}/{total}")

    driver.close()
    print("🎉 包含 Vector Embedding 的圖形資料全部匯入完成！")

if __name__ == "__main__":
    main()
