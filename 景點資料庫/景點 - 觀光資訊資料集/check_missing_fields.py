import os
import csv
from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    "bolt://localhost:7687",
    auth=("neo4j", os.environ["NEO4J_PASSWORD"]),
)

# name / lat / lon 已由 parser 保證不會空，不需要再檢查
FIELDS = [
    "description", "attraction_classes", "address", "traffic_info",
    "web_url", "reservation_urls", "service_time_info", "parking",
    "update_time", "images", "social_media_urls", "tags",
]


def is_empty(value):
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, list) and len(value) == 0:
        return True
    return False


def main():
    with driver.session() as session:
        query = "MATCH (n:Attraction) RETURN n.id AS id, n.name AS name, " + \
                ", ".join(f"n.{f} AS {f}" for f in FIELDS)
        rows = [dict(r) for r in session.run(query)]

    total = len(rows)
    summary = {f: 0 for f in FIELDS}
    detail_rows = []

    for row in rows:
        missing = [f for f in FIELDS if is_empty(row.get(f))]
        if missing:
            for f in missing:
                summary[f] += 1
            detail_rows.append({
                "id": row["id"],
                "name": row.get("name") or "",
                "missing_fields": ";".join(missing),
            })

    print(f"總筆數: {total}\n")
    print("各欄位缺值統計:")
    for f, count in sorted(summary.items(), key=lambda x: -x[1]):
        if count:
            print(f"  {f}: {count} 筆 ({count / total * 100:.1f}%)")

    with open("missing_fields_report.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "name", "missing_fields"])
        writer.writeheader()
        writer.writerows(detail_rows)

    print(f"\n已輸出詳細報表: missing_fields_report.csv（共 {len(detail_rows)} 筆有缺值的景點）")
    driver.close()


if __name__ == "__main__":
    main()
