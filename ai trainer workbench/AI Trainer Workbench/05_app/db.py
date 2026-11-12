# -*- coding: utf-8 -*-
"""连接层：副本集连接串、连接池、读写关注。"""
from pymongo import MongoClient
from pymongo.write_concern import WriteConcern

URI = ("mongodb://shopApp:App%402026@127.0.0.1:27017,127.0.0.1:27018,127.0.0.1:27019"
       "/shop?replicaSet=rs0&authSource=shop"
       "&w=majority&readPreference=secondaryPreferred&retryWrites=true")

client = MongoClient(URI, maxPoolSize=100, serverSelectionTimeoutMS=5000)
db = client.get_database("shop", write_concern=WriteConcern(w="majority"))

products = db.products
orders = db.orders
carts = db.carts
reviews = db.reviews
users = db.users
counters = db.counters
reports = db.reports
