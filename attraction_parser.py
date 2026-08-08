"""
台灣觀光景點資料 Parser
來源：交通部觀光署 觀光資訊標準 2.0（AttractionList.json）
用途：清洗 + 篩選欄位，輸出可直接寫入 Neo4j 的正規化 dict（含向量化用文字、原始資料）

執行方式：
    python attraction_parser.py AttractionList.json
"""

import json
import sys
from typing import Any, Optional


def _text(value: Any) -> str:
    """None 一律轉空字串，其餘去除頭尾空白"""
    if value is None:
        return ""
    return str(value).strip()


def _build_address(postal_address: Optional[dict]) -> str:
    """
    原始資料沒有單一 Address 欄位，只有 PostalAddress 物件
    （City / Town / StreetAddress 等），這裡組合成一個地址字串。
    """
    if not postal_address:
        return ""
    parts = [
        postal_address.get("City"),
        postal_address.get("Town"),
        postal_address.get("StreetAddress"),
    ]
    return "".join(p for p in parts if p)


def parse_attraction(raw: dict) -> dict:
    """
    將單筆景點物件正規化成統一 schema。

    對照你要求保留的欄位，以下幾個在這份資料集（TDX 觀光資訊標準 2.0）
    裡實際上不存在，已用最接近的欄位替代，並在對應 key 註明：

      - OpenTime / CloceTime(CloseTime)：
        原始資料只有一段自由文字 ServiceTimeInfo（例如「每日開放」），
        沒有拆分成結構化的開始/結束時間，故對應到 service_time_info，
        不強行拆解成 open_time / close_time（拆了也是猜的，不可靠）。
      - 優惠 PlaceId：
        整份資料集找不到 Promotion 或 PlaceId 相關欄位，設為 None。
      - 社群標籤 TagDesc：
        Tags 是純字串陣列（例如 ["賞楓","雲海",...]），沒有巢狀的
        TagDesc 物件，故 tags 直接輸出字串陣列本身。
      - Address：
        沒有單一欄位，由 PostalAddress.City + Town + StreetAddress 組合。
      - WebUrl → 對應原始欄位 WebsiteURL。
      - Parking → 對應原始欄位 ParkingInfo（文字描述，非結構化金額欄位）。
      - AttractionId → 對應原始欄位 AttractionID（大寫 D），且原始值本身
        已包含 "Attraction_" 前綴（如 Attraction_345040000G_000001），
        故直接沿用作為 Neo4j 節點的業務鍵，不再重複加前綴。
    """
    attraction_id = _text(raw.get("AttractionID"))

    images = [
        {"img_name": _text(img.get("Name")), "url": _text(img.get("URL"))}
        for img in (raw.get("Images") or [])
        if img.get("URL")
    ]

    social_media_urls = [
        _text(sm.get("URL")) for sm in (raw.get("SocialMediaURLs") or []) if sm.get("URL")
    ]

    tags = [_text(t) for t in (raw.get("Tags") or []) if _text(t)]

    reservation_urls = [_text(u) for u in (raw.get("ReservationURLs") or []) if _text(u)]

    description = _text(raw.get("Description"))
    name = _text(raw.get("AttractionName"))

    return {
        # Neo4j 節點識別與標籤
        "id": attraction_id,
        "label": "Attraction",
        # 使用者要求保留的欄位
        "attraction_id": attraction_id,
        "name": name,
        "description": description,
        "lat": raw.get("PositionLat"),
        "lon": raw.get("PositionLon"),
        "attraction_classes": raw.get("AttractionClasses") or [],
        "address": _build_address(raw.get("PostalAddress")),
        "traffic_info": _text(raw.get("TrafficInfo")),
        "web_url": _text(raw.get("WebsiteURL")),
        "reservation_urls": reservation_urls,
        "service_time_info": _text(raw.get("ServiceTimeInfo")),
        "parking": _text(raw.get("ParkingInfo")),
        "update_time": _text(raw.get("UpdateTime")),
        "images": images,                    # [{img_name, url}, ...]
        "social_media_urls": social_media_urls,  # [url, ...]
        "tags": tags,                        # [tag, ...]
        "place_id": None,                    # 此資料集無對應欄位
        # 供向量化用的文字（名稱 + 簡介 + 標籤）
        "text_for_embedding": " ".join(filter(None, [name, description, " ".join(tags)])),
        # 保留完整原始資料，寫入 Neo4j 時建議存成 raw_json 屬性
        "raw": raw,
    }


def parse_attraction_list(json_path: str) -> list[dict]:
    """讀取 AttractionList.json，回傳所有景點的正規化清單（已做基本清洗）"""
    with open(json_path, encoding="utf-8-sig") as f:
        data = json.load(f)

    parsed = []
    skipped = 0
    for raw in data.get("Attractions", []):
        # 基本清洗：沒有名稱或座標的景點視為無效資料，直接捨棄
        if not raw.get("AttractionName"):
            skipped += 1
            continue
        if raw.get("PositionLat") is None or raw.get("PositionLon") is None:
            skipped += 1
            continue
        parsed.append(parse_attraction(raw))

    print(f"[parser] 解析完成：成功 {len(parsed)} 筆，捨棄（缺名稱/座標）{skipped} 筆", file=sys.stderr)
    return parsed


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "AttractionList.json"
    records = parse_attraction_list(path)
    print(json.dumps(records[0], ensure_ascii=False, indent=2))
