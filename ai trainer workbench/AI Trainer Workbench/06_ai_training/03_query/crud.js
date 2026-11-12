// 技能图谱学习推荐系统 —— 文档增删改查（对应 A 卷 2.2 第 3 项：七类查询）
// 运行时用连接串指定库：mongosh "mongodb://127.0.0.1:27017/learning" 本文件

// ============ 插入（含数组 + 嵌套文档）============
db.skills.insertOne({
  code: "SK-DEMO-001",
  title: "Python 列表与循环",
  domain: "编程",
  sub_domain: "Python",
  category_path: ["编程", "Python", "基础语法"],
  difficulty: 0.3,
  tags: ["入门", "语法", "必考"],
  specs: { 语言: "Python 3", 前置: "变量与类型", 预计时长: "2h" },
  prerequisites: ["变量与类型"],
  status: "active",
  created_at: new Date()
});

// 批量插入练习记录（ordered:false 使个别失败不中断整批）
db.practice_records.insertMany([
  { record_no: "TEST000001", learner_id: ObjectId(), skills: [],
    score: 0, status: "completed", finished_at: new Date() },
  { record_no: "TEST000002", learner_id: ObjectId(), skills: [],
    score: 0, status: "completed", finished_at: new Date() }
], { ordered: false });

// ============ 1. 条件查询 ============
print("== 1. 条件查询：难度 >= 0.7 的技能 ==");
printjson(db.skills.find({ difficulty: { $gte: 0.7 } }, { title: 1, difficulty: 1, _id: 0 }).limit(3).toArray());

// ============ 2. 逻辑与范围查询 ============
print("== 2. 逻辑与范围：编程领域且难度 0.3~0.6 ==");
printjson(db.skills.find({ domain: "编程", difficulty: { $gte: 0.3, $lte: 0.6 } },
               { title: 1, difficulty: 1, _id: 0 }).limit(3).toArray());

print("== 2b. 逻辑 $or：难度 < 0.2 或难度 > 0.9 ==");
print("数量：" + db.skills.find({ $or: [{ difficulty: { $lt: 0.2 } }, { difficulty: { $gt: 0.9 } }] }).count());

// ============ 3. 排序分页 ============
print("== 3. 排序分页：按难度降序取前 3 条 ==");
printjson(db.skills.find({}, { title: 1, difficulty: 1, _id: 0 })
         .sort({ difficulty: -1 }).limit(3).toArray());

// ============ 4. 正则查询 ============
print("== 4. 正则：标题以 'Python' 开头的技能 ==");
printjson(db.skills.find({ title: { $regex: "^Python", $options: "i" } },
               { title: 1, _id: 0 }).limit(3).toArray());

// ============ 5. 数组查询 ============
print("== 5. 数组：tags 包含 '入门' 的技能数 ==");
print("数量：" + db.skills.find({ tags: "入门" }).count());

print("== 5b. 数组：tags 同时含多标签 ==");
printjson(db.skills.find({ tags: { $all: ["语法", "必考"] } }, { title: 1, tags: 1, _id: 0 }).limit(3).toArray());

print("== 5c. 数组：练习记录明细数 = 3 的记录 ==");
print("数量：" + db.practice_records.find({ skills: { $size: 3 } }).count());

// ============ 6. 嵌套文档查询 ============
print("== 6. 嵌套文档：规格中语言为 Python 3 的技能 ==");
printjson(db.skills.find({ "specs.语言": "Python 3" }, { title: 1, "specs.语言": 1, _id: 0 }).limit(3).toArray());

print("== 6b. 嵌套数组：练习明细中编程领域且答对的记录 ==");
print("数量：" + db.practice_records.find({ skills: { $elemMatch: { domain: "编程", correct: true } } }).count());

// ============ 7. 更新 ============
print("== 7. 更新：修改技能难度并 $inc 计数 ==");
var u1 = db.skills.updateOne({ code: "SK-DEMO-001" },
  { $set: { difficulty: 0.4 }, $inc: { "stats.practice_count": 1 },
    $currentDate: { updated_at: true } });
printjson({ matched: u1.matchedCount, modified: u1.modifiedCount });

print("== 7b. 数组更新：$addToSet 追加标签 ==");
db.skills.updateOne({ code: "SK-DEMO-001" }, { $addToSet: { tags: "高频" } });
printjson(db.skills.findOne({ code: "SK-DEMO-001" }, { title: 1, tags: 1, difficulty: 1, _id: 0 }));

// ============ 8. 删除 ============
print("== 8. 删除：清理测试数据 ==");
var d1 = db.skills.deleteOne({ code: "SK-DEMO-001" });
var d2 = db.practice_records.deleteMany({ record_no: { $regex: "^TEST" } });
printjson({ deletedSkills: d1.deletedCount, deletedRecords: d2.deletedCount });
