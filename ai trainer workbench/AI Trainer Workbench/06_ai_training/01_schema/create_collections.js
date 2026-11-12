// 技能图谱学习推荐系统 —— 业务库建库、校验器与索引
// db: learning（运行时用连接串指定库：mongosh "mongodb://127.0.0.1:27017/learning" 本文件）
// 对应 A 卷 2.2 方向一：创建数据库和集合

// ============ 1. skills 技能点（含数组 + 嵌套文档）============
db.createCollection("skills", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["code", "title", "domain", "difficulty", "created_at"],
    properties: {
      code:         { bsonType: "string" },
      title:        { bsonType: "string", maxLength: 120 },
      domain:       { bsonType: "string" },
      sub_domain:   { bsonType: "string" },
      category_path:{ bsonType: "array", items: { bsonType: "string" } },
      difficulty:   { bsonType: "double", minimum: 0, maximum: 1 },
      tags:         { bsonType: "array", items: { bsonType: "string" } },
      specs:        { bsonType: "object" },                  // 异构规格（嵌套文档）
      prerequisites:{ bsonType: "array", items: { bsonType: "string" } },  // 前置依赖
      status:       { enum: ["active", "deprecated"] },
      created_at:   { bsonType: "date" }
    }
  } },
  validationLevel: "moderate",
  validationAction: "warn"
});

// ============ 2. learners 学习者 ============
db.createCollection("learners", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["nickname", "level", "created_at"],
    properties: {
      nickname: { bsonType: "string" },
      phone:    { bsonType: "string" },
      level:    { enum: ["beginner", "silver", "gold"] },
      years:    { bsonType: "int", minimum: 0 },
      tags:     { bsonType: "array", items: { bsonType: "string" } },
      profile:  { bsonType: "object" },                     // 画像（嵌套文档）
      created_at: { bsonType: "date" }
    }
  } },
  validationLevel: "moderate",
  validationAction: "warn"
});

// ============ 3. practice_records 练习记录（含数组 + 嵌套文档）============
db.createCollection("practice_records", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["record_no", "learner_id", "skills", "status", "finished_at"],
    properties: {
      record_no:  { bsonType: "string" },
      learner_id: { bsonType: "objectId" },
      skills:     { bsonType: "array", items: { bsonType: "object" } },  // 明细数组
      score:      { bsonType: "double", minimum: 0, maximum: 1 },
      status:     { enum: ["started", "completed", "abandoned"] },
      timeline:   { bsonType: "array", items: { bsonType: "object" } },
      finished_at:{ bsonType: "date" }
    }
  } },
  validationLevel: "moderate",
  validationAction: "warn"
});

// ============ 4. assessments 掌握度自评 ============
db.createCollection("assessments", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["learner_id", "skill_id", "rating", "created_at"],
    properties: {
      learner_id: { bsonType: "objectId" },
      skill_id:   { bsonType: "objectId" },
      rating:     { bsonType: "int", minimum: 1, maximum: 5 },
      content:    { bsonType: "string" },
      created_at: { bsonType: "date" }
    }
  } },
  validationLevel: "moderate",
  validationAction: "warn"
});

// ============ 索引（对应 A 卷 2.2 第 5 项）============
// 练习记录：按学习者 + 时间倒序（ESR 原则：等值在前、排序在后）
db.practice_records.createIndex({ learner_id: 1, finished_at: -1 }, { name: "idx_learner_time" });
// 练习记录：唯一记录号
db.practice_records.createIndex({ record_no: 1 }, { name: "uniq_record_no", unique: true });
// 自评：按技能 + 时间
db.assessments.createIndex({ skill_id: 1, created_at: -1 }, { name: "idx_skill_time" });
// 技能点：按难度排序 + 领域
db.skills.createIndex({ domain: 1, difficulty: 1 }, { name: "idx_domain_diff" });
// 技能点：标题文本索引
db.skills.createIndex({ title: "text", tags: "text" }, { name: "idx_text", default_language: "none" });
// 学习者：手机号唯一
db.learners.createIndex({ phone: 1 }, { name: "uniq_phone", unique: true });

printjson(db.skills.getIndexes().map(i => i.name));
printjson(db.practice_records.getIndexes().map(i => i.name));
