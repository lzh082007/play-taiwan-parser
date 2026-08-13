import json
import os
import hashlib
from neo4j import GraphDatabase

# Neo4j 連線設定 (請根據您的環境修改)
NEO4J_URI = "neo4j://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "Playtaiwan2026Playtaiwan2026"
NEO4J_DATABASE = "hotel"  # 建立專屬的 hotel 資料庫或改用 "neo4j"

def generate_md5(text):
    return hashlib.md5(text.encode('utf-8')).hexdigest()

class HotelNeo4jImporter:
    def __init__(self, uri, user, password, database="neo4j"):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database

    def close(self):
        self.driver.close()

    def import_data(self, json_file):
        with open(json_file, 'r', encoding='utf-8') as f:
            hotels = json.load(f)

        print(f"準備匯入 {len(hotels)} 筆資料至 Neo4j 的 '{self.database}' 資料庫...")
        
        with self.driver.session(database=self.database) as session:
            # 1. 建立約束 (Constraints) 以加速匯入與確保唯一性
            self._create_constraints(session)
            
            # 2. 匯入資料
            for i, h in enumerate(hotels):
                session.execute_write(self._create_hotel_node, h)
                if (i + 1) % 100 == 0:
                    print(f"已匯入 {i + 1} 筆資料...")
            
            # 3. 建立 Vector Index
            self._create_vector_index(session)
            
        print("Neo4j 匯入完成！")

    def _create_constraints(self, session):
        print("建立約束 (Constraints)...")
        queries = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (h:Hotel) REQUIRE h.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:HotelClass) REQUIRE c.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (s:HotelStar) REQUIRE s.star IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (ct:City) REQUIRE ct.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (t:Town) REQUIRE t.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (i:Image) REQUIRE i.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (sv:Service) REQUIRE sv.name IS UNIQUE"
        ]
        for query in queries:
            session.run(query)

    @staticmethod
    def _create_hotel_node(tx, h):
        # 建立 Hotel 節點
        query = """
        MERGE (hotel:Hotel {id: $id})
        SET hotel.name = $name,
            hotel.description = $desc,
            hotel.lat = toFloat($lat),
            hotel.lon = toFloat($lon),
            hotel.address = $address,
            hotel.lowest_price = toInteger($lowest_price),
            hotel.ceiling_price = toInteger($ceiling_price),
            hotel.update_time = $update_time,
            hotel.service_time_info = $service_time_info
        """
        
        # 若有座標，加入空間地理資料型別 (Point)
        if h.get("PositionLat") is not None and h.get("PositionLon") is not None:
            query += ",\n            hotel.location = point({longitude: toFloat($lon), latitude: toFloat($lat)})"
            
        # 若有 Embedding，加入向量屬性
        if h.get("DescriptionEmbedding"):
            query += ",\n            hotel.description_embedding = $desc_emb"
            
        tx.run(query, 
               id=h["HotelID"],
               name=h["HotelName"],
               desc=h.get("Description", ""),
               lat=h.get("PositionLat"),
               lon=h.get("PositionLon"),
               address=h.get("StreetAddress", ""),
               lowest_price=h.get("LowestPrice"),
               ceiling_price=h.get("CeilingPrice"),
               update_time=h.get("UpdateTime"),
               service_time_info=json.dumps(h.get("ServiceTimeInfo", {}), ensure_ascii=False),
               desc_emb=h.get("DescriptionEmbedding"))
               
        # 建立 HotelClasses 關聯
        for class_name in h.get("HotelClasses", []):
            tx.run("""
            MATCH (hotel:Hotel {id: $hotel_id})
            MERGE (c:HotelClass {name: $class_name})
            MERGE (hotel)-[:HAS_CLASS]->(c)
            """, hotel_id=h["HotelID"], class_name=str(class_name))
            
        # 建立 HotelStars 關聯
        if h.get("HotelStars") is not None:
            tx.run("""
            MATCH (hotel:Hotel {id: $hotel_id})
            MERGE (s:HotelStar {star: $star})
            MERGE (hotel)-[:HAS_STAR]->(s)
            """, hotel_id=h["HotelID"], star=h["HotelStars"])
            
        # 建立 City 關聯
        if h.get("City"):
            tx.run("""
            MATCH (hotel:Hotel {id: $hotel_id})
            MERGE (c:City {name: $city_name})
            MERGE (hotel)-[:LOCATED_IN_CITY]->(c)
            """, hotel_id=h["HotelID"], city_name=h["City"])
            
        # 建立 Town 關聯 (並與 City 連結)
        if h.get("Town"):
            tx.run("""
            MATCH (hotel:Hotel {id: $hotel_id})
            MERGE (t:Town {name: $town_name})
            MERGE (hotel)-[:LOCATED_IN_TOWN]->(t)
            """, hotel_id=h["HotelID"], town_name=h["Town"])
            
            if h.get("City"):
                tx.run("""
                MATCH (t:Town {name: $town_name})
                MATCH (c:City {name: $city_name})
                MERGE (t)-[:PART_OF]->(c)
                """, town_name=h["Town"], city_name=h["City"])
                
        # 建立 Images 關聯
        for img in h.get("Images", []):
            img_url = img.get("URL", img.get("Url", ""))
            if not img_url:
                continue
            img_id = generate_md5(img_url)
            tx.run("""
            MATCH (hotel:Hotel {id: $hotel_id})
            MERGE (i:Image {id: $img_id})
            SET i.name = $img_name, i.url = $img_url, i.description = $img_desc
            MERGE (hotel)-[:HAS_IMAGE]->(i)
            """, hotel_id=h["HotelID"], img_id=img_id, img_name=img.get("Name", ""), img_url=img_url, img_desc=img.get("Description", ""))
            
        # 建立 ServiceInfo 關聯
        for service in h.get("ServiceInfo", []):
            if service:
                tx.run("""
                MATCH (hotel:Hotel {id: $hotel_id})
                MERGE (sv:Service {name: $service_name})
                MERGE (hotel)-[:PROVIDES_SERVICE]->(sv)
                """, hotel_id=h["HotelID"], service_name=service)

    def _create_vector_index(self, session):
        print("建立 Vector Index...")
        # intfloat/multilingual-e5-large 的維度是 1024
        dim = 1024
        index_name = "hotel_description_embedding"
        
        session.run(f"DROP INDEX {index_name} IF EXISTS")
        session.run(f"""
        CREATE VECTOR INDEX {index_name} IF NOT EXISTS
        FOR (h:Hotel)
        ON (h.description_embedding)
        OPTIONS {{indexConfig: {{
            `vector.dimensions`: {dim},
            `vector.similarity_function`: 'cosine'
        }}}}
        """)

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = script_dir
    json_file = os.path.join(base_dir, "cleaned_hotels.json")
    
    if not os.path.exists(json_file):
        print(f"找不到檔案 {json_file}，請先執行 process_hotel_data.py")
        return

    importer = HotelNeo4jImporter(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE)
    try:
        importer.import_data(json_file)
    finally:
        importer.close()

if __name__ == "__main__":
    main()
