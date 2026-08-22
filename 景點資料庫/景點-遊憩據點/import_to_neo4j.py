import json
import hashlib
from neo4j import GraphDatabase

NEO4J_URI = "neo4j://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "Playtaiwan2026Playtaiwan2026"
NEO4J_DATABASE = "attraction"

def generate_md5(text):
    """產生字串的 MD5 雜湊值"""
    return hashlib.md5(text.encode('utf-8')).hexdigest()

class AttractionNeo4jImporter:
    def __init__(self, uri, user, password, database="neo4j"):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database

    def close(self):
        self.driver.close()

    def setup_constraints(self):
        """設定唯一性約束"""
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Attraction) REQUIRE a.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:AttractionClass) REQUIRE c.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (ct:City) REQUIRE ct.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (t:Town) REQUIRE t.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (i:Image) REQUIRE i.id IS UNIQUE"
        ]
        with self.driver.session(database=self.database) as session:
            for query in constraints:
                session.run(query)
                print(f"執行約束: {query}")

    def setup_vector_index(self):
        """設定向量索引"""
        query = """
        CREATE VECTOR INDEX attraction_description_embedding IF NOT EXISTS
        FOR (a:Attraction) ON (a.description_embedding)
        OPTIONS {indexConfig: {
            `vector.dimensions`: 1024,
            `vector.similarity_function`: 'cosine'
        }}
        """
        with self.driver.session(database=self.database) as session:
            session.run(query)
            print("建立向量索引: attraction_description_embedding")

    @staticmethod
    def _create_attraction_node(tx, a):
        """建立單一遊憩據點節點及其關聯"""
        # 準備基本參數
        attr_id = a.get("AttractionID")
        name = a.get("AttractionName")
        desc = a.get("Description", "")
        lat = a.get("PositionLat")
        lon = a.get("PositionLon")
        address = a.get("StreetAddress", "")
        update_time = a.get("UpdateTime", "")
        phone = a.get("Phone", "")
        website = a.get("Website", "")
        source = a.get("source", "遊憩據點")
        desc_emb = a.get("DescriptionEmbedding")
        
        # 1. 建立 Attraction 節點
        query_attr = """
        MERGE (attr:Attraction {id: $id})
        SET attr.name = $name,
            attr.description = $desc,
            attr.address = $address,
            attr.update_time = $update_time,
            attr.phone = $phone,
            attr.website = $website,
            attr.source = $source
        """
        params = {
            "id": attr_id, "name": name, "desc": desc, "address": address,
            "update_time": update_time, "phone": phone, "website": website,
            "source": source
        }
        
        # 處理座標
        if lat is not None and lon is not None:
            query_attr += ", attr.lat = toFloat($lat), attr.lon = toFloat($lon)"
            query_attr += ", attr.location = point({longitude: toFloat($lon), latitude: toFloat($lat)})"
            params["lat"] = lat
            params["lon"] = lon
            
        # 處理向量
        if desc_emb is not None:
            query_attr += ", attr.description_embedding = $desc_emb"
            params["desc_emb"] = desc_emb
            
        tx.run(query_attr, **params)
        
        # 2. 營業時間 (OperatingHours)
        service_time = a.get("ServiceTimeInfo", {})
        if isinstance(service_time, dict):
            for day, times in service_time.items():
                for t in times:
                    open_time = t.get("open", "").strip()
                    close_time = t.get("close", "").strip()
                    if open_time and close_time:
                        tx.run("""
                        MATCH (attr:Attraction {id: $attr_id})
                        MERGE (o:OperatingHours {dayOfWeek: $day, openTime: $open_time, closeTime: $close_time})
                        MERGE (attr)-[:HAS_OPERATING_HOURS]->(o)
                        """, attr_id=attr_id, day=day, open_time=open_time, close_time=close_time)

        # 3. 分類 (AttractionClass)
        for class_name in a.get("AttractionClasses", []):
            if class_name:
                tx.run("""
                MATCH (attr:Attraction {id: $attr_id})
                MERGE (c:AttractionClass {name: $class_name})
                MERGE (attr)-[:HAS_CLASS]->(c)
                """, attr_id=attr_id, class_name=class_name)

        # 4 & 5. 縣市 (City) 與 鄉鎮市區 (Town)
        city_name = a.get("City")
        town_name = a.get("Town")
        
        if city_name:
            tx.run("""
            MATCH (attr:Attraction {id: $attr_id})
            MERGE (c:City {name: $city_name})
            MERGE (attr)-[:LOCATED_IN_CITY]->(c)
            """, attr_id=attr_id, city_name=city_name)
            
        if town_name:
            tx.run("""
            MATCH (attr:Attraction {id: $attr_id})
            MERGE (t:Town {name: $town_name})
            MERGE (attr)-[:LOCATED_IN_TOWN]->(t)
            """, attr_id=attr_id, town_name=town_name)
            
            if city_name:
                tx.run("""
                MATCH (t:Town {name: $town_name})
                MATCH (c:City {name: $city_name})
                MERGE (t)-[:PART_OF]->(c)
                """, town_name=town_name, city_name=city_name)

        # 6. 圖片 (Image)
        for img in a.get("Images", []):
            img_url = img.get("URL", "")
            if not img_url: 
                continue
            img_id = generate_md5(img_url)
            tx.run("""
            MATCH (attr:Attraction {id: $attr_id})
            MERGE (i:Image {id: $img_id})
            SET i.url = $url, i.name = $name, i.description = $desc
            MERGE (attr)-[:HAS_IMAGE]->(i)
            """, attr_id=attr_id, img_id=img_id, url=img_url, name=img.get("Name", ""), desc=img.get("Description", ""))


    def import_data(self, data_list):
        """匯入資料並產生報告"""
        report = {
            "total": len(data_list),
            "success": 0,
            "failed": 0,
            "errors": [],
            "null_value_report": {
                "city_empty": 0,
                "town_empty": 0,
                "address_empty": 0,
                "description_empty": 0,
                "coordinates_empty": 0,
                "images_empty": 0,
                "service_time_empty": 0,
                "embedding_empty": 0,
                "phone_empty": 0,
                "website_empty": 0
            },
            "format_errors": []
        }

        with self.driver.session(database=self.database) as session:
            for idx, a in enumerate(data_list):
                attr_id = a.get("AttractionID", str(idx))
                try:
                    # 檢查空值
                    if not a.get("City"): report["null_value_report"]["city_empty"] += 1
                    if not a.get("Town"): report["null_value_report"]["town_empty"] += 1
                    if not a.get("StreetAddress"): report["null_value_report"]["address_empty"] += 1
                    if not a.get("Description"): report["null_value_report"]["description_empty"] += 1
                    
                    lat = a.get("PositionLat")
                    lon = a.get("PositionLon")
                    if lat is None or lon is None:
                        report["null_value_report"]["coordinates_empty"] += 1
                    else:
                        try:
                            lat_f = float(lat)
                            lon_f = float(lon)
                            if not (21 <= lat_f <= 26 and 119 <= lon_f <= 122):
                                report["format_errors"].append({
                                    "id": attr_id,
                                    "field": "Coordinates",
                                    "issue": f"座標超出台灣範圍: ({lat_f}, {lon_f})"
                                })
                        except ValueError:
                            report["format_errors"].append({
                                "id": attr_id,
                                "field": "Coordinates",
                                "issue": "座標格式錯誤"
                            })

                    if not a.get("Images"): report["null_value_report"]["images_empty"] += 1
                    if not a.get("ServiceTimeInfo"): report["null_value_report"]["service_time_empty"] += 1
                    if not a.get("DescriptionEmbedding"): report["null_value_report"]["embedding_empty"] += 1
                    if not a.get("Phone"): report["null_value_report"]["phone_empty"] += 1
                    if not a.get("Website"): report["null_value_report"]["website_empty"] += 1

                    # 執行匯入
                    session.execute_write(self._create_attraction_node, a)
                    report["success"] += 1
                    
                    if (idx + 1) % 100 == 0:
                        print(f"已處理 {idx + 1}/{report['total']} 筆資料...")

                except Exception as e:
                    report["failed"] += 1
                    report["errors"].append({
                        "index": idx,
                        "id": attr_id,
                        "error": str(e)
                    })

        return report

def main():
    try:
        with open("cleaned_attractions.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"讀取了 {len(data)} 筆景點資料")
    except FileNotFoundError:
        print("找不到 cleaned_attractions.json 檔案，請確認檔案位置。")
        return

    importer = AttractionNeo4jImporter(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE)
    try:
        print("開始設定 Neo4j 約束...")
        importer.setup_constraints()
        
        print("開始設定向量索引...")
        importer.setup_vector_index()
        
        print("開始匯入資料...")
        report = importer.import_data(data)
        
        # 儲存報告
        with open("import_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            
        print("\n匯入完成！")
        print(f"總筆數: {report['total']}")
        print(f"成功: {report['success']}")
        print(f"失敗: {report['failed']}")
        print(f"格式錯誤數: {len(report['format_errors'])}")
        print("詳細報告已儲存至 import_report.json")
        
    finally:
        importer.close()

if __name__ == "__main__":
    main()
