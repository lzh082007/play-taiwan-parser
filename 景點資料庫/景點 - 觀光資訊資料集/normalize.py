import json
import os

def normalize_data(input_file, output_file):
    with open(input_file, 'r', encoding='utf-8-sig') as f:
        data = json.load(f)
    
    attractions = data.get('Attractions', [])
    normalized_list = []
    
    for item in attractions:
        # Normalize Tags
        raw_tags = item.get("Tags") or []
        tags = [str(t).strip() for t in raw_tags if str(t).strip()]
        
        # Normalize Parking
        parking_info = item.get("ParkingInfo") or ""
        parking = parking_info.strip() if isinstance(parking_info, str) else str(parking_info)
        
        # Normalize Social Media URLs
        raw_social = item.get("SocialMediaURLs") or []
        social_media_urls = [
            {"name": (s.get("Name") or "").strip(), "url": (s.get("URL") or "").strip()}
            for s in raw_social if isinstance(s, dict) and s.get("URL")
        ]
        
        # Normalize Images
        raw_images = item.get("Images") or []
        images = [
            {
                "name": (img.get("Name") or "").strip(), 
                "description": (img.get("Description") or "").strip(), 
                "url": (img.get("URL") or "").strip()
            }
            for img in raw_images if isinstance(img, dict) and img.get("URL")
        ]
        
        # Handle Reservation URLs
        raw_reservation = item.get("ReservationURLs") or []
        reservation_urls = [r for r in raw_reservation if r]
        
        # Convert lat/lon
        try:
            lat = float(item.get("PositionLat") or 0.0)
        except (ValueError, TypeError):
            lat = 0.0
            
        try:
            lon = float(item.get("PositionLon") or 0.0)
        except (ValueError, TypeError):
            lon = 0.0
            
        normalized_item = {
            "id": item.get("AttractionID", ""),
            "name": item.get("AttractionName", ""),
            "address": item.get("PostalAddress", ""),
            "description": item.get("Description", ""),
            "lat": lat,
            "lon": lon,
            "attraction_classes": item.get("AttractionClasses", []),
            "tags": tags,
            "parking": parking,
            "traffic_info": item.get("TrafficInfo", ""),
            "service_time_info": item.get("ServiceTimeInfo", ""),
            "reservation_urls": reservation_urls,
            "web_url": item.get("WebsiteURL", ""),
            "social_media_urls": social_media_urls,
            "update_time": item.get("UpdateTime", ""),
            "images": images,
            "embedding": [],  # Placeholder for vector embeddings
            "raw_json": json.dumps(item, ensure_ascii=False)
        }
        
        normalized_list.append(normalized_item)
        
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(normalized_list, f, ensure_ascii=False, indent=2)
        
    print(f"Normalized {len(normalized_list)} records.")
    print(f"Saved to {output_file}")

if __name__ == "__main__":
    input_path = "資料集/AttractionList.json"
    output_path = "資料集/AttractionList_Normalized.json"
    normalize_data(input_path, output_path)
