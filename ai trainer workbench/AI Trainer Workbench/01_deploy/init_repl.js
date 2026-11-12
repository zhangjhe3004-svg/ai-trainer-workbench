// 初始化三节点副本集，27017 优先级最高
rs.initiate({
  _id: "rs0",
  members: [
    { _id: 0, host: "127.0.0.1:27017", priority: 2 },
    { _id: 1, host: "127.0.0.1:27018", priority: 1 },
    { _id: 2, host: "127.0.0.1:27019", priority: 1 }
  ]
});

sleep(5000);
printjson(rs.status().members.map(m => ({ name: m.name, state: m.stateStr, health: m.health })));
