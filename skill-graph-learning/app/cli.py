# -*- coding: utf-8 -*-
"""命令行交互菜单：AI 训练师工作台。

对模型 / 技能 / 数据集 / 训练运行做增删改查与参数调配。
运行：python cli.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import init_indexes, models, skills, datasets, training_runs
from services import model, dataset, training


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


def menu_models():
    while True:
        print("\n" + "=" * 50)
        print("【模型管理】")
        print("  1. 查看全部模型")
        print("  2. 注册模型")
        print("  3. 删除模型")
        print("  0. 返回上级")
        c = input("请选择：").strip()
        if c == "1":
            rows = list(models.find({}).sort("created_at", -1))
            pprint("模型列表", rows, ["name", "base_model", "model_type", "status"])
        elif c == "2":
            name = input("  模型名称：").strip()
            base = input("  基座模型(如 Qwen2.5-7B)：").strip()
            mtype = input("  类型(llm/embedding/vision/multimodal，默认 llm)：").strip() or "llm"
            desc = input("  描述(可空)：").strip()
            try:
                model.create_model(name, base, mtype, desc)
                print("  ✅ 注册成功")
            except ValueError as e:
                print("  ❌ " + str(e))
        elif c == "3":
            name = input("  要删除的模型名称：").strip()
            d = models.find_one({"name": name})
            if not d:
                print("  ❌ 模型不存在")
                continue
            if input(f"  确认删除「{name}」？将级联清理参数/训练/评测(y/n)：").strip().lower() == "y":
                model.delete_model(str(d["_id"]))
                print("  ✅ 删除成功")
        elif c == "0":
            break


def menu_skills():
    while True:
        print("\n" + "=" * 50)
        print("【技能扩展】")
        print("  1. 查看全部技能")
        print("  2. 新增技能")
        print("  3. 给模型挂载技能")
        print("  4. 删除技能")
        print("  0. 返回上级")
        c = input("请选择：").strip()
        if c == "1":
            rows = list(skills.find({}).sort("created_at", -1))
            items = [{"name": r["name"], "category": r.get("category", ""),
                      "model_id": str(r["model_id"]) if r.get("model_id") else "-",
                      "enabled": r.get("enabled", True)} for r in rows]
            pprint("技能列表", items, ["name", "category", "model_id", "enabled"])
        elif c == "2":
            name = input("  技能名称：").strip()
            cat = input("  类别：").strip()
            desc = input("  描述(可空)：").strip()
            try:
                model.create_skill(name, cat, desc)
                print("  ✅ 新增成功")
            except ValueError as e:
                print("  ❌ " + str(e))
        elif c == "3":
            mname = input("  模型名称：").strip()
            m = models.find_one({"name": mname})
            if not m:
                print("  ❌ 模型不存在")
                continue
            sname = input("  技能名称：").strip()
            s = skills.find_one({"name": sname})
            if not s:
                print("  ❌ 技能不存在")
                continue
            model.mount_skill(str(m["_id"]), str(s["_id"]))
            print("  ✅ 挂载成功")
        elif c == "4":
            name = input("  要删除的技能名称：").strip()
            s = skills.find_one({"name": name})
            if not s:
                print("  ❌ 技能不存在")
                continue
            if input(f"  确认删除「{name}」？(y/n)：").strip().lower() == "y":
                model.delete_skill(str(s["_id"]))
                print("  ✅ 删除成功")
        elif c == "0":
            break


def menu_runs():
    while True:
        print("\n" + "=" * 50)
        print("【数据训练】")
        print("  1. 查看训练运行")
        print("  2. 创建训练运行")
        print("  3. 执行训练")
        print("  0. 返回上级")
        c = input("请选择：").strip()
        if c == "1":
            rows = list(training_runs.find({}).sort("created_at", -1))
            items = [{"name": r["name"], "task_type": r.get("task_type", ""),
                      "status": r.get("status", ""), "progress": r.get("progress", 0)} for r in rows]
            pprint("训练运行列表", items, ["name", "task_type", "status", "progress"])
        elif c == "2":
            name = input("  训练名称：").strip()
            m = models.find_one({})
            if not m:
                print("  ❌ 请先注册模型")
                continue
            ds = datasets.find_one({})
            if not ds:
                print("  ❌ 请先导入数据集")
                continue
            try:
                rid = training.create_run(name, str(m["_id"]), str(ds["_id"]),
                                          task_type="fine_tuning", mode="simulate")
                print("  ✅ 创建成功，ID:", rid)
            except ValueError as e:
                print("  ❌ " + str(e))
        elif c == "3":
            name = input("  要执行的训练名称：").strip()
            r = training_runs.find_one({"name": name})
            if not r:
                print("  ❌ 训练运行不存在")
                continue
            print("  执行中...")
            try:
                result = training.execute_run(str(r["_id"]))
                print("  ✅ 完成，指标:", result.get("metrics", {}))
            except Exception as e:
                print("  ❌ " + str(e))
        elif c == "0":
            break


def main():
    init_indexes()
    while True:
        print("\n" + "=" * 50)
        print("  AI 训练师工作台 · 命令行管理")
        print("=" * 50)
        print("  1. 模型管理")
        print("  2. 技能扩展")
        print("  3. 数据训练")
        print("  0. 退出")
        c = input("请选择：").strip()
        if c == "1":
            menu_models()
        elif c == "2":
            menu_skills()
        elif c == "3":
            menu_runs()
        elif c == "0":
            print("再见！")
            break


if __name__ == "__main__":
    main()
