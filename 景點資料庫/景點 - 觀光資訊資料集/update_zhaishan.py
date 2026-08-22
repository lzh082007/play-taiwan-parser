import json
import time

filepath = r'C:\Users\USER\Desktop\play-taiwan-parser\景點資料庫\景點 - 觀光資訊資料集\資料集\AttractionServiceTimeList_Updated.json'

with open(filepath, 'r', encoding='utf-8') as f:
    data = json.load(f)

found = False
for rec in data.get('AttractionServiceTimes', []):
    if rec['AttractionID'] == 'Attraction_371020000A_001337':
        rec['ServiceTimes'] = [{
            "Name": "一般營業時間",
            "Description": None,
            "ServiceDays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
            "StartTime": "08:30:00",
            "EndTime": "17:00:00",
            "EffectiveDate": None,
            "ExpireDate": None
        }]
        rec['_scraped'] = True
        rec['_page_reached'] = True
        rec['BusinessStatus'] = "正常營業"
        rec['UpdateTime'] = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        found = True
        print("Updated existing record for Zhaishan Tunnel")
        break

if not found:
    data.setdefault('AttractionServiceTimes', []).append({
        "AttractionID": 'Attraction_371020000A_001337',
        "AttractionName": "翟山坑道",
        "ServiceTimes": [{
            "Name": "一般營業時間",
            "Description": None,
            "ServiceDays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
            "StartTime": "08:30:00",
            "EndTime": "17:00:00",
            "EffectiveDate": None,
            "ExpireDate": None
        }],
        "_scraped": True,
        "_page_reached": True,
        "BusinessStatus": "正常營業",
        "UpdateTime": time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    })
    print("Added new record for Zhaishan Tunnel")

with open(filepath, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
