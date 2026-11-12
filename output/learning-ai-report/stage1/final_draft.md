# 基于 MongoDB 的技能图谱学习推荐系统设计与实现报告

> 华南农业大学珠江学院《高级数据库》课程 · NoSQL 期末大作业

**二级学院：** ____________________
**专业班级：** ____________________
**学　　号：** ____________________
**姓　　名：** ____________________
**2026 年 11 月**

---

## 1　总体设计与选型分析

### 1.1　业务场景与数据特征

本系统面向个人学习者的「技能图谱学习推荐」场景：学习者围绕一个个「技能点（Skill）」展开练习与自评，系统基于其练习行为序列与技能之间的依赖关系，为其推荐下一步最该学习的技能，实现个性化学习路径规划。

系统包含四类核心实体，构成完整的「学习者—技能点—练习—评价」业务闭环：

| 实体 | 集合 | 职责 | 关键特征 |
|---|---|---|---|
| 技能点 | skills | 待掌握的能力单元 | 有难度、前置依赖，多规格异构 |
| 学习者 | learners | 参与学习的用户 | 等级、年限、标签画像 |
| 练习记录 | practice_records | 一次练习的完整过程 | 明细覆盖多个技能，状态流转 |
| 掌握度自评 | assessments | 对技能掌握程度的主观评分 | 1~5 分 + 反思文本 |

业务数据呈现三个显著特征：其一，**结构异构**——不同领域的技能点规格不同（如编程类含「语言/框架/难度」，语言类含「语种/等级/场景」），与典型 NoSQL 场景高度契合；其二，**强时序性**——学习者对同一技能点会随时间反复练习，构成可建模的知识状态演化序列；其三，**幂律长尾**——少量热门技能被海量练习，大量冷门技能无人问津，是推荐与冷启动研究的典型分布。

### 1.2　选型分析

本项目选择 MongoDB 作为唯一数据存储，基于以下四点考量：

1. **结构异构需要灵活 Schema**：技能点的规格字段随领域而异，关系型数据库需为每种技能建立宽表或 EAV 模型，维护成本高；MongoDB 的文档模型可让每个技能点携带符合自身领域规格的内嵌对象。
2. **一次练习覆盖多技能需内嵌明细**：一次练习记录（practice_records）对应多个技能点明细（1~N 条），将明细内嵌为数组可让「按学习者取完整练习序列」只需一次查询，无需多表 JOIN。
3. **读多写少、查询模式稳定**：学习推荐场景以「按学习者取序列」「按技能取练习」两类查询为主，写入相对低频，适合通过复合索引 + 哈希分片优化读路径。
4. **天然适配 AI 训练数据抽取**：练习记录本身就是「学习者 × 技能点 × 反馈」三元组，是知识追踪与推荐模型的直接输入，无需二次重构即可产出训练样本。

### 1.3　系统架构设计

系统采用「业务库 + 训练库」双层架构，业务库承载在线学习服务，训练库承载离线 AI 训练数据，两者通过 ETL 层解耦：

- **业务库（learning）**：skills、learners、practice_records、assessments 四集合，服务在线学习与查询。
- **训练库（learning_ai）**：samples、features、graph_edges、runs 四集合，服务离线训练。
- **ETL 层**：从业务库聚合交互对、负采样、构建技能依赖边、抽取特征，批量写入训练库。
- **应用层**：PyMongo 服务层 + Flask 接口，命令行演示与接口共用同一套业务逻辑。

### 1.4　数据流设计

在线数据流：学习者发起练习 → 写入 practice_records（含明细与状态）→ 完成后写入 assessments → 系统按技能依赖图推荐下一技能。

离线数据流：practice_records 聚合出「学习者 × 技能点」交互对生成正样本 → 从 learners 未掌握技能中随机负采样生成负样本 → assessments 的 rating 作为显式反馈、练习对错作为隐式反馈 → skills 的 prerequisites 构建 graph_edges → 画像与难度抽取为 features → 训练样本供知识追踪与路径推荐模型消费。

---

## 2　数据模型设计

### 2.1　概念模型

系统核心关系可概括为：**学习者（learner）通过练习（practice）作用于技能点（skill），并产生评价（assessment）；技能点之间存在前置依赖（prerequisite）构成有向图。**

关系基数：
- 学习者 : 练习记录 = 1 : N
- 练习记录 : 技能点 = 1 : N（一次练习覆盖多个技能）
- 学习者 : 技能点 = M : N（通过练习记录间接关联）
- 技能点 : 技能点 = M : N（前置依赖）

### 2.2　集合结构总览

业务库 learning 四个集合，训练库 learning_ai 四个集合：

| 库 | 集合 | 说明 | 关键索引 |
|---|---|---|---|
| learning | skills | 技能点 | category_path、difficulty |
| learning | learners | 学习者 | phone 唯一 |
| learning | practice_records | 练习记录 | learner_id + finished_at |
| learning | assessments | 掌握度自评 | skill_id + created_at |
| learning_ai | samples | 训练样本 | learner_id + skill_id 唯一 |
| learning_ai | features | 特征与画像 | entity_type + entity_id 唯一 |
| learning_ai | graph_edges | 技能依赖边 | from_skill + to_skill 唯一 |
| learning_ai | runs | 实验与模型元数据 | run_id + split |

### 2.3　核心文档结构

**技能点（skills）** 示例：

```json
{
  "_id": ObjectId(),
  "code": "SK-PY-0001",
  "title": "Python 列表与循环",
  "domain": "编程",
  "sub_domain": "Python",
  "category_path": ["编程", "Python", "基础语法"],
  "difficulty": 0.35,
  "tags": ["入门", "语法", "必考"],
  "specs": { "语言": "Python 3", "前置": "变量与类型", "预计时长": "2h" },
  "prerequisites": [ObjectId("..."), ObjectId("...")],
  "mastery_stats": { "avg": 3.8, "count": 1024 },
  "status": "active",
  "created_at": ISODate()
}
```

**练习记录（practice_records）** 示例：

```json
{
  "_id": ObjectId(),
  "record_no": "PR20261112000001",
  "learner_id": ObjectId(),
  "skills": [
    { "skill_id": ObjectId(), "correct": true, "difficulty": 0.35,
      "attempt_no": 2, "domain": "编程", "sub_domain": "Python" }
  ],
  "score": 0.86,
  "status": "completed",
  "timeline": [ { "status": "started", "at": ISODate() },
                { "status": "completed", "at": ISODate() } ],
  "finished_at": ISODate()
}
```

**训练样本（samples）** 示例：

```json
{
  "_id": ObjectId(),
  "learner_id": ObjectId(),
  "skill_id": ObjectId(),
  "label": 1,
  "feedback_type": "practice",
  "correct": true,
  "mastery": 4.0,
  "difficulty": 0.35,
  "ctx": { "domain": "编程", "sub_domain": "Python", "attempt_no": 2 },
  "created_at": ISODate()
}
```

### 2.4　内嵌与引用的取舍

本设计遵循与典型电商系统一致的取舍原则，但以「练习记录」为聚合根：

- **内嵌**：练习记录的技能明细（skills 数组）内嵌于记录文档，使「按学习者取练习序列」一次查询即可获取全部交互，避免多次关联。
- **引用**：技能点之间的前置依赖（prerequisites）以 `ObjectId` 数组引用，避免技能点文档因依赖关系而无限膨胀；学习者画像与练习记录分离，防止活跃学习者的高频练习拖垮其画像文档。
- **训练库分离**：训练样本（samples）从业务库抽取后独立存储，避免在线库被离线训练频繁扫读，也便于按训练需求独立分片。

### 2.5　字段命名与类型规范

沿用工程化命名约定：字段统一蛇形小写；时间字段以 `_at` 结尾并使用 BSON Date 类型；引用字段以被引用集合单数名加 `_id` 结尾（learner_id、skill_id）；枚举字段（status、feedback_type、rel_type）在集合校验器中限定取值，越界写入被拦截；难度、评分等连续量用 `double` 存储，掌握度限定 0~5 闭区间。

### 2.6　索引与 TTL 规划

训练库索引规划（详见代码包 06_ai_training/create_collections.js）：

| 集合 | 索引 | 用途 |
|---|---|---|
| samples | { learner_id:1, skill_id:1 } 唯一 | 去重，保证同一交互仅一条样本 |
| samples | { learner_id:1, created_at:-1 } | 按学习者取练习序列 |
| samples | { skill_id:1, created_at:-1 } | 按技能取样本 |
| samples | { label:1, created_at:1 } | 快速抽取正/负样本 |
| features | { entity_type:1, entity_id:1 } 唯一 | 定位实体特征 |
| graph_edges | { from_skill:1, to_skill:1 } 唯一 | 去重 + 图出边遍历 |
| runs | { run_id:1, split:1 } | 实验查询 |

---

## 3　数据操作与业务功能实现

### 3.1　环境部署

- MongoDB 7.0.14 副本集（rs0，端口 27017/27018/27019）
- mongosh 2.2.6
- Python 3.10.11，PyMongo 4.6.3，Flask 3.0.3

三个节点 host 统一写 `127.0.0.1`，避免混用 `localhost` 导致节点无法加入。

### 3.2　数据库与集合创建

业务库 learning 与训练库 learning_ai 的集合均通过 `createCollection` + `$jsonSchema` 校验器创建，`validationLevel` 设为 `moderate`、`validationAction` 设为 `warn`，在拦截明显越界写入的同时保留对存量数据的兼容。训练库建库脚本见 `06_ai_training/create_collections.js`，四个集合的校验器分别限定 label 枚举、feedback_type 枚举、mastery 区间等约束。

### 3.3　数据构造

造数脚本按领域模板生成异构技能点（编程类/语言类/设计类各携带不同规格字段），练习记录从技能池随机抽取 1~8 个技能构成明细，时间在一年区间内均匀分布，状态按真实业务比例分配，约 20% 练习集中在头部活跃学习者，为序列建模与冷启动研究提供样本。写入用无序批量分块写入，避免全部文档驻留内存。

### 3.4　文档增删改查

覆盖七类查询（条件、范围、逻辑、排序分页、正则、数组、嵌套文档）与插入、更新、删除操作，与参考答案电商系统的 CRUD 能力对齐。典型查询如：按 `category_path` 定位技能、按 `tags` 数组多条件匹配、按 `skills` 内嵌数组的 `$elemMatch` 查询练习明细、按学习者对练习记录做游标式分页。

### 3.5　聚合管道统计

训练数据抽取核心依赖聚合管道，典型三条：

1. **交互对聚合**：对 practice_records 做 `$unwind skills`，聚合出「学习者 × 技能点」交互对，作为正样本来源。
2. **技能热度统计**：按技能分组统计练习次数与平均掌握度，识别热门与冷门技能。
3. **知识状态序列构造**：按学习者 + 时间排序，输出学习者的技能掌握演化序列，供知识追踪模型训练。

### 3.6　索引优化与 explain() 对比

以「按学习者取练习序列」为典型案例：无 `{ learner_id:1, created_at:-1 }` 索引时，查询需全集合扫描并在内存排序，数据量增大后排序内存超限直接不可用；建复合索引后，查询计划变为 IXSCAN 且 SORT 阶段消失，扫描文档数从全量降至命中区间，耗时从数百毫秒降至数毫秒，从「不可用」变为「可用」。

### 3.7　访问控制

数据库开启 authorization 后，用 localhost 例外机制创建系统管理员，再由管理员按最小权限创建业务账号：业务应用账号授予 learning / learning_ai 库的 readWrite，ETL 抽取账号授予 learning 的 read 与 learning_ai 的 readWrite，报表账号仅授予 read，管理员账号不用于业务连接。

---

## 4　业务应用实现

### 4.1　业务功能闭环

完整业务闭环覆盖：学习者发起练习 → 系统记录练习明细与状态流转 → 完成后写入掌握度自评 → 基于技能依赖图推荐下一技能 → ETL 抽取训练样本 → 训练模型产出推荐结果。演示程序覆盖检索、练习、自评、路径推荐、样本抽取五个环节。

### 4.2　工程结构

```
06_ai_training/
├── create_collections.js   # 训练库建库、校验器与索引
├── shard_config.js         # 分片集群配置
├── etl_to_training.py      # ETL：正负样本抽取、建边、特征
└── README.md               # 方案说明与执行顺序
```

### 4.3　关键实现

**样本抽取**：从 practice_records 聚合交互对生成正样本（label=1），从 learners 未掌握技能中随机负采样生成负样本（label=0），控制正负比（如 1:4）；assessments 的 rating 作为显式反馈（mastery 字段），练习对错作为隐式反馈（correct 字段）。

**依赖图构建**：遍历 skills 的 prerequisites 字段，生成 `{from_skill, to_skill, rel_type}` 依赖边，为路径推荐模型提供图约束。

**幂等抽取**：samples 以 `{learner_id, skill_id}` 唯一索引保证同一交互仅一条样本，ETL 用 upsert 实现可重复执行。

### 4.4　运行结果

执行 ETL 后，训练库生成四类数据：samples（正负样本）、features（技能难度与学习者画像）、graph_edges（技能依赖边）、runs（实验元数据）。以 demo 脚本执行一次完整闭环，覆盖「练习 → 自评 → 推荐 → 样本抽取」全流程，验证样本去重、依赖边构建与特征落库正确性。

---

## 5　结果分析

### 5.1　功能完成情况

对照作业要求逐项自查：四实体建模、七类查询、聚合管道、索引 explain 对比、访问控制、ETL 抽取、训练库四集合划分、哈希分片均已完成，覆盖参考答案七章结构所要求的全部能力点。

### 5.2　性能分析

索引对读路径的性能提升是量级性的：无索引时「按学习者取练习序列」因排序内存超限不可用，建复合索引后数毫秒返回。写路径成本主要来自多数派确认，关键写入换取一致性是本设计的明确取舍。训练库以 learner_id 哈希分片，使「按学习者聚合序列」本地化，避免跨分片 join。

### 5.3　设计得失

本设计成立的关键有三点：其一，以练习记录为聚合根整体内嵌明细，使读路径只需一次查询；其二，将训练数据从业务库分离，避免离线训练干扰在线服务；其三，以技能依赖图（graph_edges）显式建模前置关系，为路径推荐提供图约束，这是区别于传统推荐系统的核心创新点。

不足之处同样明确：其一，样本负采样依赖全量技能遍历，技能规模增大后需改为流式采样；其二，features 中的 embedding 向量维度受限，高维向量检索需引入向量索引或专用向量库；其三，技能依赖边依赖人工标注，图质量直接影响推荐效果，需建立依赖边置信度评估机制。

---

## 6　遇到的问题及解决办法

实施过程中遇到的问题可分为环境、语义与性能三类：

1. **环境类**：副本集节点 host 混用 localhost 与 127.0.0.1 导致新节点无法加入，解决为统一写法。
2. **语义类**：内嵌数组查询用路径式匹配与 `$elemMatch` 结果不同，路径式匹配允许不同元素分别满足条件，需按业务语义选用；负采样重复生成同一交互，靠 `{learner_id, skill_id}` 唯一索引 + upsert 幂等解决。
3. **性能类**：练习序列查询无索引时排序内存超限，解决为建立 ESR 复合索引（等值字段在前、排序字段在后）。

---

## 7　提交物与复现说明

### 7.1　提交物清单

| 编号 | 提交物 | 说明 |
|---|---|---|
| 01 | 06_ai_training/create_collections.js | 训练库建库、校验器、索引 |
| 02 | 06_ai_training/shard_config.js | 分片集群配置 |
| 03 | 06_ai_training/etl_to_training.py | ETL 样本抽取 |
| 04 | 06_ai_training/README.md | 方案说明与执行顺序 |
| 05 | 本报告 | 设计与实现说明 |

### 7.2　目录结构与执行顺序

执行顺序为：01 部署并初始化副本集 → 02 建集合与索引、建账号 → 03 造数并跑断言 → 04 执行查询、聚合与 explain → 05 运行 ETL 抽取训练样本 → 06 分片配置。

### 7.3　运行环境

- MongoDB 7.0.14（副本集 rs0，端口 27017/27018/27019）
- mongosh 2.2.6
- Python 3.10.11，PyMongo 4.6.3，Flask 3.0.3

### 7.4　复现注意事项

1. 三个节点 host 必须写法一致，混用 localhost 与 127.0.0.1 会导致新节点无法加入。
2. keyFile 权限必须为 400，权限过宽时 mongod 会拒绝启动。
3. 造数建议先建索引再灌数据，可省去索引重建时间。
4. 训练库 samples 的 `{learner_id, skill_id}` 唯一索引是负采样幂等的关键，删除后会重复生成样本。
5. 本报告中的运行输出为示例文本，实际提交时应替换为本人环境的真实输出或截图。
