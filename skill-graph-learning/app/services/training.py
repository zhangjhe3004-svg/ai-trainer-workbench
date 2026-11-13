# -*- coding: utf-8 -*-
"""数据训练服务：配置参数 → 发起训练 → 执行训练 → 产出指标。

AI 训练师通过本模块「用数据训练模型」：
1. create_run：基于某模型 + 某数据集 + 参数配置，创建一次训练运行；
2. execute_run：执行训练（支持两种模式）：
   - 模拟训练（默认）：不真跑模型，模拟训练步骤、loss 下降、产出指标，可演示、可扩展；
   - 真实训练（预留）：调用本地训练框架（transformers / llama-factory 等），预留接口。

"""
import os
import json
import math
import subprocess
import threading
from datetime import datetime, timezone

from bson import ObjectId

from db import training_runs, evaluations, datasets, models, model_params, samples


def _now():
    return datetime.now(timezone.utc)


TASK_TYPES = ["fine_tuning", "lora", "rlhf", "rag", "embedding", "eval"]
STATUSES = ["pending", "running", "completed", "failed"]


# ============ 训练运行 ============
def list_runs(keyword=None, status=None, model_id=None, page=1, size=50):
    cond = {}
    if keyword:
        cond["name"] = {"$regex": keyword, "$options": "i"}
    if status:
        cond["status"] = status
    if model_id:
        cond["model_id"] = ObjectId(model_id)
    total = training_runs.count_documents(cond)
    cur = training_runs.find(cond, {"name": 1, "model_id": 1, "dataset_id": 1,
                                    "task_type": 1, "status": 1, "params": 1,
                                    "progress": 1, "created_at": 1}) \
        .sort("created_at", -1).skip((page - 1) * size).limit(size)
    rows = []
    for d in cur:
        d["_id"] = str(d["_id"])
        d["model_id"] = str(d["model_id"]) if d.get("model_id") else None
        d["dataset_id"] = str(d["dataset_id"]) if d.get("dataset_id") else None
        if d.get("model_id"):
            m = models.find_one({"_id": ObjectId(d["model_id"])}, {"name": 1})
            d["model_name"] = m["name"] if m else None
        if d.get("dataset_id"):
            ds = datasets.find_one({"_id": ObjectId(d["dataset_id"])}, {"name": 1})
            d["dataset_name"] = ds["name"] if ds else None
        rows.append(d)
    return {"total": total, "rows": rows}


def get_run(rid):
    d = training_runs.find_one({"_id": ObjectId(rid)})
    if not d:
        return None
    d["_id"] = str(d["_id"])
    d["model_id"] = str(d["model_id"]) if d.get("model_id") else None
    d["dataset_id"] = str(d["dataset_id"]) if d.get("dataset_id") else None
    return d


def create_run(name, model_id, dataset_id, task_type="fine_tuning",
               params=None, description="", mode="simulate"):
    """创建一次训练运行。

    mode: simulate（模拟训练）/ real（真实调用本地训练框架）
    """
    if not models.find_one({"_id": ObjectId(model_id)}):
        raise ValueError("模型不存在")
    if not datasets.find_one({"_id": ObjectId(dataset_id)}):
        raise ValueError("数据集不存在")
    if task_type not in TASK_TYPES:
        raise ValueError("训练类型不合法：" + task_type)
    # 合并模型参数配置 + 运行覆盖参数
    mp = model_params.find_one({"model_id": ObjectId(model_id)})
    base_params = mp.get("params", {}) if mp else {}
    run_params = dict(base_params)
    run_params.update(params or {})

    rid = training_runs.insert_one({
        "name": name,
        "model_id": ObjectId(model_id),
        "dataset_id": ObjectId(dataset_id),
        "task_type": task_type,
        "params": run_params,
        "mode": mode,
        "description": description or "",
        "status": "pending",
        "progress": 0.0,
        "logs": [],
        "metrics": {},
        "created_at": _now(),
        "updated_at": _now(),
    }).inserted_id
    return str(rid)


def update_run_status(rid, status):
    if status not in STATUSES:
        raise ValueError("状态不合法：" + status)
    r = training_runs.update_one(
        {"_id": ObjectId(rid)},
        {"$set": {"status": status, "updated_at": _now()}})
    if r.matched_count == 0:
        raise ValueError("训练运行不存在")
    return True


def delete_run(rid):
    r = training_runs.delete_one({"_id": ObjectId(rid)})
    if r.deleted_count == 0:
        raise ValueError("训练运行不存在")
    evaluations.delete_many({"run_id": ObjectId(rid)})
    return True


# ============ 训练执行 ============
def execute_run(rid):
    """执行训练运行。

    根据 mode 分发：
    - simulate：模拟训练（默认，可离线演示）
    - real：调用真实本地训练框架（预留接口，需配置 TRAIN_CMD 环境变量）
    """
    run = training_runs.find_one({"_id": ObjectId(rid)})
    if not run:
        raise ValueError("训练运行不存在")
    if run.get("mode") == "real":
        return _execute_real(run)
    return _execute_simulate(run)


def _execute_simulate(run):
    """模拟训练：不真跑模型，模拟训练步骤、loss 下降、产出指标。

    通过 progress / logs / metrics 字段追踪训练过程，可演示、可扩展。
    """
    rid = run["_id"]
    epochs = int(run.get("params", {}).get("epochs", 3))
    lr = float(run.get("params", {}).get("learning_rate", 2e-5))

    # 更新状态为 running
    training_runs.update_one({"_id": rid}, {"$set": {"status": "running", "updated_at": _now()}})

    logs = []
    total_steps = epochs * 10  # 每 epoch 模拟 10 个 step
    for epoch in range(1, epochs + 1):
        for step in range(1, 11):
            global_step = (epoch - 1) * 10 + step
            # 模拟 loss 下降：指数衰减 + 噪声
            loss = 4.0 * math.exp(-0.5 * global_step / total_steps) + 0.05 * (1 - global_step / total_steps)
            loss = round(max(loss, 0.01), 4)
            progress = round(global_step / total_steps, 4)
            log = {"epoch": epoch, "step": global_step,
                   "loss": loss, "lr": lr, "at": _now().isoformat()}
            logs.append(log)
            training_runs.update_one(
                {"_id": rid},
                {"$set": {"progress": progress, "updated_at": _now()},
                 "$push": {"logs": log}})

    # 训练完成，产出指标
    final_loss = logs[-1]["loss"] if logs else 0.0
    metrics = {
        "final_loss": final_loss,
        "accuracy": round(0.75 + 0.2 * (1 - final_loss / 4.0) + 0.02, 4),
        "perplexity": round(1.0 + final_loss * 3.0, 4),
    }
    training_runs.update_one(
        {"_id": rid},
        {"$set": {"status": "completed", "progress": 1.0, "metrics": metrics,
                  "updated_at": _now()}})
    # 同步更新模型状态为 ready
    models.update_one({"_id": run["model_id"]}, {"$set": {"status": "ready", "updated_at": _now()}})
    # 记录评测
    for metric, value in metrics.items():
        evaluations.insert_one({"run_id": rid, "metric": metric, "value": value,
                                "note": "模拟训练产出", "created_at": _now()})
    # 训练完成自动生成模型版本
    try:
        from services import version
        vid = version.create_version_from_run(str(rid), note="模拟训练自动生成")
        training_runs.update_one({"_id": rid}, {"$set": {"version_id": ObjectId(vid)}})
    except Exception:
        pass  # 版本生成失败不阻塞训练
    return {"status": "completed", "metrics": metrics, "steps": len(logs)}


def _execute_real(run):
    """真实训练：调用本地训练框架（预留接口）。

    通过环境变量 TRAIN_CMD 指定训练命令（如 llama-factory / transformers 脚本），
    命令中可用占位符：{model} {source_path} {dataset} {params_json}
    {method} {method_params_json}（由微调策略写入）。
    若未配置 TRAIN_CMD，则报错提示。
    """
    cmd = os.environ.get("TRAIN_CMD", "")
    if not cmd:
        raise RuntimeError(
            "真实训练模式需配置 TRAIN_CMD 环境变量（本地训练框架命令），"
            "或改用 simulate 模式演示。详见 README「真实训练」章节。")

    model_doc = models.find_one({"_id": run["model_id"]}, {"base_model": 1, "source_type": 1, "source_path": 1})
    model_name = model_doc.get("base_model", "")
    source_path = model_doc.get("source_path", "") or model_name
    dataset_name = datasets.find_one({"_id": run["dataset_id"]}, {"name": 1})["name"]
    params_json = str(run.get("params", {}))

    cmd = (cmd.replace("{model}", model_name)
              .replace("{source_path}", source_path)
              .replace("{dataset}", dataset_name)
              .replace("{params_json}", params_json)
              .replace("{method}", run.get("finetune_method", "sft"))
              .replace("{method_params_json}",
                       json.dumps(run.get("method_config", {}), ensure_ascii=False)))

    rid = run["_id"]
    training_runs.update_one({"_id": rid}, {"$set": {"status": "running", "updated_at": _now()}})
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=7200)
        if proc.returncode == 0:
            training_runs.update_one({"_id": rid},
                                     {"$set": {"status": "completed", "progress": 1.0,
                                               "updated_at": _now()},
                                      "$push": {"logs": {"output": proc.stdout[-2000:], "at": _now().isoformat()}}})
            models.update_one({"_id": run["model_id"]}, {"$set": {"status": "ready"}})
            return {"status": "completed", "output": proc.stdout[-500:]}
        else:
            training_runs.update_one({"_id": rid},
                                     {"$set": {"status": "failed", "updated_at": _now()},
                                      "$push": {"logs": {"error": proc.stderr[-2000:], "at": _now().isoformat()}}})
            raise RuntimeError("训练失败：" + proc.stderr[-500:])
    except subprocess.TimeoutExpired:
        training_runs.update_one({"_id": rid}, {"$set": {"status": "failed"}})
        raise RuntimeError("训练超时")


# ============ 评测 ============
def list_evaluations(run_id=None, page=1, size=50):
    cond = {}
    if run_id:
        cond["run_id"] = ObjectId(run_id)
    total = evaluations.count_documents(cond)
    cur = evaluations.find(cond, {"run_id": 1, "metric": 1, "value": 1,
                                  "note": 1, "created_at": 1}) \
        .sort("created_at", -1).skip((page - 1) * size).limit(size)
    rows = []
    for d in cur:
        d["_id"] = str(d["_id"])
        d["run_id"] = str(d["run_id"]) if d.get("run_id") else None
        rows.append(d)
    return {"total": total, "rows": rows}


def add_evaluation(run_id, metric, value, note=None):
    if not training_runs.find_one({"_id": ObjectId(run_id)}):
        raise ValueError("训练运行不存在")
    eid = evaluations.insert_one({
        "run_id": ObjectId(run_id),
        "metric": metric,
        "value": float(value),
        "note": note or "",
        "created_at": _now(),
    }).inserted_id
    return str(eid)


def delete_evaluation(eid):
    r = evaluations.delete_one({"_id": ObjectId(eid)})
    if r.deleted_count == 0:
        raise ValueError("评测不存在")
    return True


# ============ 异步训练 + 实时进度 ============
def start_run_async(rid):
    """在后台线程异步执行训练，立即返回（不阻塞）。"""
    run = training_runs.find_one({"_id": ObjectId(rid)})
    if not run:
        raise ValueError("训练运行不存在")
    if run.get("status") == "running":
        raise ValueError("训练已在运行中")

    def _worker():
        try:
            execute_run(rid)
        except Exception as e:
            training_runs.update_one(
                {"_id": ObjectId(rid)},
                {"$set": {"status": "failed", "updated_at": _now()},
                 "$push": {"logs": {"error": str(e), "at": _now().isoformat()}}})

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return {"started": True, "run_id": rid}


def get_run_progress(rid):
    """查询训练运行的实时进度与日志。"""
    run = training_runs.find_one({"_id": ObjectId(rid)})
    if not run:
        raise ValueError("训练运行不存在")
    return {
        "status": run.get("status"),
        "progress": run.get("progress", 0.0),
        "metrics": run.get("metrics", {}),
        "logs": run.get("logs", [])[-20:],  # 最近 20 条日志
        "log_count": len(run.get("logs", [])),
    }
