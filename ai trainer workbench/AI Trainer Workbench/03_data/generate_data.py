# -*- coding: utf-8 -*-
"""造数脚本：商品、用户、订单、评论。

用法：
    python generate_data.py --products 120000 --users 50000 --orders 300000 --reviews 120000

要点（对应报告 3.3 与表 8）：
- 金额统一 Decimal128，时间统一 UTC；先建索引再灌数据可省去重建时间。
- 订单明细 1~8 条，created_at 均匀落在 2025-11 至 2026-10 十二个月。
- 约 20% 订单集中到前 100 个「活跃用户」，为 3.6 节排序超限与深分页对比提供样本。
- 评论关联订单生成（引用 order_id / product_id），评分 1~5 近似正态分布。
- 订单按 2 万条分块生成、分块写入，避免一次性把全部文档堆在内存。
"""
import argparse
import random
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from bson import ObjectId
from bson.decimal128 import Decimal128
from pymongo import MongoClient, InsertOne
from pymongo.write_concern import WriteConcern

URI = ("mongodb://shopApp:App%402026@127.0.0.1:27017,127.0.0.1:27018,127.0.0.1:27019"
       "/shop?replicaSet=rs0&authSource=shop&w=majority")
CLIENT = MongoClient(URI, maxPoolSize=50)
DB = CLIENT.get_database("shop", write_concern=WriteConcern(w="majority"))

CATEGORIES = [
    ("图书", "计算机", "数据库", 31),
    ("图书", "计算机", "算法", 32),
    ("图书", "外语", "英语", 33),
    ("数码", "配件", "键盘", 51),
    ("数码", "配件", "耳机", 52),
    ("文创", "文具", "笔记本", 71),
    ("文创", "周边", "徽章", 72),
]

BOOK_SPECS = [
    {"作者": ["王珊", "杜小勇"], "版次": "第6版", "页数": 412, "出版日期": datetime(2023, 3, 1, tzinfo=timezone.utc)},
    {"作者": ["Cormen T H"], "版次": "第3版", "页数": 780},
    {"作者": ["Kleppmann M"], "版次": "第1版", "页数": 616},
]
TAGS = ["数据库", "考研", "教材", "九成新", "包邮", "现货", "清仓"]
STATUS_LIST = ["on_sale"] * 8 + ["off_shelf", "sold_out"]
ORDER_STATUS = ["created"] * 2 + ["paid"] * 5 + ["shipped"] * 2 + ["completed"] * 3
CITIES = ["广州市", "江门市", "佛山市"]

ACTIVE_USERS = 100        # 头部活跃用户数
ACTIVE_RATIO = 0.2        # 集中到活跃用户的订单比例
ORDER_CHUNK = 20000       # 订单分块生成/写入的块大小


def bulk_write(col, docs, size=1000):
    """无序批量写入，单批失败不中断整批。"""
    total = 0
    for i in range(0, len(docs), size):
        batch = [InsertOne(d) for d in docs[i:i + size]]
        r = col.bulk_write(batch, ordered=False)
        total += r.inserted_count
    return total


def gen_products(n):
    docs = []
    for i in range(n):
        cat = random.choice(CATEGORIES)
        price = Decimal(str(round(random.uniform(9, 480), 2)))
        list_price = (price * Decimal("1.2")).quantize(Decimal("0.01"))
        spec = random.choice(BOOK_SPECS) if cat[0] == "图书" else {"成色": "九成新", "保修": "3个月"}
        stock = random.randint(0, 60)
        docs.append({
            "_id": ObjectId(),
            "sku": "SK-%06d" % i,
            "title": "%s入门与实战（第%d辑）" % (cat[2], i % 20 + 1),
            "category_id": cat[3],
            "category_path": [cat[0], cat[1], cat[2]],
            "brand": {"name": "校园书店", "country": "CN"},
            "price": {"list": Decimal128(list_price), "sale": Decimal128(price), "currency": "CNY"},
            "specs": spec,
            "tags": random.sample(TAGS, 4),
            "skus": [{"sku_id": "SK-%06d-A" % i, "spec": "标准",
                      "price": Decimal128(price), "stock": stock}],
            "stock_total": stock,
            "rating": {"score": round(random.uniform(3.5, 5.0), 1), "count": random.randint(1, 2000)},
            "status": random.choice(STATUS_LIST),
            "created_at": datetime.now(timezone.utc) - timedelta(days=random.randint(0, 365)),
        })
    return docs


def gen_users(n):
    docs = []
    for i in range(n):
        docs.append({
            "_id": ObjectId(),
            "nickname": "用户%05d" % i,
            "phone": "138%08d" % i,
            "level": random.choice(["normal", "normal", "silver", "gold"]),
            "tags": random.sample(["高校", "二手", "数码"], 2),
            "profile": {"campus": random.choice(["广州", "江门", "佛山"]), "age": random.randint(18, 40)},
            "created_at": datetime.now(timezone.utc) - timedelta(days=random.randint(1, 900)),
        })
    return docs


def gen_orders(count, seq_start, prods, user_docs):
    """生成一批订单。seq_start 保证 order_no 全局唯一（uniq_order_no 索引要求）。"""
    active = user_docs[:ACTIVE_USERS]
    docs = []
    base = datetime(2025, 11, 1, tzinfo=timezone.utc)
    for i in range(count):
        seq = seq_start + i
        k = random.randint(1, min(8, len(prods)))   # 明细 1~8 条（报告 1.1.3 / 表 8）
        items = []
        total = Decimal("0")
        for p in random.sample(prods, k):
            qty = random.randint(1, 3)
            price = p["price"]["sale"].to_decimal()
            subtotal = price * qty
            total += subtotal
            items.append({"product_id": p["_id"], "sku_id": p["skus"][0]["sku_id"],
                          "title": p["title"], "price": Decimal128(price), "qty": qty,
                          "subtotal": Decimal128(subtotal)})
        u = random.choice(active) if random.random() < ACTIVE_RATIO else random.choice(user_docs)
        created = base + timedelta(minutes=random.randint(0, 365 * 24 * 60))
        docs.append({
            "_id": ObjectId(),
            "order_no": "SO%s%06d" % (created.strftime("%Y%m%d"), seq),
            "user_id": u["_id"],
            "user_nickname": u["nickname"],
            "items": items,
            "amount": {"goods_total": Decimal128(total), "discount": Decimal128(Decimal("0")),
                       "freight": Decimal128(Decimal("0")), "payable": Decimal128(total)},
            "address": {"province": "广东省", "city": random.choice(CITIES),
                        "district": "从化区", "detail": "xx 路 %d 号" % random.randint(1, 999),
                        "receiver": u["nickname"], "phone": "138****%04d" % (i % 10000)},
            "status": random.choice(ORDER_STATUS),
            "timeline": [{"status": "created", "at": created}],
            "created_at": created,
        })
    return docs


def gen_reviews(n, order_pool):
    """评论关联订单生成：product_id 取自订单明细，order_id / user_id 引用原订单。"""
    docs = []
    for i in range(n):
        od = random.choice(order_pool)
        it = random.choice(od["items"])
        rating = max(1, min(5, int(round(random.gauss(4, 0.9)))))   # 近似正态（表 8）
        docs.append({
            "product_id": it["product_id"],
            "order_id": od["_id"],
            "user_id": od["user_id"],
            "rating": rating,
            "content": random.choice(["书很新，发货快", "性价比高", "包装完好", "有点旧但可接受"]),
            "images": [],
            "created_at": od["created_at"] + timedelta(hours=random.randint(1, 240)),
        })
    return docs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--products", type=int, default=120000)
    ap.add_argument("--users", type=int, default=50000)
    ap.add_argument("--orders", type=int, default=300000)
    ap.add_argument("--reviews", type=int, default=120000)
    args = ap.parse_args()

    t0 = time.time()
    prods = gen_products(args.products)
    bulk_write(DB.products, prods)
    print("[1/4] products %6d 条写入完成，耗时 %5.1f s" % (len(prods), time.time() - t0))

    t1 = time.time()
    us = gen_users(args.users)
    bulk_write(DB.users, us)
    print("[2/4] users    %6d 条写入完成，耗时 %5.1f s" % (len(us), time.time() - t1))

    t2 = time.time()
    total = 0
    order_pool = []          # 每块抽样保留部分订单，供评论关联，避免全部驻留内存
    for start in range(0, args.orders, ORDER_CHUNK):
        cnt = min(ORDER_CHUNK, args.orders - start)
        chunk = gen_orders(cnt, start, prods, us)
        total += bulk_write(DB.orders, chunk)
        order_pool.extend(random.sample(chunk, min(50, len(chunk))))
    print("[3/4] orders   %6d 条写入完成，耗时 %5.1f s" % (total, time.time() - t2))

    t3 = time.time()
    rvs = gen_reviews(args.reviews, order_pool)
    bulk_write(DB.reviews, rvs)
    print("[4/4] reviews  %6d 条写入完成，耗时 %5.1f s" % (len(rvs), time.time() - t3))
    print("合计 %d 条，总耗时 %.1f s"
          % (len(prods) + len(us) + total + len(rvs), time.time() - t0))


if __name__ == "__main__":
    main()
