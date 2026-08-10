from sentence_transformers import SentenceTransformer
from neo4j import GraphDatabase

model = SentenceTransformer("BAAI/bge-m3", device="cuda")
query_vector = model.encode("海邊音樂活動", normalize_embeddings=True).tolist()

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "Playtaiwan2026Playtaiwan2026"))
with driver.session(database="event") as session:
    result = session.run("""
        CYPHER 25
        MATCH (e:Event)
        SEARCH e IN (
            VECTOR INDEX event_embedding FOR $qv
            LIMIT 5
        ) SCORE AS score
        RETURN e.name AS name, score
        ORDER BY score DESC
    """, qv=query_vector)
    for r in result:
        print(round(r["score"], 3), r["name"])

driver.close()