"""
台灣觀光活動資料 -> Neo4j 匯入腳本（含向量搜尋 embedding）

只保留以下欄位並寫入單一節點 (:Event)：
EventID, EventName, Description, PositionLat, PositionLon,
Images(Name/URL/Description), TrafficInfo, ParkingInfo,
WebsiteURL, StartDateTime, EndDateTime, EventStatus, UpdateTime

另外會用本地開源模型（BAAI/bge-m3，支援繁體中文，1024 維）
把每筆活動的 name + description 轉成向量，存進 e.embedding，
並在 Neo4j 建立 vector index，之後可以做語意搜尋（GraphRAG hybrid search 用得到）。

使用方式：
    python import_events_to_neo4j.py EventList.json

需要先安裝：
    pip install neo4j sentence-transformers

注意：sentence-transformers 第一次執行會從 HuggingFace 下載模型權重（約 2GB），
      這一步需要網路連線；下載完成後模型會被快取在本機，之後執行完全離線可跑。
"""

import json
import logging
import os
import sys
from datetime import datetime
from typing import Optional

from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("event_importer")


# ============================================================
# Step 1：讀檔
# ============================================================
def load_events(json_path: str) -> list[dict]:
    """讀取原始 JSON，回傳 Events 陣列（原始、未清洗）"""
    with open(json_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    events = data.get("Events", [])
    logger.info(f"讀到 {len(events)} 筆活動")
    return events


# ============================================================
# Step 2：清洗
# ============================================================
def clean_str(value) -> Optional[str]:
    """空字串 / 純空白 轉成 None，其餘 strip 頭尾空白"""
    if value is None:
        return None
    value = str(value).strip()
    return value if value else None


def parse_datetime(value: Optional[str], event_id: str, field_name: str) -> Optional[str]:
    """
    驗證 ISO8601 格式（含時區）是否可解析。
    回傳原始字串本身（交給 Cypher 的 datetime() 轉型，不在 Python 端做轉換），
    格式錯誤則回傳 None 並記錄警告。
    """
    if not value:
        return None
    try:
        datetime.fromisoformat(value)
        return value
    except ValueError:
        logger.warning(f"[{event_id}] {field_name} 日期格式無法解析，捨棄此欄位: {value}")
        return None


def clean_event(raw: dict) -> Optional[dict]:
    """
    清洗單筆活動資料。
    回傳 None 代表這筆資料缺少必要欄位，不予匯入。
    """
    event_id = raw.get("EventID")
    if not event_id:
        logger.warning("缺少 EventID，略過此筆")
        return None

    # 座標是必要欄位：沒有座標的活動在地圖 / 空間查詢上沒有意義
    lat, lon = raw.get("PositionLat"), raw.get("PositionLon")
    if lat is None or lon is None:
        logger.warning(f"[{event_id}] 缺少座標，略過此筆")
        return None
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        logger.warning(f"[{event_id}] 座標格式錯誤，略過此筆")
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        logger.warning(f"[{event_id}] 座標超出合理範圍 ({lat}, {lon})，略過此筆")
        return None

    # Images 可能有多張，我們將其整理成 dict 陣列以利後續拆分 Image 節點
    images = raw.get("Images") or []
    images_list = []
    for i in images:
        url = clean_str(i.get("URL"))
        if url:
            images_list.append({
                "ImageURL": url,
                "ImageName": clean_str(i.get("Name")) or "",
                "ImageDescription": clean_str(i.get("Description")) or ""
            })

    start_dt = parse_datetime(raw.get("StartDateTime"), event_id, "StartDateTime")
    end_dt = parse_datetime(raw.get("EndDateTime"), event_id, "EndDateTime")

    # 日期合理性檢查：只記警告，不擋匯入（避免誤刪合法的跨年 / 長期活動）
    if start_dt and end_dt:
        s, e = datetime.fromisoformat(start_dt), datetime.fromisoformat(end_dt)
        if e < s:
            logger.warning(f"[{event_id}] EndDateTime 早於 StartDateTime，資料可能有誤: {start_dt} ~ {end_dt}")
        elif (e - s).days > 365:
            logger.warning(f"[{event_id}] 活動期間超過一年，建議人工複查: {start_dt} ~ {end_dt}")

    return {
        "eventId": event_id,
        "name": clean_str(raw.get("EventName")),
        "description": clean_str(raw.get("Description")),
        "lat": lat,
        "lon": lon,
        "images": images_list,
        "trafficInfo": clean_str(raw.get("TrafficInfo")),
        "parkingInfo": clean_str(raw.get("ParkingInfo")),
        "websiteUrl": clean_str(raw.get("WebsiteURL")),
        "startDateTime": start_dt,
        "endDateTime": end_dt,
        "eventStatus": raw.get("EventStatus"),
        "updateTime": parse_datetime(raw.get("UpdateTime"), event_id, "UpdateTime"),
    }


def clean_events(raw_events: list[dict], report_path: str = "missing_fields_report.json") -> list[dict]:
    cleaned = []
    missing_report = []

    for raw in raw_events:
        event_id = raw.get("EventID")
        if not event_id:
            missing_report.append({"EventID": "Unknown", "Status": "Skipped", "Reason": "Missing EventID"})
            continue

        c = clean_event(raw)
        if c is None:
            missing_report.append({"EventID": event_id, "Status": "Skipped", "Reason": "缺少必要欄位 (如座標) 或格式錯誤"})
            continue

        missing_fields = []
        if not c.get("name"): missing_fields.append("EventName")
        if not c.get("description"): missing_fields.append("Description")
        if not c.get("trafficInfo"): missing_fields.append("TrafficInfo")
        if not c.get("parkingInfo"): missing_fields.append("ParkingInfo")
        if not c.get("websiteUrl"): missing_fields.append("WebsiteURL")
        if not c.get("startDateTime"): missing_fields.append("StartDateTime")
        if not c.get("endDateTime"): missing_fields.append("EndDateTime")
        if not c.get("eventStatus"): missing_fields.append("EventStatus")
        if not c.get("updateTime"): missing_fields.append("UpdateTime")
        if not c.get("images"): missing_fields.append("Images")

        if missing_fields:
            missing_report.append({
                "EventID": event_id,
                "Status": "Kept",
                "MissingFields": missing_fields
            })

        cleaned.append(c)

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(missing_report, f, ensure_ascii=False, indent=2)
        logger.info(f"缺失欄位報告已輸出至: {report_path}")
    except Exception as e:
        logger.error(f"輸出缺失報告失敗: {e}")

    logger.info(f"清洗完成：{len(cleaned)} / {len(raw_events)} 筆可匯入")
    return cleaned


# ============================================================
# Step 3：產生 Embedding（本地開源模型，支援中文）
# ============================================================
# bge-m3：目前開源多語言 embedding 裡對中文語意表現數一數二好的模型，1024 維。
# 換模型記得同步改下面 EMBEDDING_DIMENSIONS，不然 vector index 建立會失敗。
EMBEDDING_MODEL_NAME = "BAAI/bge-m3"
EMBEDDING_DIMENSIONS = 1024

_embedding_model = None


def get_embedding_model() -> SentenceTransformer:
    """延遲載入模型，避免不需要 embedding 的情境也要等模型載入"""
    global _embedding_model
    if _embedding_model is None:
        logger.info(f"載入 embedding 模型 {EMBEDDING_MODEL_NAME}（第一次執行需要下載，請保持網路連線）...")
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        logger.info("模型載入完成")
    return _embedding_model


def add_embeddings(cleaned_events: list[dict], batch_size: int = 32) -> list[dict]:
    """
    用 name + description 組成語意文字，產生向量後掛回每筆資料的 embedding 欄位。
    normalize_embeddings=True 讓向量長度為 1，配合 cosine similarity 的 vector index 使用。
    """
    if not cleaned_events:
        return cleaned_events

    model = get_embedding_model()
    texts = [f"{e['name'] or ''}。{e['description'] or ''}".strip() for e in cleaned_events]

    logger.info(f"開始產生 {len(texts)} 筆 embedding（本地運算，934 筆規模在 CPU 上約數分鐘）...")
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        normalize_embeddings=True,
    )
    for event, emb in zip(cleaned_events, embeddings):
        event["DescriptionEmbedding"] = emb.tolist()
    logger.info("embedding 產生完成")
    return cleaned_events


# ============================================================
# Step 4：建立 Constraints / Indexes
# ============================================================
SCHEMA_CYPHER = [
    # EventID 唯一鍵，確保 MERGE 不會重複建立節點
    "CREATE CONSTRAINT event_id IF NOT EXISTS FOR (e:Event) REQUIRE e.EventID IS UNIQUE",
    # ImageURL 唯一鍵
    "CREATE CONSTRAINT image_url IF NOT EXISTS FOR (i:Image) REQUIRE i.ImageURL IS UNIQUE",
    # 空間索引，之後可以用 point.distance() 做「附近活動」查詢
    "CREATE POINT INDEX event_location IF NOT EXISTS FOR (e:Event) ON (e.location)",
    # 時間範圍查詢用（例如「這個月有哪些活動」）
    "CREATE INDEX event_start_time IF NOT EXISTS FOR (e:Event) ON (e.StartDateTime)",
    "CREATE INDEX event_end_time IF NOT EXISTS FOR (e:Event) ON (e.EndDateTime)",
    "CREATE INDEX event_status IF NOT EXISTS FOR (e:Event) ON (e.EventStatus)",
    # 向量索引，供語意搜尋 / GraphRAG hybrid search 使用
    f"""CREATE VECTOR INDEX event_description_index IF NOT EXISTS
        FOR (e:Event) ON (e.DescriptionEmbedding)
        OPTIONS {{indexConfig: {{
            `vector.dimensions`: {EMBEDDING_DIMENSIONS},
            `vector.similarity_function`: 'cosine'
        }}}}""",
]


def setup_schema(driver, database: str):
    with driver.session(database=database) as session:
        for stmt in SCHEMA_CYPHER:
            session.run(stmt)
    logger.info("Constraints / Indexes 建立完成")


# ============================================================
# Step 5：批次 Upsert
# ============================================================
UPSERT_CYPHER = """
UNWIND $batch AS row
MERGE (e:Event {EventID: row.eventId})
SET
    e.EventName = row.name,
    e.Description = row.description,
    e.PositionLat = row.lat,
    e.PositionLon = row.lon,
    e.location = point({latitude: row.lat, longitude: row.lon}),
    e.TrafficInfo = row.trafficInfo,
    e.ParkingInfo = row.parkingInfo,
    e.WebsiteURL = row.websiteUrl,
    e.StartDateTime = CASE WHEN row.startDateTime IS NULL THEN NULL ELSE datetime(row.startDateTime) END,
    e.EndDateTime = CASE WHEN row.endDateTime IS NULL THEN NULL ELSE datetime(row.endDateTime) END,
    e.EventStatus = row.eventStatus,
    e.UpdateTime = CASE WHEN row.updateTime IS NULL THEN NULL ELSE datetime(row.updateTime) END,
    e.DescriptionEmbedding = row.DescriptionEmbedding,
    e.SourceDataset = '觀光資訊'

WITH e, row.images AS images
UNWIND images AS img
MERGE (i:Image {ImageURL: img.ImageURL})
SET i.ImageName = img.ImageName,
    i.ImageDescription = img.ImageDescription
MERGE (e)-[:HAS_IMAGE]->(i)
"""


def upsert_events(driver, database: str, cleaned_events: list[dict], batch_size: int = 500):
    """
    用 UNWIND + MERGE 批次寫入。
    eventId 是冪等鍵：同一筆資料重複匯入只會更新屬性，不會產生重複節點。
    """
    total = len(cleaned_events)
    for i in range(0, total, batch_size):
        batch = cleaned_events[i:i + batch_size]
        with driver.session(database=database) as session:
            session.run(UPSERT_CYPHER, batch=batch)
        logger.info(f"已寫入 {min(i + batch_size, total)} / {total} 筆")


# ============================================================
# 主流程
# ============================================================
def main():
    if len(sys.argv) < 2:
        print("使用方式: python import_events_to_neo4j.py <EventList.json 路徑>")
        sys.exit(1)

    json_path = sys.argv[1]

    # 建議把連線資訊放在環境變數，不要寫死在程式碼裡
    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "Playtaiwan2026Playtaiwan2026")
    neo4j_database = os.environ.get("NEO4J_DATABASE", "events")  # 改成你建立的活動 database 名稱

    if not neo4j_password:
        logger.error("請設定環境變數 NEO4J_PASSWORD 後再執行")
        sys.exit(1)

    cache_file = os.path.join(os.path.dirname(json_path) or ".", "events_with_embeddings_cache.json")

    if os.path.exists(cache_file):
        logger.info(f"找到已有的 embedding 快取檔 ({cache_file})，直接載入跳過耗時運算...")
        with open(cache_file, "r", encoding="utf-8") as f:
            cleaned_events = json.load(f)
    else:
        raw_events = load_events(json_path)
        
        report_file = os.path.join(os.path.dirname(json_path) or ".", "missing_fields_report.json")
        cleaned_events = clean_events(raw_events, report_file)
        
        cleaned_events = add_embeddings(cleaned_events)
        
        logger.info(f"將計算好的資料與向量存入快取檔: {cache_file}")
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cleaned_events, f, ensure_ascii=False)

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    try:
        driver.verify_connectivity()
        logger.info("Neo4j 連線成功")
        setup_schema(driver, neo4j_database)
        upsert_events(driver, neo4j_database, cleaned_events)
    finally:
        driver.close()

    logger.info("匯入完成")


if __name__ == "__main__":
    main()
