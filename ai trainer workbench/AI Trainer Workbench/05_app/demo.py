# -*- coding: utf-8 -*-
"""命令行闭环演示：检索 → 加购 → 下单 → 支付 → 查询 → 统计。"""
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from bson import ObjectId
from bson.decimal128 import Decimal128

from db import db, products, users
from services.product import search_products, get_product
from services.cart import add_to_cart, get_cart
from services.order import create_order, pay_order, list_orders, StockShortage
from services.report import category_report


def main():
    t0 = time.time()

    user = users.find_one({}, {"_id": 1, "nickname": 1}) or {"_id": ObjectId(), "nickname": "测试用户"}
    uid, nickname = user["_id"], user.get("nickname", "测试用户")

    print("[1] 检索：品类=31 价格<=50")
    rows = search_products(category_id=31, price_min=0, price_max=50)
    print("    命中 %d 条" % len(rows))
    for r in rows[:3]:
        print("    %s  ¥%.2f  评分%.1f  库存%d" % (r["title"], r["price"], r["rating"], r["stock"]))

    if not rows:
        print("数据为空，请先执行 03_data/generate_data.py")
        return

    # 取一个有库存的 SKU
    doc = products.find_one({"category_id": 31, "skus.stock": {"$gte": 2}})
    if not doc:
        print("没有库存足够的商品，请先造数")
        return

    print("[2] 加购：")
    res = add_to_cart(str(uid), str(doc["_id"]), doc["skus"][0]["sku_id"], 2)
    print("    upsert=%s 购物车 %d 条" % (res["upserted"], len(get_cart(str(uid))["items"])))

    items = [{"product_id": str(doc["_id"]),
              "sku_id": doc["skus"][0]["sku_id"],
              "title": doc["title"],
              "price": doc["skus"][0]["price"],
              "qty": 2}]
    address = {"province": "广东省", "city": "广州市", "district": "从化区",
               "detail": "xx 路 1 号 3 栋 502", "receiver": nickname, "phone": "138****6721"}

    try:
        oid, order_no = create_order(str(uid), nickname, items, address)
        print("[3] 下单：订单号 %s" % order_no)
    except StockShortage as e:
        print("[3] 下单失败：库存不足 %s" % e)
        return

    print("[4] 支付：首次回调 %s" % pay_order(order_no, "4200002xxx20261106"))
    print("[4] 支付：重复回调 %s" % pay_order(order_no, "4200002xxx20261106"))

    print("[5] 查询：该用户最近 3 单")
    for o in list_orders(str(uid), size=3):
        print("    %s  %-9s %.2f  %s" % (o["order_no"], o["status"], o["payable"],
                                         o["created_at"].strftime("%Y-%m-%d %H:%M")))

    print("[6] 统计：上一自然月品类销售额")
    end = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start = (end - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for r in category_report(start, end)[:3]:
        print("    %s  %.2f  订单 %d" % (r["category"], r["revenue"], r["orderCount"]))

    print("闭环完成，用时 %d ms" % ((time.time() - t0) * 1000))


if __name__ == "__main__":
    main()
