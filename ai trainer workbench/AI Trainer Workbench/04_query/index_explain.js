// 索引与 explain 对比：四个案例（对应报告 3.6）
use shop

// 在执行计划树里向下查找索引名：winningPlan 可能是 LIMIT→FETCH→IXSCAN 的嵌套结构
function findIndexName(plan) {
  while (plan) {
    if (plan.indexName) return plan.indexName;
    plan = plan.inputStage;
  }
  return "(未命中索引)";
}

// dropIndex 在索引不存在时会报错，重跑脚本时跳过即可
function dropIfExists(col, name) {
  try { col.dropIndex(name); } catch (e) { print("（无 " + name + " 索引，跳过删除）"); }
}

print("\n===== 案例一：品类 + 价格 + 排序 =====");
dropIfExists(db.products, "idx_cat_price");
var q1 = { category_id: 31,
           "price.sale": { $gte: NumberDecimal("50"), $lte: NumberDecimal("200") } };
var before = db.products.find(q1).sort({ "price.sale": 1 }).limit(10).explain("executionStats");
print("优化前 阶段=" + before.executionStats.executionStages.stage
      + " 扫描文档=" + before.executionStats.totalDocsExamined
      + " 耗时=" + before.executionStats.executionTimeMillis + " ms");

db.products.createIndex({ category_id: 1, "price.sale": 1 }, { name: "idx_cat_price" });
var after = db.products.find(q1).sort({ "price.sale": 1 }).limit(10).explain("executionStats");
print("优化后 扫描键=" + after.executionStats.totalKeysExamined
      + " 扫描文档=" + after.executionStats.totalDocsExamined
      + " 耗时=" + after.executionStats.executionTimeMillis + " ms");
print("索引名=" + findIndexName(after.queryPlanner.winningPlan));

print("\n===== 案例二：订单列表排序（取订单量最大的活跃用户做样本） =====");
var top = db.orders.aggregate([
  { $group: { _id: "$user_id", n: { $sum: 1 } } },
  { $sort: { n: -1 } },
  { $limit: 1 }
]).toArray()[0];
var uid = top._id, cnt = top.n;
print("样本用户订单数=" + cnt);

dropIfExists(db.orders, "idx_user_time");
try {
  var b2 = db.orders.find({ user_id: uid }).sort({ created_at: -1 }).limit(10).explain("executionStats");
  print("优化前 阶段=" + b2.executionStats.executionStages.stage
        + " 扫描文档=" + b2.executionStats.totalDocsExamined
        + " 耗时=" + b2.executionStats.executionTimeMillis + " ms（无索引需内存排序）");
} catch (e) {
  print("优化前 报错=" + e.message);
}
db.orders.createIndex({ user_id: 1, created_at: -1 }, { name: "idx_user_time" });
var a2 = db.orders.find({ user_id: uid }).sort({ created_at: -1 }).limit(10).explain("executionStats");
print("优化后 扫描键=" + a2.executionStats.totalKeysExamined
      + " 扫描文档=" + a2.executionStats.totalDocsExamined
      + " 耗时=" + a2.executionStats.executionTimeMillis + " ms");
print("索引名=" + findIndexName(a2.queryPlanner.winningPlan));

print("\n===== 案例三：深分页 vs 游标分页 =====");
var skipN = Math.max(Math.floor(cnt / 2), 0);   // 保证页码落在该用户订单中段，一定有数据
var d3 = db.orders.find({ user_id: uid }).sort({ created_at: -1 }).skip(skipN).limit(10).explain("executionStats");
print("页码式 skip " + skipN + " 扫描键=" + d3.executionStats.totalKeysExamined
      + " 耗时=" + d3.executionStats.executionTimeMillis + " ms");
var page = db.orders.find({ user_id: uid }).sort({ created_at: -1 }).skip(skipN).limit(10).toArray();
var last = page[page.length - 1];
var c3 = db.orders.find({ user_id: uid, created_at: { $lt: last.created_at } })
             .sort({ created_at: -1 }).limit(10).explain("executionStats");
print("游标式 扫描键=" + c3.executionStats.totalKeysExamined
      + " 耗时=" + c3.executionStats.executionTimeMillis + " ms");

print("\n===== 案例四：锚定 vs 非锚定正则 =====");
var b4 = db.products.find({ title: { $regex: "^数据库" } }).explain("executionStats");
print("锚定 阶段=" + findIndexName(b4.queryPlanner.winningPlan)
      + " 扫描文档=" + b4.executionStats.totalDocsExamined
      + " 耗时=" + b4.executionStats.executionTimeMillis + " ms");
var b5 = db.products.find({ title: { $regex: "数据库" } }).explain("executionStats");
print("非锚定 阶段=" + b5.executionStats.executionStages.stage
      + " 扫描文档=" + b5.executionStats.totalDocsExamined
      + " 耗时=" + b5.executionStats.executionTimeMillis + " ms");
