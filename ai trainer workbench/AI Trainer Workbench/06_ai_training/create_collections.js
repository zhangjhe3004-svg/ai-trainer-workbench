// 技能图谱学习推荐 —— AI 训练库建库、校验器与索引
// db: learning_ai（运行时用连接串指定库：mongosh "mongodb://127.0.0.1:27017/learning_ai" 本文件）
// 对应四集合：samples / features / graph_edges / runs

// ================= 1. samples（训练样本主表）=================
// 一行一条「学习者 × 技能点」练习交互样本
db.createCollection("samples", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["learner_id", "skill_id", "label", "feedback_type", "created_at"],
    properties: {
      learner_id:     { bsonType: "objectId" },
      skill_id:       { bsonType: "objectId" },
      label:          { bsonType: "int", enum: [0, 1] },       // 1=正样本(掌握/完成) 0=负样本(未掌握)
      feedback_type:  { enum: ["practice", "assess", "review"] },
      mastery:        { bsonType: "double", minimum: 0, maximum: 5 },  // 掌握度自评(显式反馈)
      correct:        { bsonType: "bool" },                     // 本次练习对错(隐式反馈)
      difficulty:     { bsonType: "double", minimum: 0, maximum: 1 },  // 技能难度
      ctx: {
        bsonType: "object",
        properties: {
          domain:     { bsonType: "string" },   // 领域，如 "编程"
          sub_domain: { bsonType: "string" },   // 子领域，如 "Python"
          attempt_no: { bsonType: "int" }       // 第几次练习该技能
        }
      },
      created_at:     { bsonType: "date" }
    }
  } },
  validationLevel: "moderate",
  validationAction: "warn"
});

// ================= 2. features（技能/学习者特征与画像）=================
db.createCollection("features", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["entity_type", "entity_id"],
    properties: {
      entity_type: { enum: ["skill", "learner"] },
      entity_id:   { bsonType: "objectId" },
      // 技能侧特征
      difficulty:  { bsonType: "double" },
      // 学习者侧画像
      level:       { bsonType: "string" },
      years:       { bsonType: "int" },
      tags:        { bsonType: "array", items: { bsonType: "string" } },
      // embedding 向量（数组存储，供向量检索/近邻）
      dense:       { bsonType: "array", items: { bsonType: "double" } },
      // 稀疏特征（one-hot）
      sparse:      { bsonType: "object" },
      updated_at:  { bsonType: "date" }
    }
  } },
  validationLevel: "moderate",
  validationAction: "warn"
});

// ================= 3. graph_edges（技能依赖图边）=================
db.createCollection("graph_edges", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["from_skill", "to_skill", "rel_type"],
    properties: {
      from_skill: { bsonType: "objectId" },   // 前置技能
      to_skill:   { bsonType: "objectId" },   // 后继技能
      rel_type:   { enum: ["prerequisite", "related"] },
      weight:     { bsonType: "double", minimum: 0, maximum: 1 }  // 依赖强度(可选)
    }
  } },
  validationLevel: "moderate",
  validationAction: "warn"
});

// ================= 4. runs（实验与模型元数据）=================
db.createCollection("runs", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["run_id", "model", "split"],
    properties: {
      run_id:  { bsonType: "string" },
      model:   { bsonType: "string" },        // DKT / DKVMN / LightGCN ...
      split:   { enum: ["train", "valid", "test"] },
      params:  { bsonType: "object" },
      metrics: { bsonType: "object" },        // { auc, accuracy, ndcg }
      status:  { enum: ["running", "done", "failed"] },
      created_at: { bsonType: "date" }
    }
  } },
  validationLevel: "moderate",
  validationAction: "warn"
});

// ================= 索引策略 =================
// samples：去重 + 按用户取序列 + 按技能取样本 + 按标签采样
db.samples.createIndex({ learner_id: 1, skill_id: 1 },
                       { name: "uniq_learner_skill", unique: true });
db.samples.createIndex({ learner_id: 1, created_at: -1 },
                       { name: "idx_learner_time" });
db.samples.createIndex({ skill_id: 1, created_at: -1 },
                       { name: "idx_skill_time" });
db.samples.createIndex({ label: 1, created_at: 1 },
                       { name: "idx_label_time" });

// features：定位实体特征
db.features.createIndex({ entity_type: 1, entity_id: 1 },
                        { name: "uniq_entity", unique: true });

// graph_edges：双向遍历技能依赖图
db.graph_edges.createIndex({ from_skill: 1, rel_type: 1 },
                           { name: "idx_from_rel" });
db.graph_edges.createIndex({ to_skill: 1, rel_type: 1 },
                           { name: "idx_to_rel" });
db.graph_edges.createIndex({ from_skill: 1, to_skill: 1 },
                           { name: "uniq_edge", unique: true });

// runs：按实验 + 数据集切分查询
db.runs.createIndex({ run_id: 1, split: 1 }, { name: "idx_run_split" });

printjson(db.samples.getIndexes().map(i => i.name));
printjson(db.graph_edges.getIndexes().map(i => i.name));
