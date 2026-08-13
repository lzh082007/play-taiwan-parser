import json
import os
from neo4j import GraphDatabase

# Neo4j 連線設定 (請根據您的環境修改)
NEO4J_URI = "neo4j://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "Playtaiwan2026Playtaiwan2026"
NEO4J_DATABASE = "restaurant"  # 預設為 "neo4j"，可修改為您指定的資料庫名稱

# 動態設定：與 process_restaurants.py 保持一致
CONFIG = {
    "embedding_fields": ["Description"],
    "relation_fields": {
        "CuisineClasses": "Cuisine",
        "City": "City",
        "Town": "Town",
        "Images": "Image"
    }
}

class RestaurantNeo4jImporter:
    def __init__(self, uri, user, password, database="neo4j"):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database

    def close(self):
        self.driver.close()

    def import_data(self, json_file):
        with open(json_file, 'r', encoding='utf-8') as f:
            restaurants = json.load(f)

        print(f"準備匯入 {len(restaurants)} 筆資料至 Neo4j 的 '{self.database}' 資料庫...")
        
        with self.driver.session(database=self.database) as session:
            # 1. 建立約束 (Constraints) 以加速匯入與確保唯一性
            self._create_constraints(session)
            
            # 2. 匯入資料
            for i, r in enumerate(restaurants):
                session.execute_write(self._create_restaurant_node, r)
                if (i + 1) % 100 == 0:
                    print(f"已匯入 {i + 1} 筆資料...")
            
            # 3. 建立 Vector Index
            self._create_vector_index(session)
            
        print("Neo4j 匯入完成！")

    def _create_constraints(self, session):
        print("建立約束 (Constraints)...")
        queries = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (r:Restaurant) REQUIRE r.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Cuisine) REQUIRE c.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (ct:City) REQUIRE ct.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (t:Town) REQUIRE t.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (i:Image) REQUIRE i.id IS UNIQUE"
        ]
        for query in queries:
            session.run(query)

    @staticmethod
    def _create_restaurant_node(tx, r):
        # 建立 Restaurant 節點，屬性包含經緯度與各種基本資料
        query = """
        MERGE (rest:Restaurant {id: $id})
        SET rest.name = $name,
            rest.description = $desc,
            rest.lat = toFloat($lat),
            rest.lon = toFloat($lon),
            rest.website = $website,
            rest.address = $address,
            rest.monday_open = $monday_open,
            rest.monday_close = $monday_close,
            rest.tuesday_open = $tuesday_open,
            rest.tuesday_close = $tuesday_close,
            rest.wednesday_open = $wednesday_open,
            rest.wednesday_close = $wednesday_close,
            rest.thursday_open = $thursday_open,
            rest.thursday_close = $thursday_close,
            rest.friday_open = $friday_open,
            rest.friday_close = $friday_close,
            rest.saturday_open = $saturday_open,
            rest.saturday_close = $saturday_close,
            rest.sunday_open = $sunday_open,
            rest.sunday_close = $sunday_close
        """
        
        # 動態寫入 embedding 屬性
        for field in CONFIG["embedding_fields"]:
            emb_key = f"{field}_embedding"
            if emb_key in r and r[emb_key]:
                query += f", rest.{emb_key} = ${emb_key}\n"
                
        tx.run(query, 
               id=r["RestaurantID"],
               name=r["RestaurantName"],
               desc=r["Description"],
               lat=r["PositionLat"],
               lon=r["PositionLon"],
               website=r["WebsiteURL"],
               address=r["StreetAddress"],
               monday_open=r.get("MondayOpenTime", ""),
               monday_close=r.get("MondayCloseTime", ""),
               tuesday_open=r.get("TuesdayOpenTime", ""),
               tuesday_close=r.get("TuesdayCloseTime", ""),
               wednesday_open=r.get("WednesdayOpenTime", ""),
               wednesday_close=r.get("WednesdayCloseTime", ""),
               thursday_open=r.get("ThursdayOpenTime", ""),
               thursday_close=r.get("ThursdayCloseTime", ""),
               friday_open=r.get("FridayOpenTime", ""),
               friday_close=r.get("FridayCloseTime", ""),
               saturday_open=r.get("SaturdayOpenTime", ""),
               saturday_close=r.get("SaturdayCloseTime", ""),
               sunday_open=r.get("SundayOpenTime", ""),
               sunday_close=r.get("SundayCloseTime", ""),
               **{f"{f}_embedding": r.get(f"{f}_embedding") for f in CONFIG["embedding_fields"]})
               
        # 建立 CuisineClasses 關聯
        for cuisine_id in r.get("CuisineClasses", []):
            tx.run("""
            MATCH (rest:Restaurant {id: $rest_id})
            MERGE (c:Cuisine {id: $cuisine_id})
            MERGE (rest)-[:HAS_CUISINE]->(c)
            """, rest_id=r["RestaurantID"], cuisine_id=str(cuisine_id))
            
        # 建立 City 關聯
        if r.get("City"):
            tx.run("""
            MATCH (rest:Restaurant {id: $rest_id})
            MERGE (c:City {name: $city_name})
            MERGE (rest)-[:LOCATED_IN_CITY]->(c)
            """, rest_id=r["RestaurantID"], city_name=r["City"])
            
        # 建立 Town 關聯 (並與 City 連結)
        if r.get("Town"):
            tx.run("""
            MATCH (rest:Restaurant {id: $rest_id})
            MERGE (t:Town {name: $town_name})
            MERGE (rest)-[:LOCATED_IN_TOWN]->(t)
            """, rest_id=r["RestaurantID"], town_name=r["Town"])
            
            if r.get("City"):
                tx.run("""
                MATCH (t:Town {name: $town_name})
                MATCH (c:City {name: $city_name})
                MERGE (t)-[:PART_OF]->(c)
                """, town_name=r["Town"], city_name=r["City"])
                
        # 建立 Images 關聯
        for img in r.get("Images", []):
            tx.run("""
            MATCH (rest:Restaurant {id: $rest_id})
            MERGE (i:Image {id: $img_id})
            SET i.name = $img_name, i.url = $img_url, i.description = $img_desc
            MERGE (rest)-[:HAS_IMAGE]->(i)
            """, rest_id=r["RestaurantID"], img_id=img["id"], img_name=img["name"], img_url=img["url"], img_desc=img.get("description", ""))

    def _create_vector_index(self, session):
        print("建立 Vector Index...")
        # 假設 embedding 維度為 1024 (BERT large 的維度)
        dim = 1024 # ckiplab/bert-large-chinese 為 1024 維
        for field in CONFIG["embedding_fields"]:
            index_name = f"restaurant_{field.lower()}_embedding"
            # 確保先刪除舊的 index 以免報錯
            session.run(f"DROP INDEX {index_name} IF EXISTS")
            session.run(f"""
            CREATE VECTOR INDEX {index_name} IF NOT EXISTS
            FOR (r:Restaurant)
            ON (r.{field}_embedding)
            OPTIONS {{indexConfig: {{
                `vector.dimensions`: {dim},
                `vector.similarity_function`: 'cosine'
            }}}}
            """)

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = script_dir
    json_file = os.path.join(base_dir, "cleaned_restaurants.json")
    
    if not os.path.exists(json_file):
        print(f"找不到檔案 {json_file}，請先執行 process_restaurants.py")
        return

    importer = RestaurantNeo4jImporter(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE)
    try:
        importer.import_data(json_file)
    finally:
        importer.close()

if __name__ == "__main__":
    main()
