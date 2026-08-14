import json
import os
import hashlib
from neo4j import GraphDatabase

# Neo4j 連線設定 (請根據您的環境修改)
NEO4J_URI = "neo4j://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "Playtaiwan2026Playtaiwan2026"
NEO4J_DATABASE = "attraction"  # 建立專屬資料庫或改用 "neo4j"

def generate_md5(text):
    return hashlib.md5(text.encode('utf-8')).hexdigest()

class AttractionNeo4jImporter:
    def __init__(self, uri, user, password, database="neo4j"):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database

    def close(self):
        self.driver.close()

    def import_data(self, json_file):
        with open(json_file, 'r', encoding='utf-8') as f:
            attractions = json.load(f)

        print(f"準備匯入 {len(attractions)} 筆資料至 Neo4j 的 '{self.database}' 資料庫...")
        
        with self.driver.session(database=self.database) as session:
            # 1. 建立約束 (Constraints) 以加速匯入與確保唯一性
            self._create_constraints(session)
            
            # 2. 匯入資料
            for i, a in enumerate(attractions):
                session.execute_write(self._create_attraction_node, a)
                if (i + 1) % 100 == 0:
                    print(f"已匯入 {i + 1} 筆資料...")
            
            # 3. 建立 Vector Index
            self._create_vector_index(session)
            
        print("Neo4j 匯入完成！")

    def _create_constraints(self, session):
        print("建立約束 (Constraints)...")
        queries = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Attraction) REQUIRE a.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:AttractionClass) REQUIRE c.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (ct:City) REQUIRE ct.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (t:Town) REQUIRE t.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (i:Image) REQUIRE i.id IS UNIQUE"
        ]
        for query in queries:
            session.run(query)

    @staticmethod
    def _create_attraction_node(tx, a):
        # 建立 Attraction 節點
        # 保留原欄位，所以會有許多原有的屬性，這邊挑選重要的建立屬性，或者可以直接使用動態匯入，
        # 為了效能與明確結構，只針對最常見的建立屬性，若需儲存完整原始資料也可轉 JSON 字串。
        query = """
        MERGE (attr:Attraction {id: $id})
        SET attr.name = $name,
            attr.description = $desc,
            attr.lat = toFloat($lat),
            attr.lon = toFloat($lon),
            attr.address = $address,
            attr.update_time = $update_time,
            attr.ticket_info = $ticket_info,
            attr.travel_info = $travel_info,
            attr.service_time_info = $service_time_info
        """
        
        # 若有座標，加入空間地理資料型別 (Point)
        if a.get("PositionLat") is not None and a.get("PositionLon") is not None:
            query += ",\n            attr.location = point({longitude: toFloat($lon), latitude: toFloat($lat)})"
            
        # 若有 Embedding，加入向量屬性
        if a.get("DescriptionEmbedding"):
            query += ",\n            attr.description_embedding = $desc_emb"
            
        tx.run(query, 
               id=a["AttractionID"],
               name=a["AttractionName"],
               desc=a.get("Description", ""),
               lat=a.get("PositionLat"),
               lon=a.get("PositionLon"),
               address=a.get("StreetAddress", ""),
               update_time=a.get("UpdateTime", ""),
               ticket_info=a.get("TicketInfo", ""),
               travel_info=a.get("TravelInfo", ""),
               service_time_info=a.get("ServiceTimeInfo", ""),
               desc_emb=a.get("DescriptionEmbedding"))
               
        # 建立 AttractionClasses 關聯 (已轉為明碼)
        for class_name in a.get("AttractionClasses", []):
            tx.run("""
            MATCH (attr:Attraction {id: $attr_id})
            MERGE (c:AttractionClass {name: $class_name})
            MERGE (attr)-[:HAS_CLASS]->(c)
            """, attr_id=a["AttractionID"], class_name=str(class_name))
            
        # 建立 City 關聯
        if a.get("City"):
            tx.run("""
            MATCH (attr:Attraction {id: $attr_id})
            MERGE (c:City {name: $city_name})
            MERGE (attr)-[:LOCATED_IN_CITY]->(c)
            """, attr_id=a["AttractionID"], city_name=a["City"])
            
        # 建立 Town 關聯 (並與 City 連結)
        if a.get("Town"):
            tx.run("""
            MATCH (attr:Attraction {id: $attr_id})
            MERGE (t:Town {name: $town_name})
            MERGE (attr)-[:LOCATED_IN_TOWN]->(t)
            """, attr_id=a["AttractionID"], town_name=a["Town"])
            
            if a.get("City"):
                tx.run("""
                MATCH (t:Town {name: $town_name})
                MATCH (c:City {name: $city_name})
                MERGE (t)-[:PART_OF]->(c)
                """, town_name=a["Town"], city_name=a["City"])
                
        # 建立 Images 關聯
        for img in a.get("Images", []):
            img_url = img.get("URL", img.get("Url", ""))
            if not img_url:
                continue
            img_id = generate_md5(img_url)
            tx.run("""
            MATCH (attr:Attraction {id: $attr_id})
            MERGE (i:Image {id: $img_id})
            SET i.name = $img_name, i.url = $img_url, i.description = $img_desc
            MERGE (attr)-[:HAS_IMAGE]->(i)
            """, attr_id=a["AttractionID"], img_id=img_id, img_name=img.get("Name", ""), img_url=img_url, img_desc=img.get("Description", ""))

    def _create_vector_index(self, session):
        print("建立 Vector Index...")
        dim = 1024
        index_name = "attraction_description_embedding"
        
        session.run(f"DROP INDEX {index_name} IF EXISTS")
        session.run(f"""
        CREATE VECTOR INDEX {index_name} IF NOT EXISTS
        FOR (a:Attraction)
        ON (a.description_embedding)
        OPTIONS {{indexConfig: {{
            `vector.dimensions`: {dim},
            `vector.similarity_function`: 'cosine'
        }}}}
        """)

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = script_dir
    json_file = os.path.join(base_dir, "cleaned_attractions.json")
    
    if not os.path.exists(json_file):
        print(f"找不到檔案 {json_file}，請先執行 process_attractions.py")
        return

    importer = AttractionNeo4jImporter(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE)
    try:
        importer.import_data(json_file)
    finally:
        importer.close()

if __name__ == "__main__":
    main()
