// AI 训练师工作台 —— 索引优化与 explain() 对比（对应 A 卷 2.2 第 5 项）
// 运行时用连接串指定库：mongosh "mongodb://127.0.0.1:27017/trainer" 本文件

// 在执行计划树里向下查找索引名
function findIndexName(plan) {
  while (plan) {
    if (plan.indexName) return plan.indexName;
    plan = plan.inputStage;
  }
  return "(未命中索引)";
}
function dropIfExists(col, name) {
  try { col.dropIndex(name); } catch (e) { print("（无 " + name + " 索引，跳过删除）"); }
}

// ============ 案例一：模型类型 + 时间排序 ============
print("\n===== 案例一：模型类型 + 时间排序 =====");
dropIfExists(db.models, "idx_model_type_time");
var q1 = { model_type: "llm" };
var before = db.models.find(q1).sort({ created_at: -1 }).limit(10).explain("executionStats");
print("优化前 阶段=" + before.executionStats.executionStages.stage
      + " 扫描文档=" + before.executionStats.totalDocsExamined
      + " 耗时=" + before.executionStats.executionTimeMillis + " ms");

db.models.createIndex({ model_type: 1, created_at: -1 }, { name: "idx_model_type_time" });
var after = db.models.find(q1).sort({ created_at: -1 }).limit(10).explain("executionStats");
print("优化后 扫描键=" + after.executionStats.totalKeysExamined
      + " 扫描文档=" + after.executionStats.totalDocsExamined
      + " 耗时=" + after.executionStats.executionTimeMillis + " ms");
print("索引名=" + findIndexName(after.queryPlanner.winningPlan));

// ============ 案例二：训练运行按模型排序 ============
print("\n===== 案例二：训练运行按模型排序 =====");
var top = db.training_runs.aggregate([
  { $group: { _id: "$model_id", n: { $sum: 1 } } },
  { $sort: { n: -1 } },
  { $limit: 1 }
]).toArray()[0];
var mid = top._id, cnt = top.n;
print("样本模型训练数=" + cnt);

dropIfExists(db.training_runs, "idx_run_model_time");
var b2 = db.training_runs.find({ model_id: mid }).sort({ created_at: -1 }).limit(10).explain("executionStats");
print("优化前 阶段=" + b2.executionStats.executionStages.stage
      + " 扫描文档=" + b2.executionStats.totalDocsExamined
      + " 耗时=" + b2.executionStats.executionTimeMillis + " ms（无索引需内存排序）");

db.training_runs.createIndex({ model_id: 1, created_at: -1 }, { name: "idx_run_model_time" });
var a2 = db.training_runs.find({ model_id: mid }).sort({ created_at: -1 }).limit(10).explain("executionStats");
print("优化后 扫描键=" + a2.executionStats.totalKeysExamined
      + " 扫描文档=" + a2.executionStats.totalDocsExamined
      + " 耗时=" + a2.executionStats.executionTimeMillis + " ms");
print("索引名=" + findIndexName(a2.queryPlanner.winningPlan));

// ============ 案例三：锚定 vs 非锚定正则 ============
print("\n===== 案例三：锚定 vs 非锚定正则 =====");
var b4 = db.models.find({ name: { $regex: "^Qwen" } }).explain("executionStats");
print("锚定 阶段=" + findIndexName(b4.queryPlanner.winningPlan)
      + " 扫描文档=" + b4.executionStats.totalDocsExamined
      + " 耗时=" + b4.executionStats.executionTimeMillis + " ms");
var b5 = db.models.find({ name: { $regex: "Qwen" } }).explain("executionStats");
print("非锚定 阶段=" + b5.executionStats.executionStages.stage
      + " 扫描文档=" + b5.executionStats.totalDocsExamined
      + " 耗时=" + b5.executionStats.executionTimeMillis + " ms");
