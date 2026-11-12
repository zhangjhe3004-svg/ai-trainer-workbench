// 增删改查：七类查询 + 插入/批量插入 + 更新 + 删除（对应报告 3.4）
use shop

// ---- 插入 ----
// 可重复执行：先清理上一轮演示残留，避免 BK 商品重复累积
db.products.deleteMany({ sku: { $in: ["BK-2024-0031", "TEST-0001"] } });

db.products.insertOne({
  sku: "BK-2024-0031",
  title: "数据库系统概论（第6版）",
  category_id: 31,
  category_path: ["图书", "计算机", "数据库"],
  price: { list: NumberDecimal("59.80"), sale: NumberDecimal("32.90"), currency: "CNY" },
  specs: { 作者: ["王珊", "萨师煊"], 版次: "第6版", 页数: 412 },
  tags: ["数据库", "考研", "教材", "九成新"],
  skus: [
    { sku_id: "BK-2024-0031-A", spec: "平装/九成新", price: NumberDecimal("32.90"), stock: 12 },
    { sku_id: "BK-2024-0031-B", spec: "平装/八成新", price: NumberDecimal("25.00"), stock: 5 }
  ],
  stock_total: 17,
  rating: { score: 4.6, count: 1287 },
  status: "on_sale",
  created_at: new Date()
});

// 批量插入：ordered:false 使个别文档校验失败不中断整批，失败明细从 writeErrors 读取
db.orders.insertMany([
  { order_no: "TEST20261107000001", user_id: ObjectId("66e9f0a1b2c3d4e5f6a7b8c9"),
    items: [], amount: { payable: NumberDecimal("0.00") }, status: "created",
    created_at: new Date() },
  { order_no: "TEST20261107000002", user_id: ObjectId("66e9f0a1b2c3d4e5f6a7b8c9"),
    items: [], amount: { payable: NumberDecimal("0.00") }, status: "created",
    created_at: new Date() },
  { order_no: "TEST20261107000003", user_id: ObjectId("66e9f0a1b2c3d4e5f6a7b8c9"),
    items: [], amount: { payable: NumberDecimal("0.00") }, status: "created",
    created_at: new Date() }
], { ordered: false });

// ---- 条件 + 范围 ----
db.products.find({ category_id: 31, status: "on_sale",
                   "price.sale": { $lte: NumberDecimal("50") } },
                 { _id: 0, title: 1, "price.sale": 1, "rating.score": 1 }).limit(3);

// ---- 逻辑 ----
db.products.find({ status: "on_sale",
                   $or: [{ "price.sale": { $lt: NumberDecimal("20") } },
                         { "rating.score": { $gte: 4.8 } }] }).count();
db.products.find({ status: "on_sale", title: { $not: /数据库/ } }).count();

// ---- 排序分页 ----
db.products.find({ category_id: 31, status: "on_sale" }, { title: 1, "rating.score": 1 })
          .sort({ "rating.score": -1, created_at: -1 }).skip(20).limit(10);

// ---- 正则 ----
// 锚定前缀可命中 idx_title；投影只返回标题
db.products.find({ title: { $regex: "^数据库", $options: "i" } },
                 { title: 1, _id: 0 }).limit(3);

// ---- 数组 ----
db.products.find({ tags: "考研" }).count();
db.products.find({ tags: { $all: ["数据库", "考研"] } }).count();
db.products.find({ tags: { $size: 4 } }).count();
db.products.find({ skus: { $elemMatch: { stock: { $lt: 5 }, price: { $gte: NumberDecimal("30") } } } }).count();
// 对照：路径式匹配允许两个条件由不同 SKU 分别满足，结果数应明显更大
db.products.find({ "skus.stock": { $lt: 5 }, "skus.price": { $gte: NumberDecimal("30") } }).count();
// 投影切片：只返回前两个标签
db.products.find({ sku: "BK-2024-0031" }, { title: 1, tags: { $slice: 2 }, _id: 0 });

// ---- 嵌套文档 ----
db.orders.find({ "address.city": "广州市" }).count();
db.orders.find({ items: { $elemMatch: { sku_id: "BK-2024-0031-A", qty: { $gte: 2 } } } }).count();
db.orders.find({ "items.qty": { $gte: 5 } }).count();
db.products.find({ "specs.页数": { $gt: 400 }, category_id: 31 },
                 { title: 1, "specs.页数": 1, _id: 0 }).limit(2);

// ---- 更新 ----
db.products.updateOne({ sku: "BK-2024-0031" },
  { $set: { status: "on_sale", "specs.版次": "第6版（2023 重印）" },
    $inc: { "rating.count": 1 },
    $currentDate: { updated_at: true } });

db.products.updateMany({ tags: "考研" }, { $set: { "specs.用途": "升学备考" } });

db.products.updateOne({ sku: "BK-2024-0031" },
  { $push: { tags: { $each: ["新版", "现货"], $sort: 1, $slice: 6 } } });
db.products.updateOne({ sku: "BK-2024-0031" }, { $addToSet: { tags: "包邮" } });
db.products.updateOne({ sku: "BK-2024-0031" }, { $pull: { tags: "九成新" } });

db.products.updateOne(
  { sku: "BK-2024-0031", skus: { $elemMatch: { sku_id: "BK-2024-0031-A", stock: { $gte: 2 } } } },
  { $inc: { "skus.$[e].stock": -2, stock_total: -2 } },
  { arrayFilters: [{ "e.sku_id": "BK-2024-0031-A" }] });

db.carts.updateOne({ user_id: ObjectId("66e9f0a1b2c3d4e5f6a7b8c9") },
  { $setOnInsert: { created_at: new Date() },
    $set: { updated_at: new Date() },
    $addToSet: { items: { product_id: ObjectId("66f1a2c3d4e5f6a7b8c9d0e1"),
                          sku_id: "BK-2024-0031-A", qty: 1 } } },
  { upsert: true });

// ---- 删除 ----
// 先插一条测试商品再删除，演示单条插入→删除闭环
db.products.insertOne({
  sku: "TEST-0001", title: "测试商品（待删除）", category_id: 31,
  price: { sale: NumberDecimal("1.00"), currency: "CNY" },
  status: "on_sale", created_at: new Date() });
db.products.deleteOne({ sku: "TEST-0001" });
db.products.deleteMany({ status: "off_shelf", stock_total: 0 });
// 订单只允许物理删除测试数据，业务订单用状态流转而非物理删除
db.orders.deleteMany({ order_no: { $regex: "^TEST" } });
