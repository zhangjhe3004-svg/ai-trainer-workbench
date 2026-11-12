// AI 训练师工作台 —— 聚合管道统计（对应 A 卷 2.2 第 4 项）
// 运行时用连接串指定库：mongosh "mongodb://127.0.0.1:27017/trainer" 本文件

// ============ 1. 按类型统计模型数 ============
print("== 1. 按类型统计模型数与状态分布 ==");
printjson(db.models.aggregate([
  { $group: { _id: "$model_type", count: { $sum: 1 } } },
  { $sort: { count: -1 } }
]).toArray());

// ============ 2. 按月统计训练运行量 ============
print("== 2. 按月统计训练运行数 ==");
printjson(db.training_runs.aggregate([
  { $group: { _id: { $dateToString: { format: "%Y-%m", date: "$created_at" } },
              count: { $sum: 1 } } },
  { $sort: { _id: 1 } },
  { $limit: 6 }
]).toArray());

// ============ 3. 关联统计：每个模型的训练次数 ============
print("== 3. 关联统计：训练最多的前 5 个模型 ==");
printjson(db.training_runs.aggregate([
  { $group: { _id: "$model_id", count: { $sum: 1 } } },
  { $sort: { count: -1 } },
  { $limit: 5 },
  { $lookup: { from: "models", localField: "_id", foreignField: "_id", as: "m" } },
  { $project: { name: { $arrayElemAt: ["$m.name", 0] }, count: 1, _id: 0 } }
]).toArray());

// ============ 4. 展开明细：统计每个技能被挂载的次数 ============
print("== 4. 展开：按类别统计技能数 ==");
printjson(db.skills.aggregate([
  { $group: { _id: "$category", count: { $sum: 1 } } },
  { $sort: { count: -1 } }
]).toArray());

// ============ 5. 关联统计：已挂载技能最多的模型 ============
print("== 5. 关联统计：已挂载技能最多的前 5 个模型 ==");
printjson(db.skills.aggregate([
  { $match: { model_id: { $ne: null } } },
  { $group: { _id: "$model_id", count: { $sum: 1 } } },
  { $sort: { count: -1 } },
  { $limit: 5 },
  { $lookup: { from: "models", localField: "_id", foreignField: "_id", as: "m" } },
  { $project: { name: { $arrayElemAt: ["$m.name", 0] }, count: 1, _id: 0 } }
]).toArray());

// ============ 6. 分面统计：$facet 多维分面 ============
print("== 6. 分面：训练运行按状态 + 类型分桶 ==");
printjson(db.training_runs.aggregate([
  { $facet: {
      byStatus: [
        { $group: { _id: "$status", n: { $sum: 1 } } },
        { $sort: { n: -1 } } ],
      byType: [
        { $group: { _id: "$task_type", n: { $sum: 1 } } },
        { $sort: { n: -1 } } ]
  } }
]).toArray());
