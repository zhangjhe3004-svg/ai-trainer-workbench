// 技能图谱学习推荐系统 —— 访问控制（对应 A 卷 2.2 第 6 项）
// 启用 authorization 后，用 localhost 例外机制创建管理员，再按最小权限创建业务账号

// 1. 系统管理员（首次无用户时用 localhost 例外）
db = db.getSiblingDB("admin");
db.createUser({
  user: "learnAdmin",
  pwd: "Admin@2026",
  roles: [
    { role: "userAdminAnyDatabase", db: "admin" },
    { role: "readWriteAnyDatabase", db: "admin" }
  ]
});

// 2. 业务账号（只读写 learning）
db = db.getSiblingDB("learning");
db.createUser({ user: "learnApp", pwd: "App@2026", roles: [{ role: "readWrite", db: "learning" }] });

// 3. 训练库 ETL 账号（读 learning + 读写 learning_ai）
db.createUser({ user: "etlApp", pwd: "Etl@2026", roles: [
  { role: "read", db: "learning" },
  { role: "readWrite", db: "learning_ai" }
]});

// 4. 报表账号（只读）
db.createUser({ user: "learnReport", pwd: "Report@2026", roles: [{ role: "read", db: "learning" }] });

printjson(db.getUsers());
