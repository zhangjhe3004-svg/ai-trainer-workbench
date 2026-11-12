# -*- coding: utf-8 -*-
"""技能图谱学习推荐系统 —— 完整运行演示。

单文件演示：建库建集合 → 造数据 → 练习 → 自评 → 路径推荐 → ETL 抽取训练样本 → 查询验证。
不依赖副本集，连接本机独立 mongod（127.0.0.1:27017）。

运行：python demo_run.py
"""
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient, ASCENDING, DESCENDING

client = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=5000)
# 业务库 + 训练库
biz = client["learning"]
ai = client["learning_ai"]


def line(t):
    print("\n" + "=" * 60)
    print(t)
    print("=" * 60)


def step1_init():
    """建集合 + 索引。"""
    line("【步骤1】建库、建集合与索引")
    for c in ["skills", "learners", "practice_records", "assessments"]:
        biz[c].drop()
    for c in ["samples", "features", "graph_edges", "runs"]:
        ai[c].drop()

    # 索引（对应报告的 2.6 节）
    biz.practice_records.create_index([("learner_id", 1), ("finished_at", -1)], name="idx_learner_time")
    biz.assessments.create_index([("skill_id", 1), ("created_at", -1)], name="idx_skill_time")
    ai.samples.create_index([("learner_id", 1), ("skill_id", 1)], name="uniq_learner_skill", unique=True)
    ai.samples.create_index([("learner_id", 1), ("created_at", -1)], name="idx_learner_time")
    ai.samples.create_index([("label", 1), ("created_at", 1)], name="idx_label_time")
    ai.graph_edges.create_index([("from_skill", 1), ("to_skill", 1)], name="uniq_edge", unique=True)
    print("  业务库 practice_records 索引:", [n for n in biz.practice_records.index_information() if n != "_id_"])
    print("  训练库 samples 索引:", [n for n in ai.samples.index_information() if n != "_id_"])


def step2_seed():
    """造数据：技能点（带依赖）+ 学习者 + 练习记录 + 自评。"""
    line("【步骤2】造数据（技能图谱 + 学习者 + 练习 + 自评）")
    # 技能点：Python 学习路径，含前置依赖
    skills = [
        ("变量与类型", "基础", 0.1, []),
        ("列表与循环", "基础", 0.2, ["变量与类型"]),
        ("函数与模块", "基础", 0.35, ["列表与循环"]),
        ("面向对象", "进阶", 0.6, ["函数与模块"]),
        ("数据分析", "进阶", 0.75, ["面向对象", "列表与循环"]),
        ("机器学习", "高阶", 0.9, ["数据分析"]),
    ]
    skill_ids = {}
    for code, title, domain, diff, pres in [
        ("S001", "变量与类型", "基础", 0.1, []),
        ("S002", "列表与循环", "基础", 0.2, ["变量与类型"]),
        ("S003", "函数与模块", "基础", 0.35, ["列表与循环"]),
        ("S004", "面向对象", "进阶", 0.6, ["函数与模块"]),
        ("S005", "数据分析", "进阶", 0.75, ["面向对象", "列表与循环"]),
        ("S006", "机器学习", "高阶", 0.9, ["数据分析"]),
    ]:
        sid = biz.skills.insert_one({
            "code": code, "title": title, "domain": "编程", "sub_domain": "Python",
            "difficulty": diff, "prerequisites": pres, "created_at": datetime.now(timezone.utc),
        }).inserted_id
        skill_ids[code] = sid
    print("  技能点:", [(s["code"], s["title"]) for s in biz.skills.find({}, {"code": 1, "title": 1})])

    # 学习者
    learners = [
        ("用户001", "beginner"), ("用户002", "beginner"), ("用户003", "gold"),
    ]
    learner_ids = []
    for name, level in learners:
        lid = biz.learners.insert_one({"nickname": name, "level": level, "created_at": datetime.now(timezone.utc)}).inserted_id
        learner_ids.append((name, level, lid))
    print("  学习者:", [(n, lv) for n, lv, _ in learner_ids])

    # 练习记录：用户001 按路径顺序练习前4个技能，用户002 练前2个，用户003 练1个
    def practice(learner, skill_codes, correct_ratio=0.8):
        rec_skills = []
        for i, sc in enumerate(skill_codes):
            correct = (i % 5) < 4  # 80% 正确
            rec_skills.append({
                "skill_id": skill_ids[sc], "correct": correct,
                "difficulty": biz.skills.find_one({"_id": skill_ids[sc]})["difficulty"],
                "attempt_no": 1, "domain": "编程", "sub_domain": "Python",
            })
        biz.practice_records.insert_one({
            "record_no": "PR" + datetime.now().strftime("%Y%m%d%H%M%S") + str(len(rec_skills)),
            "learner_id": learner, "skills": rec_skills, "status": "completed",
            "finished_at": datetime.now(timezone.utc),
        })

    for name, lv, lid in learner_ids:
        if name == "用户001":
            practice(lid, ["S001", "S002", "S003", "S004"])
        elif name == "用户002":
            practice(lid, ["S001", "S002"])
        else:
            practice(lid, ["S001"])

    # 自评：用户001 对自己掌握的技能打分
    for sc, score in [("S001", 5), ("S002", 4), ("S003", 3)]:
        biz.assessments.insert_one({
            "learner_id": learner_ids[0][2], "skill_id": skill_ids[sc],
            "rating": score, "content": "掌握良好", "created_at": datetime.now(timezone.utc),
        })
    print("  练习记录:", biz.practice_records.count_documents({}), "条；自评:", biz.assessments.count_documents({}), "条")


def step3_recommend():
    """路径推荐：基于技能依赖图，推荐下一步该学的技能。"""
    line("【步骤3】路径推荐（依赖图 + 掌握度）")
    # 取用户001 已练习的技能
    u001 = biz.learners.find_one({"nickname": "用户001"})
    done = set()
    for rec in biz.practice_records.find({"learner_id": u001["_id"]}):
        for s in rec["skills"]:
            done.add(biz.skills.find_one({"_id": s["skill_id"]})["code"])
    print("  用户001 已掌握:", sorted(done))

    # 推荐：所有前置已满足、且自己未学的技能
    all_skills = list(biz.skills.find({}))
    code_to_title = {s["code"]: s["title"] for s in all_skills}
    done_titles = {code_to_title[c] for c in done}
    recommend = []
    for s in all_skills:
        if s["code"] in done:
            continue
        # 前置技能是否都已掌握（按 title 匹配）
        pre_ok = all(p in done_titles for p in s["prerequisites"]) if s["prerequisites"] else True
        if pre_ok:
            recommend.append((s["code"], s["title"], s["difficulty"]))
    print("  推荐下一步学习（前置已满足）:")
    for code, title, diff in sorted(recommend, key=lambda x: x[2]):
        print(f"    → {title}（{code}，难度 {diff}）")


def step4_etl():
    """ETL：抽取训练样本（正样本 + 负采样 + 依赖边 + 特征）。"""
    line("【步骤4】ETL 抽取训练样本")
    # 正样本：练习记录展开成 (learner, skill)
    pos = 0
    for rec in biz.practice_records.find({}):
        for s in rec["skills"]:
            ai.samples.replace_one(
                {"learner_id": rec["learner_id"], "skill_id": s["skill_id"]},
                {"learner_id": rec["learner_id"], "skill_id": s["skill_id"],
                 "label": 1, "feedback_type": "practice", "correct": s["correct"],
                 "difficulty": s["difficulty"], "created_at": rec["finished_at"]},
                upsert=True)
            pos += 1

    # 负采样：为每个学习者随机采样未练习技能
    learners = list(biz.learners.find({}))
    skills = list(biz.skills.find({}))
    import random
    random.seed(42)
    neg = 0
    for l in learners:
        done = {s["skill_id"] for s in ai.samples.find({"learner_id": l["_id"], "label": 1}, {"skill_id": 1})}
        cand = [s["_id"] for s in skills if s["_id"] not in done]
        for _ in range(min(2, len(cand))):
            sk = random.choice(cand)
            ai.samples.replace_one(
                {"learner_id": l["_id"], "skill_id": sk},
                {"learner_id": l["_id"], "skill_id": sk, "label": 0,
                 "feedback_type": "review", "created_at": datetime.now(timezone.utc)},
                upsert=True)
            neg += 1
    print(f"  正样本 {pos} 条，负采样（去重后实际落库 {ai.samples.count_documents({'label': 0})} 条）")

    # 依赖边
    edges = 0
    for s in biz.skills.find({}):
        for pre in s.get("prerequisites", []):
            pre_id = biz.skills.find_one({"title": pre})["_id"]
            ai.graph_edges.replace_one(
                {"from_skill": pre_id, "to_skill": s["_id"]},
                {"from_skill": pre_id, "to_skill": s["_id"], "rel_type": "prerequisite", "weight": 1.0},
                upsert=True)
            edges += 1
    print(f"  依赖边 {edges} 条")

    # 特征
    feat = 0
    for s in biz.skills.find({}):
        ai.features.replace_one(
            {"entity_type": "skill", "entity_id": s["_id"]},
            {"entity_type": "skill", "entity_id": s["_id"], "difficulty": s["difficulty"]}, upsert=True)
        feat += 1
    print(f"  特征 {feat} 条")


def step5_verify():
    """查询验证：训练样本、依赖图、知识状态序列。"""
    line("【步骤5】查询验证")
    print("  训练样本（label=1 正样本）:")
    for s in ai.samples.find({"label": 1}).sort("created_at", 1):
        sk = biz.skills.find_one({"_id": s["skill_id"]})
        lr = biz.learners.find_one({"_id": s["learner_id"]})
        print(f"    {lr['nickname']} → {sk['title']}（correct={s['correct']}）")

    print("\n  技能依赖图（前置 → 后继）:")
    for e in ai.graph_edges.find({}):
        a = biz.skills.find_one({"_id": e["from_skill"]})["title"]
        b = biz.skills.find_one({"_id": e["to_skill"]})["title"]
        print(f"    {a} → {b}")

    print("\n  用户001 的知识状态序列（按时间）:")
    u001 = biz.learners.find_one({"nickname": "用户001"})
    for s in ai.samples.find({"learner_id": u001["_id"]}).sort("created_at", 1):
        sk = biz.skills.find_one({"_id": s["skill_id"]})
        tag = "正" if s["label"] == 1 else "负"
        print(f"    {sk['title']} [{tag}样本]")

    # 统计
    total = ai.samples.count_documents({})
    pos = ai.samples.count_documents({"label": 1})
    print(f"\n  汇总：训练样本 {total} 条（正 {pos} / 负 {total - pos}），依赖边 {ai.graph_edges.count_documents({})} 条，特征 {ai.features.count_documents({})} 条")


def main():
    line("技能图谱学习推荐系统 · 运行演示")
    print("连接 MongoDB:", client.server_info()["version"])
    step1_init()
    step2_seed()
    step3_recommend()
    step4_etl()
    step5_verify()
    line("演示完成")


if __name__ == "__main__":
    main()
