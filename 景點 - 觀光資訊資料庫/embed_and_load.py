import os, json
from sentence_transformers import SentenceTransformer
from neo4j import GraphDatabase
from attraction_parser import parse_attraction_list

print("載入本地 embedding 模型（第一次執行會自動下載，約 2GB，請耐心等待）...")
model = SentenceTransformer("BAAI/bge-m3")

driver = GraphDatabase.driver(
    "bolt://localhost:7687",
    auth=("neo4j", os.environ["NEO4J_PASSWORD"]),
)


def embed_batch(texts):
    embeddings = model.encode(texts, normalize_embeddings=True)
    return [e.tolist() for e in embeddings]


def write_batch(tx, records):
    tx.run(
        """
    UNWIND $records AS rec
    MERGE (n:Attraction {id: rec.id})
    SET n.name = rec.name,
        n.description = rec.description,
        n.lat = rec.lat,
        n.lon = rec.lon,
        n.attraction_classes = rec.attraction_classes,
        n.address = rec.address,
        n.traffic_info = rec.traffic_info,
        n.web_url = rec.web_url,
        n.reservation_urls = rec.reservation_urls,
        n.service_time_info = rec.service_time_info,
        n.parking = rec.parking,
        n.update_time = rec.update_time,
        n.images = rec.images_json,
        n.social_media_urls = rec.social_media_urls,
        n.tags = rec.tags,
        n.raw_json = rec.raw_json,
        n.embedding = rec.embedding
    """,
        records=records,
    )


def main():
    records = parse_attraction_list("AttractionList.json")
    total = len(records)
    BATCH = 200

    for i in range(0, total, BATCH):
        chunk = records[i:i + BATCH]
        texts = [r["text_for_embedding"] or r["name"] for r in chunk]
        embeddings = embed_batch(texts)

        payload = [
            {
                "id": r["id"],
                "name": r["name"],
                "description": r["description"],
                "lat": r["lat"],
                "lon": r["lon"],
                "attraction_classes": r["attraction_classes"],
                "address": r["address"],
                "traffic_info": r["traffic_info"],
                "web_url": r["web_url"],
                "reservation_urls": r["reservation_urls"],
                "service_time_info": r["service_time_info"],
                "parking": r["parking"],
                "update_time": r["update_time"],
                "images_json": json.dumps(r["images"], ensure_ascii=False),
                "social_media_urls": r["social_media_urls"],
                "tags": r["tags"],
                "raw_json": json.dumps(r["raw"], ensure_ascii=False),
                "embedding": emb,
            }
            for r, emb in zip(chunk, embeddings)
        ]

        with driver.session() as session:
            session.execute_write(write_batch, payload)

        print(f"已寫入 {min(i + BATCH, total)}/{total}")

    driver.close()
    print("全部完成")


if __name__ == "__main__":
    main()
