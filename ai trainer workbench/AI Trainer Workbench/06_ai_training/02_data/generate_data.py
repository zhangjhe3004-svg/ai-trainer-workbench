# -*- coding: utf-8 -*-
"""造数脚本：技能点、学习者、练习记录、自评。

用法：
    python generate_data.py [--skills 60 --learners 200 --records 800 --assess 400]

要点（对应 A 卷 2.2 第 2 项：文档含数组、嵌套文档）：
- 技能点含数组（tags/category_path/prerequisites）与嵌套文档（specs）。
- 练习记录含明细数组（skills[]）与嵌套文档（timeline）。
- 时间在一年内均匀分布，约 20% 练习集中在头部活跃学习者（幂律长尾）。
- 写入用无序批量分块，避免文档全驻内存。
"""
import argparse
import random
import time
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from pymongo import MongoClient, InsertOne

URI = "mongodb://127.0.0.1:27017"
CLIENT = MongoClient(URI)
DB = CLIENT["learning"]

DOMAINS = [
    ("编程", "Python", ["入门", "语法", "必考"]),
    ("编程", "Java", ["入门", "面向对象"]),
    ("编程", "数据结构", ["进阶", "算法"]),
    ("外语", "英语", ["四级", "词汇"]),
    ("设计", "UI", ["原型", "工具"]),
]

# 技能点规格模板（异构，体现嵌套文档）
SPEC_TEMPLATES = [
    {"语言": "Python 3", "前置": "无", "预计时长": "2h"},
    {"语言": "Java 17", "前置": "基础语法", "预计时长": "3h"},
    {"难度级别": "中级", "推荐教材": "《算法导论》"},
    {"语种": "英语", "等级": "CET-4", "词汇量": 4500},
    {"工具": "Figma", "输出": "低保真原型"},
]


def gen_skills(n):
    docs = []
    for i in range(n):
        dom, sub, tags = random.choice(DOMAINS)
        # 前置依赖：前面已生成的同领域技能（体现依赖图）
        pre = []
        if i > 0 and random.random() < 0.6:
            pre = [docs[random.randint(0, i - 1)]["title"]]
        docs.append({
            "_id": ObjectId(),
            "code": "SK-%06d" % i,
            "title": "%s知识点%02d" % (sub, i),
            "domain": dom,
            "sub_domain": sub,
            "category_path": [dom, sub],
            "difficulty": round(random.uniform(0.1, 0.95), 2),
            "tags": random.sample(tags, min(2, len(tags))),
            "specs": random.choice(SPEC_TEMPLATES),
            "prerequisites": pre,
            "status": "active",
            "created_at": datetime.now(timezone.utc) - timedelta(days=random.randint(0, 365)),
        })
    return docs


def gen_learners(n):
    docs = []
    for i in range(n):
        docs.append({
            "_id": ObjectId(),
            "nickname": "学习者%04d" % i,
            "phone": "139%08d" % i,
            "level": random.choice(["beginner", "beginner", "silver", "gold"]),
            "years": random.randint(0, 5),
            "tags": random.sample(["在职", "学生", "自学", "转行"], 2),
            "profile": {"city": random.choice(["广州", "深圳", "杭州", "北京"]),
                        "age": random.randint(18, 45)},
            "created_at": datetime.now(timezone.utc) - timedelta(days=random.randint(1, 900)),
        })
    return docs


def gen_records(n, skills, learners, seq_start):
    """练习记录：明细 1~5 个技能，含 timeline 嵌套数组。"""
    active = learners[:20]  # 前 20 个为活跃学习者
    docs = []
    base = datetime(2025, 11, 1, tzinfo=timezone.utc)
    for i in range(n):
        seq = seq_start + i
        k = random.randint(1, 5)
        chosen = random.sample(skills, k)
        skill_items = []
        correct_cnt = 0
        for sk in chosen:
            correct = random.random() < 0.75
            if correct:
                correct_cnt += 1
            skill_items.append({
                "skill_id": sk["_id"], "correct": correct,
                "difficulty": sk["difficulty"], "attempt_no": random.randint(1, 3),
                "domain": sk["domain"], "sub_domain": sk["sub_domain"],
            })
        u = random.choice(active) if random.random() < 0.2 else random.choice(learners)
        finished = base + timedelta(minutes=random.randint(0, 365 * 24 * 60))
        docs.append({
            "_id": ObjectId(),
            "record_no": "PR%06d" % seq,
            "learner_id": u["_id"],
            "skills": skill_items,
            "score": round(correct_cnt / k, 2),
            "status": "completed",
            "timeline": [
                {"status": "started", "at": finished - timedelta(minutes=random.randint(5, 60))},
                {"status": "completed", "at": finished},
            ],
            "finished_at": finished,
        })
    return docs


def gen_assessments(n, records, skills, learners):
    """自评：关联练习记录，评分 1~5 近似正态。"""
    docs = []
    for i in range(n):
        rec = random.choice(records)
        it = random.choice(rec["skills"])
        rating = max(1, min(5, int(round(random.gauss(4, 0.9)))))
        docs.append({
            "learner_id": rec["learner_id"],
            "skill_id": it["skill_id"],
            "rating": rating,
            "content": random.choice(["掌握良好", "还需巩固", "理解透彻", "有点吃力"]),
            "created_at": rec["finished_at"] + timedelta(hours=random.randint(1, 240)),
        })
    return docs


def bulk_write(col, docs, size=1000):
    total = 0
    for i in range(0, len(docs), size):
        r = col.bulk_write([InsertOne(d) for d in docs[i:i + size]], ordered=False)
        total += r.inserted_count
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skills", type=int, default=60)
    ap.add_argument("--learners", type=int, default=200)
    ap.add_argument("--records", type=int, default=800)
    ap.add_argument("--assess", type=int, default=400)
    args = ap.parse_args()

    t0 = time.time()
    sk = gen_skills(args.skills)
    bulk_write(DB.skills, sk)
    print("[1/4] skills %6d 条，耗时 %5.1f s" % (len(sk), time.time() - t0))

    t1 = time.time()
    lr = gen_learners(args.learners)
    bulk_write(DB.learners, lr)
    print("[2/4] learners %6d 条，耗时 %5.1f s" % (len(lr), time.time() - t1))

    t2 = time.time()
    # 分块生成练习记录
    rec_pool = []
    total = 0
    CHUNK = 20000
    for start in range(0, args.records, CHUNK):
        cnt = min(CHUNK, args.records - start)
        chunk = gen_records(cnt, sk, lr, start)
        total += bulk_write(DB.practice_records, chunk)
        rec_pool.extend(random.sample(chunk, min(200, len(chunk))))
    print("[3/4] practice_records %6d 条，耗时 %5.1f s" % (total, time.time() - t2))

    t3 = time.time()
    rv = gen_assessments(args.assess, rec_pool, sk, lr)
    bulk_write(DB.assessments, rv)
    print("[4/4] assessments %6d 条，耗时 %5.1f s" % (len(rv), time.time() - t3))

    print("合计 %d 条，总耗时 %.1f s"
          % (len(sk) + len(lr) + total + len(rv), time.time() - t0))


if __name__ == "__main__":
    main()
