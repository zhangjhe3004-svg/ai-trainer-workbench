# -*- coding: utf-8 -*-
"""统计服务：聚合管道 + 报表落库。"""
from datetime import datetime, timezone

from db import orders, reports


def category_report(start, end):
    pipeline = [
        {"$match": {"status": {"$in": ["paid", "shipped", "completed"]},
                    "created_at": {"$gte": start, "$lt": end}}},
        {"$unwind": "$items"},
        {"$lookup": {"from": "products", "localField": "items.product_id",
                     "foreignField": "_id", "as": "p"}},
        {"$unwind": "$p"},
        {"$group": {"_id": {"$arrayElemAt": ["$p.category_path", 0]},
                    "revenue": {"$sum": {"$multiply": ["$items.price", "$items.qty"]}},
                    "orderIds": {"$addToSet": "$_id"}}},
        {"$project": {"category": "$_id", "revenue": 1,
                      "orderCount": {"$size": "$orderIds"}, "_id": 0}},
        {"$sort": {"revenue": -1}},
    ]
    rows = list(orders.aggregate(pipeline, allowDiskUse=True))
    for r in rows:
        r["revenue"] = float(r["revenue"].to_decimal()) if hasattr(r["revenue"], "to_decimal") else float(r["revenue"])
    reports.replace_one({"_id": "category_" + start.strftime("%Y%m")},
                        {"rows": rows, "generated_at": datetime.now(timezone.utc)},
                        upsert=True)
    return rows
