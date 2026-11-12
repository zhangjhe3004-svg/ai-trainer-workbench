// 在 admin 库创建系统管理员（首次无用户时可用 localhost 例外）
use admin
db.createUser({
  user: "shopAdmin",
  pwd: "Admin@2026",
  roles: [
    { role: "userAdminAnyDatabase", db: "admin" },
    { role: "clusterAdmin", db: "admin" },
    { role: "readWriteAnyDatabase", db: "admin" }
  ]
});

// 业务账号：只读写 shop；报表账号：只读
use shop
db.createUser({ user: "shopApp", pwd: "App@2026", roles: [{ role: "readWrite", db: "shop" }] });
db.createUser({ user: "shopReport", pwd: "Report@2026", roles: [{ role: "read", db: "shop" }] });

printjson(db.getUsers());
