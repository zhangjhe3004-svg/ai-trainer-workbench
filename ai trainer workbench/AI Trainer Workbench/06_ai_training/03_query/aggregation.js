// 技能图谱学习推荐系统 —— 聚合管道统计（对应 A 卷 2.2 第 4 项）
// 运行时用连接串指定库：mongosh "mongodb://127.0.0.1:27017/learning" 本文件

// ============ 1. 按领域统计技能数 ============
print("== 1. 按领域统计技能数与平均难度 ==");
printjson(db.skills.aggregate([
  { $group: { _id: "$domain", count: { $sum: 1 }, avgDiff: { $avg: "$difficulty" } } },
  { $sort: { count: -1 } }
]).toArray());

// ============ 2. 按月统计练习量 ============
print("== 2. 按月统计练习记录数 ==");
printjson(db.practice_records.aggregate([
  { $group: { _id: { $dateToString: { format: "%Y-%m", date: "$finished_at" } },
              count: { $sum: 1 },
              avgScore: { $avg: "$score" } } },
  { $sort: { _id: 1 } },
  { $limit: 6 }
]).toArray());

// ============ 3. 关联统计：每个学习者的练习次数 ============
print("== 3. 关联统计：练习最多的前 5 个学习者 ==");
printjson(db.practice_records.aggregate([
  { $group: { _id: "$learner_id", count: { $sum: 1 } } },
  { $sort: { count: -1 } },
  { $limit: 5 },
  { $lookup: { from: "learners", localField: "_id", foreignField: "_id", as: "l" } },
  { $project: { nickname: { $arrayElemAt: ["$l.nickname", 0] }, count: 1, _id: 0 } }
]).toArray());

// ============ 4. 展开明细：统计每个技能被练习的次数 ============
print("== 4. 展开明细：被练习最多的前 5 个技能 ==");
printjson(db.practice_records.aggregate([
  { $unwind: "$skills" },
  { $group: { _id: "$skills.skill_id", count: { $sum: 1 }, correct: { $sum: { $cond: ["$skills.correct", 1, 0] } } } },
  { $sort: { count: -1 } },
  { $limit: 5 },
  { $lookup: { from: "skills", localField: "_id", foreignField: "_id", as: "s" } },
  { $project: { title: { $arrayElemAt: ["$s.title", 0] }, count: 1, correct: 1, _id: 0 } }
]).toArray());

// ============ 5. 关联统计：金牌学习者的练习数与自评数 ============
print("== 5. 关联统计：金牌学习者的练习数与自评数 ==");
printjson(db.learners.aggregate([
  { $match: { level: "gold" } },
  { $lookup: { from: "practice_records", localField: "_id", foreignField: "learner_id", as: "recs" } },
  { $lookup: { from: "assessments", localField: "_id", foreignField: "learner_id", as: "rvs" } },
  { $project: { nickname: 1, practiceCount: { $size: "$recs" }, reviewCount: { $size: "$rvs" }, _id: 0 } },
  { $sort: { practiceCount: -1 } },
  { $limit: 5 }
]).toArray());

// ============ 6. 分面统计：$facet 多维分面 ============
print("== 6. 分面：技能点按领域 + 难度分桶 ==");
printjson(db.skills.aggregate([
  { $match: { status: "active" } },
  { $facet: {
      byDomain: [
        { $group: { _id: "$domain", n: { $sum: 1 } } },
        { $sort: { n: -1 } } ],
      diffBuckets: [
        { $bucket: { groupBy: "$difficulty",
                     boundaries: [0, 0.3, 0.6, 0.9, 1.0],
                     default: "0.9+",
                     output: { n: { $sum: 1 } } } } ]
  } }
]).toArray());
