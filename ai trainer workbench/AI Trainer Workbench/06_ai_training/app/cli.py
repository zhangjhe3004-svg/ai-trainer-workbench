# -*- coding: utf-8 -*-
"""命令行交互菜单：对技能点 / 学习者 / 练习记录做增删改查。

运行：python cli.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import init_indexes, skills, learners, practice_records
from services import skill, learner, record


def pprint(title, items, fields):
    print("\n  —— " + title + " ——")
    if not items:
        print("  （无数据）")
        return
    for it in items:
        parts = []
        for f in fields:
            parts.append(str(it.get(f, "")))
        print("  " + "  |  ".join(parts))


def menu_skills():
    while True:
        print("\n" + "=" * 50)
        print("【技能点管理】")
        print("  1. 查看全部技能点")
        print("  2. 新增技能点")
        print("  3. 修改技能点")
        print("  4. 删除技能点")
        print("  0. 返回上级")
        c = input("请选择：").strip()
        if c == "1":
            rows = list(skills.find({}).sort("difficulty", 1))
            pprint("技能点列表", rows, ["code", "title", "domain", "difficulty", "prerequisites"])
        elif c == "2":
            title = input("  标题：").strip()
            domain = input("  领域(默认 编程)：").strip() or "编程"
            sub = input("  子领域(默认 Python)：").strip() or "Python"
            diff = input("  难度 0~1(默认 0.5)：").strip() or "0.5"
            pre = input("  前置技能(逗号分隔，可空)：").strip()
            try:
                skill.create_skill(title, domain, sub, float(diff), pre.split(",") if pre else [])
                print("  ✅ 新增成功")
            except ValueError as e:
                print("  ❌ " + str(e))
        elif c == "3":
            title = input("  要修改的技能点标题：").strip()
            d = skills.find_one({"title": title})
            if not d:
                print("  ❌ 技能点不存在")
                continue
            new_diff = input("  新难度(回车跳过)：").strip()
            new_pre = input("  新前置(逗号分隔，回车跳过)：").strip()
            try:
                skill.update_skill(str(d["_id"]),
                                   difficulty=float(new_diff) if new_diff else None,
                                   prerequisites=new_pre.split(",") if new_pre else None)
                print("  ✅ 修改成功")
            except ValueError as e:
                print("  ❌ " + str(e))
        elif c == "4":
            title = input("  要删除的技能点标题：").strip()
            d = skills.find_one({"title": title})
            if not d:
                print("  ❌ 技能点不存在")
                continue
            if input(f"  确认删除「{title}」？(y/n)：").strip().lower() == "y":
                try:
                    skill.delete_skill(str(d["_id"]))
                    print("  ✅ 删除成功")
                except ValueError as e:
                    print("  ❌ " + str(e))
        elif c == "0":
            break


def menu_learners():
    while True:
        print("\n" + "=" * 50)
        print("【学习者管理】")
        print("  1. 查看全部学习者")
        print("  2. 新增学习者")
        print("  3. 修改学习者等级")
        print("  4. 删除学习者")
        print("  0. 返回上级")
        c = input("请选择：").strip()
        if c == "1":
            rows = list(learners.find({}).sort("_id", 1))
            pprint("学习者列表", rows, ["nickname", "level", "years"])
        elif c == "2":
            name = input("  昵称：").strip()
            level = input("  等级(beginner/silver/gold，默认 beginner)：").strip() or "beginner"
            years = input("  学习年限(默认 0)：").strip() or "0"
            try:
                learner.create_learner(name, level, int(years))
                print("  ✅ 新增成功")
            except ValueError as e:
                print("  ❌ " + str(e))
        elif c == "3":
            name = input("  要修改的学习者昵称：").strip()
            d = learners.find_one({"nickname": name})
            if not d:
                print("  ❌ 学习者不存在")
                continue
            level = input("  新等级：").strip()
            try:
                learner.update_learner(str(d["_id"]), level=level or None)
                print("  ✅ 修改成功")
            except ValueError as e:
                print("  ❌ " + str(e))
        elif c == "4":
            name = input("  要删除的学习者昵称：").strip()
            d = learners.find_one({"nickname": name})
            if not d:
                print("  ❌ 学习者不存在")
                continue
            if input(f"  确认删除「{name}」？将级联清理其数据(y/n)：").strip().lower() == "y":
                try:
                    learner.delete_learner(str(d["_id"]))
                    print("  ✅ 删除成功")
                except ValueError as e:
                    print("  ❌ " + str(e))
        elif c == "0":
            break


def menu_records():
    while True:
        print("\n" + "=" * 50)
        print("【练习记录管理】")
        print("  1. 查看全部练习记录")
        print("  2. 录入练习记录")
        print("  3. 删除练习记录")
        print("  4. 新增自评")
        print("  5. 路径推荐")
        print("  0. 返回上级")
        c = input("请选择：").strip()
        if c == "1":
            rows = list(practice_records.find({}).sort("finished_at", -1))
            items = []
            for r in rows:
                lr = learners.find_one({"_id": r["learner_id"]})
                items.append({"record_no": r["record_no"],
                              "nickname": lr["nickname"] if lr else "?",
                              "skill_count": len(r.get("skills", [])),
                              "score": r.get("score", "-")})
            pprint("练习记录列表", items, ["record_no", "nickname", "skill_count", "score"])
        elif c == "2":
            lrs = list(learners.find({}))
            if not lrs:
                print("  ❌ 请先新增学习者")
                continue
            print("  学习者：")
            for i, l in enumerate(lrs):
                print(f"    {i}. {l['nickname']}")
            idx = int(input("  选择学习者序号：").strip())
            lr = lrs[idx]
            print("  技能点：")
            sks = list(skills.find({}).sort("difficulty", 1))
            for i, s in enumerate(sks):
                print(f"    {i}. {s['code']} {s['title']}")
            codes = input("  选择技能(序号逗号分隔，如 0,1)：").strip()
            flags = input("  对错(逗号分隔，1对0错，如 1,0)：").strip()
            sel = [sks[int(x)]["code"] for x in codes.split(",") if x.strip()]
            fl = [bool(int(x)) for x in flags.split(",") if x.strip()]
            try:
                record.create_record(str(lr["_id"]), sel, fl)
                print("  ✅ 录入成功")
            except ValueError as e:
                print("  ❌ " + str(e))
        elif c == "3":
            no = input("  要删除的记录号：").strip()
            d = practice_records.find_one({"record_no": no})
            if not d:
                print("  ❌ 记录不存在")
                continue
            if input("  确认删除？(y/n)：").strip().lower() == "y":
                record.delete_record(str(d["_id"]))
                print("  ✅ 删除成功")
        elif c == "4":
            lrs = list(learners.find({}))
            print("  学习者：")
            for i, l in enumerate(lrs):
                print(f"    {i}. {l['nickname']}")
            idx = int(input("  选择学习者序号：").strip())
            lr = lrs[idx]
            sks = list(skills.find({}))
            print("  技能点：")
            for i, s in enumerate(sks):
                print(f"    {i}. {s['code']} {s['title']}")
            si = int(input("  选择技能序号：").strip())
            rating = input("  评分 1~5：").strip()
            content = input("  反思笔记(可空)：").strip()
            try:
                record.add_assessment(str(lr["_id"]), sks[si]["code"], float(rating), content)
                print("  ✅ 自评成功")
            except ValueError as e:
                print("  ❌ " + str(e))
        elif c == "5":
            lrs = list(learners.find({}))
            print("  学习者：")
            for i, l in enumerate(lrs):
                print(f"    {i}. {l['nickname']}")
            idx = int(input("  选择学习者序号：").strip())
            lr = lrs[idx]
            r = record.recommend(str(lr["_id"]))
            print(f"\n  {r['learner']} 已掌握：{'、'.join(r['mastered']) if r['mastered'] else '（无）'}")
            print("  推荐下一步：")
            for x in r["recommend"]:
                print(f"    → {x['title']}（难度 {x['difficulty']}）")
        elif c == "0":
            break


def main():
    init_indexes()
    while True:
        print("\n" + "=" * 50)
        print("  技能图谱学习推荐系统 · 命令行管理")
        print("=" * 50)
        print("  1. 技能点管理")
        print("  2. 学习者管理")
        print("  3. 练习记录管理")
        print("  0. 退出")
        c = input("请选择：").strip()
        if c == "1":
            menu_skills()
        elif c == "2":
            menu_learners()
        elif c == "3":
            menu_records()
        elif c == "0":
            print("再见！")
            break


if __name__ == "__main__":
    main()
