// AI 训练师工作台 —— 文档增删改查（对应 A 卷 2.2 第 3 项：七类查询）
// 运行时用连接串指定库：mongosh "mongodb://127.0.0.1:27017/trainer" 本文件

// ============ 插入（含数组 + 嵌套文档）============
db.models.insertOne({
  name: "医疗问答助手-DEMO",
  base_model: "Qwen2.5-7B",
  model_type: "llm",
  description: "演示模型",
  tags: ["医疗", "问答", "微调"],
  status: "registered",
  created_at: new Date()
});

// 批量插入训练运行（ordered:false 使个别失败不中断整批）
db.training_runs.insertMany([
  { name: "TEST-RUN-001", model_id: ObjectId(), dataset_id: ObjectId(),
    task_type: "fine_tuning", status: "pending", progress: 0, logs: [],
    created_at: new Date() },
  { name: "TEST-RUN-002", model_id: ObjectId(), dataset_id: ObjectId(),
    task_type: "lora", status: "completed", progress: 1, logs: [],
    created_at: new Date() }
], { ordered: false });

// ============ 1. 条件查询 ============
print("== 1. 条件查询：类型为 llm 的模型 ==");
printjson(db.models.find({ model_type: "llm" }, { name: 1, model_type: 1, _id: 0 }).limit(3).toArray());

// ============ 2. 逻辑与范围查询 ============
print("== 2. 逻辑与范围：状态为 ready 或 training 的模型 ==");
print("数量：" + db.models.find({ status: { $in: ["ready", "training"] } }).count());

print("== 2b. 逻辑 $or：类型为 llm 或 embedding ==");
print("数量：" + db.models.find({ $or: [{ model_type: "llm" }, { model_type: "embedding" }] }).count());

// ============ 3. 排序分页 ============
print("== 3. 排序分页：按创建时间降序取前 3 条模型 ==");
printjson(db.models.find({}, { name: 1, created_at: 1, _id: 0 })
         .sort({ created_at: -1 }).limit(3).toArray());

// ============ 4. 正则查询 ============
print("== 4. 正则：名称以 'Qwen' 开头的模型 ==");
printjson(db.models.find({ name: { $regex: "^Qwen", $options: "i" } },
               { name: 1, _id: 0 }).limit(3).toArray());

// ============ 5. 数组查询 ============
print("== 5. 数组：tags 包含 '医疗' 的模型数 ==");
print("数量：" + db.models.find({ tags: "医疗" }).count());

print("== 5b. 数组：tags 同时含多标签 ==");
printjson(db.models.find({ tags: { $all: ["医疗", "问答"] } }, { name: 1, tags: 1, _id: 0 }).limit(3).toArray());

print("== 5c. 数组：训练运行日志数 = 0 的运行 ==");
print("数量：" + db.training_runs.find({ logs: { $size: 0 } }).count());

// ============ 6. 嵌套文档查询 ============
print("== 6. 嵌套文档：参数快照中 epochs 为 3 的训练运行 ==");
printjson(db.training_runs.find({ "params.epochs": 3 }, { name: 1, "params.epochs": 1, _id: 0 }).limit(3).toArray());

// ============ 7. 更新 ============
print("== 7. 更新：修改模型状态并 $currentDate ==");
var u1 = db.models.updateOne({ name: "医疗问答助手-DEMO" },
  { $set: { status: "ready" }, $currentDate: { updated_at: true } });
printjson({ matched: u1.matchedCount, modified: u1.modifiedCount });

print("== 7b. 数组更新：$addToSet 追加标签 ==");
db.models.updateOne({ name: "医疗问答助手-DEMO" }, { $addToSet: { tags: "已训练" } });
printjson(db.models.findOne({ name: "医疗问答助手-DEMO" }, { name: 1, tags: 1, status: 1, _id: 0 }));

// ============ 8. 删除 ============
print("== 8. 删除：清理测试数据 ==");
var d1 = db.models.deleteOne({ name: "医疗问答助手-DEMO" });
var d2 = db.training_runs.deleteMany({ name: { $regex: "^TEST" } });
printjson({ deletedModels: d1.deletedCount, deletedRuns: d2.deletedCount });
