// 技能图谱学习推荐系统 —— 索引优化与 explain() 对比（对应 A 卷 2.2 第 5 项）
// 运行时用连接串指定库：mongosh "mongodb://127.0.0.1:27017/learning" 本文件

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

// ============ 案例一：领域 + 难度 + 排序 ============
print("\n===== 案例一：领域 + 难度 + 排序 =====");
dropIfExists(db.skills, "idx_domain_diff");
var q1 = { domain: "编程", difficulty: { $gte: 0.2, $lte: 0.6 } };
var before = db.skills.find(q1).sort({ difficulty: 1 }).limit(10).explain("executionStats");
print("优化前 阶段=" + before.executionStats.executionStages.stage
      + " 扫描文档=" + before.executionStats.totalDocsExamined
      + " 耗时=" + before.executionStats.executionTimeMillis + " ms");

db.skills.createIndex({ domain: 1, difficulty: 1 }, { name: "idx_domain_diff" });
var after = db.skills.find(q1).sort({ difficulty: 1 }).limit(10).explain("executionStats");
print("优化后 扫描键=" + after.executionStats.totalKeysExamined
      + " 扫描文档=" + after.executionStats.totalDocsExamined
      + " 耗时=" + after.executionStats.executionTimeMillis + " ms");
print("索引名=" + findIndexName(after.queryPlanner.winningPlan));

// ============ 案例二：练习记录按学习者排序 ============
print("\n===== 案例二：练习记录按学习者排序 =====");
// 取练习最多的学习者做样本
var top = db.practice_records.aggregate([
  { $group: { _id: "$learner_id", n: { $sum: 1 } } },
  { $sort: { n: -1 } },
  { $limit: 1 }
]).toArray()[0];
var uid = top._id, cnt = top.n;
print("样本学习者练习数=" + cnt);

dropIfExists(db.practice_records, "idx_learner_time");
var b2 = db.practice_records.find({ learner_id: uid }).sort({ finished_at: -1 }).limit(10).explain("executionStats");
print("优化前 阶段=" + b2.executionStats.executionStages.stage
      + " 扫描文档=" + b2.executionStats.totalDocsExamined
      + " 耗时=" + b2.executionStats.executionTimeMillis + " ms（无索引需内存排序）");

db.practice_records.createIndex({ learner_id: 1, finished_at: -1 }, { name: "idx_learner_time" });
var a2 = db.practice_records.find({ learner_id: uid }).sort({ finished_at: -1 }).limit(10).explain("executionStats");
print("优化后 扫描键=" + a2.executionStats.totalKeysExamined
      + " 扫描文档=" + a2.executionStats.totalDocsExamined
      + " 耗时=" + a2.executionStats.executionTimeMillis + " ms");
print("索引名=" + findIndexName(a2.queryPlanner.winningPlan));

// ============ 案例三：锚定 vs 非锚定正则 ============
print("\n===== 案例三：锚定 vs 非锚定正则 =====");
var b4 = db.skills.find({ title: { $regex: "^Python" } }).explain("executionStats");
print("锚定 阶段=" + findIndexName(b4.queryPlanner.winningPlan)
      + " 扫描文档=" + b4.executionStats.totalDocsExamined
      + " 耗时=" + b4.executionStats.executionTimeMillis + " ms");
var b5 = db.skills.find({ title: { $regex: "Python" } }).explain("executionStats");
print("非锚定 阶段=" + b5.executionStats.executionStages.stage
      + " 扫描文档=" + b5.executionStats.totalDocsExamined
      + " 耗时=" + b5.executionStats.executionTimeMillis + " ms");
