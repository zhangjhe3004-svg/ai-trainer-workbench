# -*- coding: utf-8 -*-
"""数据集管理服务：导入、CRUD、预览、样本标注。

"""
import json
import csv
import io
import random
from datetime import datetime, timezone

from bson import ObjectId

from db import datasets


def _now():
    return datetime.now(timezone.utc)


def list_datasets(keyword=None, dataset_type=None, page=1, size=50):
    cond = {}
    if keyword:
        cond["name"] = {"$regex": keyword, "$options": "i"}
    if dataset_type:
        cond["dataset_type"] = dataset_type
    total = datasets.count_documents(cond)
    cur = datasets.find(cond, {"name": 1, "description": 1, "dataset_type": 1,
                               "format": 1, "sample_count": 1, "tags": 1,
                               "splits.counts": 1, "created_at": 1}) \
        .sort("created_at", -1).skip((page - 1) * size).limit(size)
    rows = []
    for d in cur:
        d["_id"] = str(d["_id"])
        rows.append(d)
    return {"total": total, "rows": rows}


def get_dataset(did):
    d = datasets.find_one({"_id": ObjectId(did)})
    if not d:
        return None
    d["_id"] = str(d["_id"])
    return d


def create_dataset(name, description, dataset_type, tags, data):
    """创建数据集。data 为样本列表（list of dict）。

    dataset_type: instruction / preference / classification / qa / raw
    """
    if datasets.find_one({"name": name}):
        raise ValueError("数据集已存在：" + name)
    format_type = "json"
    did = datasets.insert_one({
        "name": name,
        "description": description,
        "dataset_type": dataset_type,
        "format": format_type,
        "tags": tags or [],
        "samples": data or [],
        "sample_count": len(data or []),
        "created_at": _now(),
        "updated_at": _now(),
    }).inserted_id

    # 自动向量化样本（构建向量数据库，供相似度检索/自动归类）
    try:
        from services import vector
        for i, s in enumerate(data or []):
            if isinstance(s, dict):
                text = " ".join(str(v) for v in s.values())[:500]
            else:
                text = str(s)[:500]
            vector.index_text("dataset", str(did), text,
                              title=f"{name}#{i+1}", extra={"dataset_id": str(did)})
    except Exception:
        pass  # 向量化失败不阻塞主流程

    return str(did)


def import_dataset_json(name, description, dataset_type, tags, json_text):
    """从 JSON 文本导入数据集。支持 [{"input":..., "output":...}, ...] 或 JSONL。"""
    samples = []
    text = json_text.strip()
    if not text:
        raise ValueError("内容为空")
    # 尝试 JSON 数组
    try:
        data = json.loads(text)
        if isinstance(data, list):
            samples = data
        else:
            raise ValueError("JSON 需为数组")
    except json.JSONDecodeError:
        # 尝试 JSONL（每行一个 JSON）
        for line in text.splitlines():
            line = line.strip()
            if line:
                try:
                    samples.append(json.loads(line))
                except json.JSONDecodeError:
                    raise ValueError("JSON 或 JSONL 格式错误：%s" % line[:50])
    return create_dataset(name, description, dataset_type, tags, samples)


def import_dataset_csv(name, description, dataset_type, tags, csv_text):
    """从 CSV 文本导入数据集。"""
    reader = csv.DictReader(io.StringIO(csv_text))
    samples = [dict(row) for row in reader]
    if not samples:
        raise ValueError("CSV 无数据行")
    return create_dataset(name, description, dataset_type, tags, samples)


def update_dataset(did, name=None, description=None, tags=None):
    d = datasets.find_one({"_id": ObjectId(did)})
    if not d:
        raise ValueError("数据集不存在")
    upd = {}
    if name is not None:
        upd["name"] = name
    if description is not None:
        upd["description"] = description
    if tags is not None:
        upd["tags"] = tags
    if upd:
        upd["updated_at"] = _now()
        datasets.update_one({"_id": ObjectId(did)}, {"$set": upd})
    return True


def add_samples(did, samples):
    """向数据集追加样本。"""
    r = datasets.update_one(
        {"_id": ObjectId(did)},
        {"$push": {"samples": {"$each": samples}},
         "$inc": {"sample_count": len(samples)},
         "$set": {"updated_at": _now()}})
    if r.matched_count == 0:
        raise ValueError("数据集不存在")
    return True


def preview_samples(did, offset=0, limit=5):
    """预览数据集样本。"""
    d = datasets.find_one({"_id": ObjectId(did)},
                          {"samples": {"$slice": [offset, limit]}, "name": 1})
    if not d:
        raise ValueError("数据集不存在")
    return {"name": d["name"], "samples": d.get("samples", [])}


def delete_dataset(did):
    r = datasets.delete_one({"_id": ObjectId(did)})
    if r.deleted_count == 0:
        raise ValueError("数据集不存在")
    # 级联删除向量索引
    try:
        from db import vector_index
        vector_index.delete_many({"source_type": "dataset", "source_id": did})
    except Exception:
        pass
    return True


# ============ 数据拆分（train / valid / test） ============
def split_dataset(did, train_ratio=0.8, valid_ratio=0.1, test_ratio=0.1, seed=42):
    """将数据集拆分为训练集 / 验证集 / 测试集。

    结果写入数据集的 splits 字段：{"train": [...], "valid": [...], "test": [...]}
    并记录各子集的样本数与拆分比例。
    """
    d = datasets.find_one({"_id": ObjectId(did)})
    if not d:
        raise ValueError("数据集不存在")
    samples = d.get("samples", [])
    if not samples:
        raise ValueError("数据集无样本")
    total = train_ratio + valid_ratio + test_ratio
    if abs(total - 1.0) > 1e-6:
        raise ValueError("拆分比例之和需为 1.0")

    rng = random.Random(seed)
    shuffled = samples[:]
    rng.shuffle(shuffled)
    n = len(shuffled)
    n_train = int(n * train_ratio)
    n_valid = int(n * valid_ratio)
    # 剩余全部给 test，避免因取整丢样本
    train = shuffled[:n_train]
    valid = shuffled[n_train:n_train + n_valid]
    test = shuffled[n_train + n_valid:]

    splits = {
        "train": train,
        "valid": valid,
        "test": test,
        "counts": {"train": len(train), "valid": len(valid), "test": len(test)},
        "ratios": {"train": train_ratio, "valid": valid_ratio, "test": test_ratio},
        "seed": seed,
        "split_at": _now(),
    }
    datasets.update_one({"_id": ObjectId(did)}, {"$set": {"splits": splits, "updated_at": _now()}})
    return splits["counts"]


def get_split(did, split_name="train"):
    """获取数据集的某个子集。split_name: train / valid / test。"""
    d = datasets.find_one({"_id": ObjectId(did)})
    if not d:
        raise ValueError("数据集不存在")
    splits = d.get("splits")
    if not splits:
        raise ValueError("数据集尚未拆分，请先执行拆分")
    return splits.get(split_name, [])


def import_dataset_file(name, description, dataset_type, tags, content, filename=""):
    """从上传文件内容导入数据集（自动识别 JSON / JSONL / CSV）。"""
    content = (content or "").strip()
    if not content:
        raise ValueError("文件内容为空")
    lower = filename.lower()
    if lower.endswith(".csv"):
        return import_dataset_csv(name, description, dataset_type, tags, content)
    elif lower.endswith(".jsonl"):
        # JSONL：每行一个 JSON
        samples = []
        for line in content.splitlines():
            line = line.strip()
            if line:
                try:
                    samples.append(json.loads(line))
                except json.JSONDecodeError:
                    raise ValueError("JSONL 格式错误：" + line[:50])
        return create_dataset(name, description, dataset_type, tags, samples)
    else:
        # 默认按 JSON 处理（也兼容 JSONL）
        return import_dataset_json(name, description, dataset_type, tags, content)
