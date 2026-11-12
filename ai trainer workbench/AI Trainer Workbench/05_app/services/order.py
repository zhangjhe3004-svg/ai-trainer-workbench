# -*- coding: utf-8 -*-
"""订单服务：事务下单、幂等支付、游标分页查询。"""
from datetime import datetime, timezone
from decimal import Decimal

from bson import ObjectId
from bson.decimal128 import Decimal128
from pymongo import ReturnDocument
from pymongo.errors import OperationFailure
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from db import client, db, orders, counters


class StockShortage(Exception):
    pass


def next_order_no(session):
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    doc = counters.find_one_and_update(
        {"_id": "order_no_" + today},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
        session=session)
    return "SO" + today + "{:06d}".format(doc["seq"])


def create_order(user_id, nickname, items, address):
    """items: [{"product_id": str, "sku_id": str, "price": Decimal128, "qty": int}]"""
    with client.start_session() as s:
        for attempt in range(3):
            try:
                with s.start_transaction(
                        read_concern=ReadConcern("majority"),
                        write_concern=WriteConcern("majority")):
                    goods_total = Decimal("0")
                    detail = []
                    for it in items:
                        pid = ObjectId(it["product_id"])
                        r = db.products.update_one(
                            {"_id": pid,
                             "skus": {"$elemMatch": {"sku_id": it["sku_id"],
                                                     "stock": {"$gte": it["qty"]}}}},
                            {"$inc": {"skus.$[e].stock": -it["qty"],
                                      "stock_total": -it["qty"]}},
                            array_filters=[{"e.sku_id": it["sku_id"]}],
                            session=s)
                        if r.modified_count != 1:
                            raise StockShortage(it["sku_id"])
                        price = it["price"].to_decimal() if isinstance(it["price"], Decimal128) \
                            else Decimal(str(it["price"]))
                        subtotal = price * it["qty"]
                        goods_total += subtotal
                        detail.append({"product_id": pid,
                                       "sku_id": it["sku_id"],
                                       "title": it.get("title", ""),
                                       "price": Decimal128(price),
                                       "qty": it["qty"],
                                       "subtotal": Decimal128(subtotal)})

                    order_no = next_order_no(s)
                    now = datetime.now(timezone.utc)
                    oid = orders.insert_one({
                        "order_no": order_no,
                        "user_id": ObjectId(user_id),
                        "user_nickname": nickname,
                        "items": detail,
                        "amount": {"goods_total": Decimal128(goods_total),
                                   "discount": Decimal128(Decimal("0")),
                                   "freight": Decimal128(Decimal("0")),
                                   "payable": Decimal128(goods_total)},
                        "address": address,
                        "status": "created",
                        "timeline": [{"status": "created", "at": now}],
                        "created_at": now,
                    }, session=s).inserted_id
                return str(oid), order_no
            except OperationFailure as e:
                if e.has_error_label("TransientTransactionError") and attempt < 2:
                    continue
                raise


def pay_order(order_no, trade_no, method="wechat"):
    """条件更新实现幂等：重复回调 modified_count 为 0。"""
    now = datetime.now(timezone.utc)
    r = orders.update_one(
        {"order_no": order_no, "status": "created"},
        {"$set": {"status": "paid",
                  "payment": {"method": method, "trade_no": trade_no, "paid_at": now}},
         "$push": {"timeline": {"status": "paid", "at": now}}})
    if r.modified_count == 0:
        return {"ok": True, "duplicated": True}
    return {"ok": True, "duplicated": False}


def list_orders(user_id, cursor=None, size=10):
    """游标式分页：cursor 传上一页最后一条的 created_at。"""
    cond = {"user_id": ObjectId(user_id)}
    if cursor:
        cond["created_at"] = {"$lt": cursor}
    cur = orders.find(cond, {"_id": 0, "order_no": 1, "status": 1,
                             "amount.payable": 1, "created_at": 1}) \
                .sort("created_at", -1).limit(size)
    return [{"order_no": d["order_no"], "status": d["status"],
             "payable": float(d["amount"]["payable"].to_decimal()),
             "created_at": d["created_at"]} for d in cur]
