# -*- coding: utf-8 -*-
"""商品服务：检索与详情。"""
from decimal import Decimal

from bson import ObjectId
from bson.decimal128 import Decimal128

from db import products


def search_products(category_id=None, price_min=0, price_max=1000000, tags=None, page=1, size=10):
    cond = {"status": "on_sale"}
    if category_id:
        cond["category_id"] = category_id
    cond["price.sale"] = {
        "$gte": Decimal128(Decimal(str(price_min))),
        "$lte": Decimal128(Decimal(str(price_max))),
    }
    if tags:
        cond["tags"] = {"$all": list(tags)}
    # 排序与复合索引 {category_id:1,"price.sale":1} 对齐（ESR：等值在前、排序字段在后），
    # 使列表查询直接命中索引顺序，消除内存排序（报告 1.4 / 表 10）
    cur = (products.find(cond, {"_id": 1, "title": 1, "price.sale": 1,
                                "rating.score": 1, "stock_total": 1})
            .sort({"price.sale": 1})
            .skip((page - 1) * size).limit(size))
    return [{"id": str(d["_id"]), "title": d["title"],
             "price": float(d["price"]["sale"].to_decimal()),
             "rating": d.get("rating", {}).get("score", 0),
             "stock": d.get("stock_total", 0)} for d in cur]


def get_product(pid):
    d = products.find_one({"_id": ObjectId(pid)})
    if not d:
        return None
    d["_id"] = str(d["_id"])
    return d
