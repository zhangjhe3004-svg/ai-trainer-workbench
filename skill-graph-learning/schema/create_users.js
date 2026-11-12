// AI 训练师工作台 —— 访问控制（对应 A 卷 2.2 第 6 项）
// 启用 authorization 后，用 localhost 例外机制创建管理员，再按最小权限创建业务账号

// 1. 系统管理员（首次无用户时用 localhost 例外）
db = db.getSiblingDB("admin");
db.createUser({
  user: "trainerAdmin",
  pwd: "Admin@2026",
  roles: [
    { role: "userAdminAnyDatabase", db: "admin" },
    { role: "readWriteAnyDatabase", db: "admin" }
  ]
});

// 2. 业务账号（只读写 trainer）
db = db.getSiblingDB("trainer");
db.createUser({ user: "trainerApp", pwd: "App@2026", roles: [{ role: "readWrite", db: "trainer" }] });

// 3. 训练库 ETL 账号（读 trainer + 读写 trainer_ai）
db.createUser({ user: "etlApp", pwd: "Etl@2026", roles: [
  { role: "read", db: "trainer" },
  { role: "readWrite", db: "trainer_ai" }
]});

// 4. 报表账号（只读）
db.createUser({ user: "trainerReport", pwd: "Report@2026", roles: [{ role: "read", db: "trainer" }] });

printjson(db.getUsers());
