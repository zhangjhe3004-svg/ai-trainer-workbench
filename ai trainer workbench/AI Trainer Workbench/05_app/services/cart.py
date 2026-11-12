# -*- coding: utf-8 -*-
"""购物车服务：upsert + TTL。"""
from datetime import datetime, timezone

from bson import ObjectId

from db import carts


def add_to_cart(user_id, product_id, sku_id, qty=1):
    now = datetime.now(timezone.utc)
    r = carts.update_one(
        {"user_id": ObjectId(user_id)},
        {"$setOnInsert": {"created_at": now},
         "$set": {"updated_at": now},
         "$addToSet": {"items": {"product_id": ObjectId(product_id),
                                 "sku_id": sku_id, "qty": qty}}},
        upsert=True)
    return {"upserted": r.upserted_id is not None, "modified": r.modified_count}


def get_cart(user_id):
    d = carts.find_one({"user_id": ObjectId(user_id)})
    if not d:
        return {"items": []}
    d["_id"] = str(d["_id"])
    d["user_id"] = str(d["user_id"])
    for it in d["items"]:
        it["product_id"] = str(it["product_id"])
    return d
