// 结果断言：验证语义正确性，避免"不报错但结果错"
use shop

function check(name, actual, expect) {
  print((actual === expect ? "PASS " : "FAIL ") + name + " 实际=" + actual + " 期望=" + expect);
}

check("标签含考研", db.products.countDocuments({ tags: "考研" }) > 0, true);
check("$all 双标签", db.products.countDocuments({ tags: { $all: ["数据库", "考研"] } }) > 0, true);
check("$size=4（应等于商品总数）", db.products.countDocuments({ tags: { $size: 4 } }), db.products.countDocuments());
check("金额区间（Decimal）", db.orders.countDocuments({
  "amount.payable": { $gte: NumberDecimal("100"), $lte: NumberDecimal("200") } }) > 0, true);
check("金额区间（double 错误写法应为 0）", db.orders.countDocuments({
  "amount.payable": { $gte: 100, $lte: 200 } }), 0);
check("锚定正则", db.products.countDocuments({ title: { $regex: "^数据库" } }) > 0, true);

// 数组语义差异：$elemMatch 要求同一元素满足两个条件
var same = db.products.countDocuments({ skus: { $elemMatch: { stock: { $lt: 5 }, price: { $gte: NumberDecimal("30") } } } });
var diff = db.products.countDocuments({ "skus.stock": { $lt: 5 }, "skus.price": { $gte: NumberDecimal("30") } });
print("elemMatch=" + same + "  路径匹配=" + diff + "  差值应大于 0：" + (diff > same));
