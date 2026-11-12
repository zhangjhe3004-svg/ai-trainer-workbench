// 建库、集合校验器与索引
use shop

db.createCollection("products", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["sku", "title", "category_id", "price", "status", "created_at"],
    properties: {
      sku:         { bsonType: "string", maxLength: 24 },
      title:       { bsonType: "string", maxLength: 120 },
      category_id: { bsonType: "int" },
      price: {
        bsonType: "object",
        required: ["sale"],
        properties: { sale: { bsonType: ["decimal", "double"], minimum: 0 } }
      },
      tags:        { bsonType: "array", maxItems: 10, items: { bsonType: "string" } },
      status:      { enum: ["on_sale", "off_shelf", "sold_out"] },
      created_at:  { bsonType: "date" }
    }
  } },
  validationLevel: "moderate",
  validationAction: "warn"
});

db.createCollection("orders");
db.createCollection("users");
db.createCollection("reviews");
db.createCollection("carts");
db.createCollection("counters");

// 商品：复合索引按 ESR 原则排列，等值在前、排序字段在后
db.products.createIndex({ category_id: 1, "price.sale": 1 }, { name: "idx_cat_price" });
db.products.createIndex({ tags: 1 }, { name: "idx_tags" });
db.products.createIndex({ title: 1 }, { name: "idx_title" });
db.products.createIndex({ title: "text", tags: "text" },
                        { name: "idx_text", default_language: "none" });
db.products.createIndex({ status: 1, "rating.score": -1 }, { name: "idx_status_rating" });

// 订单：唯一订单号 + 用户维度倒序 + 状态扫描
db.orders.createIndex({ order_no: 1 }, { name: "uniq_order_no", unique: true });
db.orders.createIndex({ user_id: 1, created_at: -1 }, { name: "idx_user_time" });
db.orders.createIndex({ status: 1, created_at: 1 }, { name: "idx_status_time" });

// 评论：商品维度分页
db.reviews.createIndex({ product_id: 1, created_at: -1 }, { name: "idx_prod_time" });

// 用户：手机号唯一
db.users.createIndex({ phone: 1 }, { name: "uniq_phone", unique: true });

// 购物车：TTL 7 天
db.carts.createIndex({ updated_at: 1 }, { name: "ttl_cart", expireAfterSeconds: 604800 });

printjson(db.products.getIndexes().map(i => i.name));
