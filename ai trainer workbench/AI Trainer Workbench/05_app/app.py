# -*- coding: utf-8 -*-
"""Flask 接口层：只做参数校验与结果包装。"""
from datetime import datetime

from flask import Flask, jsonify, request

from services.product import search_products, get_product
from services.cart import add_to_cart, get_cart
from services.order import create_order, pay_order, list_orders, StockShortage
from services.report import category_report

app = Flask(__name__)


@app.get("/products")
def api_products():
    kw = request.args
    rows = search_products(
        category_id=int(kw["category_id"]) if "category_id" in kw else None,
        price_min=float(kw.get("price_min", 0)),
        price_max=float(kw.get("price_max", 10 ** 6)),
        tags=kw.getlist("tag"),
        page=int(kw.get("page", 1)),
        size=int(kw.get("size", 10)))
    return jsonify({"code": 0, "data": rows})


@app.get("/products/<pid>")
def api_product_detail(pid):
    d = get_product(pid)
    if not d:
        return jsonify({"code": 404, "msg": "商品不存在"}), 404
    return jsonify({"code": 0, "data": d})


@app.post("/cart")
def api_add_cart():
    body = request.get_json()
    add_to_cart(body["user_id"], body["product_id"], body["sku_id"], body.get("qty", 1))
    return jsonify({"code": 0})


@app.get("/cart/<user_id>")
def api_cart(user_id):
    return jsonify({"code": 0, "data": get_cart(user_id)})


@app.post("/orders")
def api_create_order():
    body = request.get_json()
    try:
        oid, no = create_order(body["user_id"], body["nickname"],
                               body["items"], body["address"])
    except StockShortage as e:
        return jsonify({"code": 4001, "msg": "库存不足：%s" % e}), 400
    return jsonify({"code": 0, "order_id": oid, "order_no": no})


@app.post("/pay/callback")
def api_pay():
    body = request.get_json()
    return jsonify(pay_order(body["order_no"], body["trade_no"],
                             body.get("method", "wechat")))


@app.get("/orders")
def api_orders():
    raw = request.args.get("cursor")
    cursor = datetime.fromisoformat(raw) if raw else None  # 游标是时间戳字符串，需转回 datetime
    rows = list_orders(request.args["user_id"], cursor=cursor,
                       size=int(request.args.get("size", 10)))
    return jsonify({"code": 0, "data": rows})


@app.get("/report/category")
def api_report():
    start = datetime.fromisoformat(request.args["start"])
    end = datetime.fromisoformat(request.args["end"])
    return jsonify({"code": 0, "data": category_report(start, end)})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
