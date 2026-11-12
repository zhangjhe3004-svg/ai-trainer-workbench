# -*- coding: utf-8 -*-
"""模型管理服务：模型注册 + 参数调配 + 技能扩展。

AI 训练师工作台核心模块。训练师在这里：
1. 注册模型（名称 / 基座 / 类型 / 描述）
2. 调配模型核心超参数（learning rate / batch size / epochs / 温度 / top_p 等）
3. 给模型增加 / 移除「技能」（skill），扩展模型能力
"""
import os

from datetime import datetime, timezone

from bson import ObjectId

from db import models, model_params, skills, graph_edges, features


def _now():
    return datetime.now(timezone.utc)


# ============ 模型来源类型 ============
# registered: 仅名称注册（原方式）；local_dir: 本地文件夹；local_file: 本地权重文件
# huggingface: HuggingFace 仓库 ID；url: 远程下载地址
SOURCE_TYPES = ["registered", "local_dir", "local_file", "huggingface", "url"]

SOURCE_LABELS = {
    "registered": "已注册模型",
    "local_dir": "本地文件夹",
    "local_file": "本地文件",
    "huggingface": "HuggingFace 仓库",
    "url": "远程 URL",
}


def _detect_source_type(path):
    """根据路径/标识符自动推断模型来源类型。"""
    s = (path or "").strip()
    if not s:
        return "registered"
    if s.startswith("http://") or s.startswith("https://"):
        return "url"
    # 形如 org/name 或 name 且含 /，且不是绝对路径 → HuggingFace 仓库 ID
    if "/" in s and not os.path.isabs(s) and not s.startswith("."):
        # 排除 Windows 盘符（C:/）或本地路径
        if len(s) >= 2 and s[1] == ":":
            return "local_dir"
        return "huggingface"
    # 绝对路径或含盘符 → 本地
    if os.path.isabs(s) or (len(s) >= 2 and s[1] == ":") or s.startswith("./") or s.startswith(".."):
        if os.path.isdir(s) or s.endswith("/") or s.endswith("\\"):
            return "local_dir"
        return "local_file"
    return "registered"


# ============ 模型注册 ============
def list_models(keyword=None, model_type=None, page=1, size=50):
    cond = {}
    if keyword:
        cond["name"] = {"$regex": keyword, "$options": "i"}
    if model_type:
        cond["model_type"] = model_type
    total = models.count_documents(cond)
    cur = models.find(cond, {"name": 1, "base_model": 1, "model_type": 1,
                             "status": 1, "description": 1, "source_type": 1,
                             "source_path": 1, "created_at": 1}) \
        .sort("created_at", -1).skip((page - 1) * size).limit(size)
    rows = []
    for d in cur:
        d["_id"] = str(d["_id"])
        d["skill_count"] = _count_skills(str(d["_id"]))
        d["run_count"] = _count_runs(str(d["_id"]))
        d["source_label"] = SOURCE_LABELS.get(d.get("source_type", "registered"), "已注册模型")
        rows.append(d)
    return {"total": total, "rows": rows}


def _count_skills(model_id):
    """统计某模型已挂载的技能数。"""
    return model_params.count_documents({"model_id": ObjectId(model_id)}) if False else \
        skills.count_documents({"model_id": ObjectId(model_id)})


def _count_runs(model_id):
    from db import training_runs
    return training_runs.count_documents({"model_id": ObjectId(model_id)})


def get_model(mid):
    d = models.find_one({"_id": ObjectId(mid)})
    if not d:
        return None
    d["_id"] = str(d["_id"])
    d["source_label"] = SOURCE_LABELS.get(d.get("source_type", "registered"), "已注册模型")
    return d


# ============ 本地目录浏览 + 来源检测 ============
def browse_local_dir(path=None):
    """浏览本地目录，返回子目录与文件列表（供前端「选择文件夹」）。

    path 为空时返回磁盘根/驱动器列表；否则返回该目录下的子目录 + 常见模型文件。
    """
    if not path:
        # 返回可用驱动器
        drives = []
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            p = f"{letter}:/"
            if os.path.exists(p):
                drives.append({"name": f"{letter}:/", "path": f"{letter}:/", "type": "drive"})
        return {"current": "", "parent": None, "drives": drives, "dirs": [], "files": []}

    p = os.path.normpath(path)
    if not os.path.isdir(p):
        raise ValueError("目录不存在：" + path)
    dirs, files = [], []
    try:
        for entry in sorted(os.listdir(p), key=str.lower):
            full = os.path.join(p, entry)
            if os.path.isdir(full):
                dirs.append({"name": entry, "path": full, "type": "dir"})
            elif os.path.isfile(full):
                files.append({"name": entry, "path": full, "type": "file",
                              "size": os.path.getsize(full)})
    except PermissionError:
        raise ValueError("无权限访问该目录：" + path)
    parent = os.path.dirname(p) if p != os.path.dirname(p) else None
    return {"current": p, "parent": parent, "drives": [],
            "dirs": dirs[:200], "files": files[:200]}


def detect_source(source_path):
    """检测模型来源：返回推断的来源类型 + 校验结果。"""
    s = (source_path or "").strip()
    source_type = _detect_source_type(s)
    result = {"source_type": source_type, "source_path": s,
              "label": SOURCE_LABELS[source_type], "valid": True, "message": ""}
    if source_type == "local_dir":
        if os.path.isdir(s):
            # 尝试识别模型标记文件（宽松，仅提示）
            markers = [f for f in ("config.json", "pytorch_model.bin", "model.safetensors",
                                   "adapter_config.json", "ggml-model", "tokenizer.json")
                       if os.path.exists(os.path.join(s, f))]
            result["message"] = ("检测到 HuggingFace/模型目录，含标记文件：" + ", ".join(markers)) if markers \
                else "目录存在（未识别到常见模型文件，仍可继续）"
        else:
            result["valid"] = False
            result["message"] = "目录不存在"
    elif source_type == "local_file":
        result["valid"] = os.path.isfile(s)
        result["message"] = "文件存在" if result["valid"] else "文件不存在"
    elif source_type == "huggingface":
        result["message"] = "HuggingFace 仓库 ID（训练时将自动拉取）"
    elif source_type == "url":
        result["message"] = "远程模型下载地址"
    else:
        result["message"] = "仅名称注册（无实体文件）"
    return result


def create_model(name, base_model, model_type="llm", description="", tags=None, source=None):
    """注册一个新模型。model_type: llm / embedding / vision / multimodal

    source: 模型来源信息 dict，形如
        {"source_type": "local_dir", "source_path": "D:/models/qwen2.5-7b"}
        {"source_type": "huggingface", "source_path": "Qwen/Qwen2.5-7B"}
        {"source_type": "url", "source_path": "https://..."}
        {"source_type": "registered"}（默认，仅名称注册）
    """
    if models.find_one({"name": name}):
        raise ValueError("模型已存在：" + name)
    src = source or {}
    source_type = src.get("source_type") or _detect_source_type(base_model)
    source_path = src.get("source_path") or (base_model if source_type != "registered" else "")
    if source_type not in SOURCE_TYPES:
        raise ValueError("模型来源类型不合法：" + source_type)
    # 本地来源做存在性校验（宽松：目录/文件存在即可，不严格解析内容）
    if source_type == "local_dir" and source_path:
        if not os.path.isdir(source_path):
            raise ValueError("本地文件夹不存在：" + source_path)
    if source_type == "local_file" and source_path:
        if not os.path.isfile(source_path):
            raise ValueError("本地文件不存在：" + source_path)
    mid = models.insert_one({
        "name": name,
        "base_model": base_model,
        "model_type": model_type,
        "description": description or "",
        "tags": tags or [],
        "source_type": source_type,
        "source_path": source_path,
        "status": "registered",  # registered / training / ready / deprecated
        "created_at": _now(),
        "updated_at": _now(),
    }).inserted_id
    # 初始化默认参数配置
    init_default_params(str(mid), model_type)
    return str(mid)


def update_model(mid, name=None, description=None, tags=None, status=None):
    d = models.find_one({"_id": ObjectId(mid)})
    if not d:
        raise ValueError("模型不存在")
    upd = {}
    if name is not None:
        upd["name"] = name
    if description is not None:
        upd["description"] = description
    if tags is not None:
        upd["tags"] = tags
    if status is not None:
        upd["status"] = status
    if upd:
        upd["updated_at"] = _now()
        models.update_one({"_id": ObjectId(mid)}, {"$set": upd})
    return True


def delete_model(mid):
    r = models.delete_one({"_id": ObjectId(mid)})
    if r.deleted_count == 0:
        raise ValueError("模型不存在")
    # 级联清理参数、技能挂载、训练运行
    model_params.delete_many({"model_id": ObjectId(mid)})
    skills.update_many({"model_id": ObjectId(mid)}, {"$unset": {"model_id": ""}})
    from db import training_runs, evaluations
    for run in training_runs.find({"model_id": ObjectId(mid)}, {"_id": 1}):
        evaluations.delete_many({"run_id": run["_id"]})
    training_runs.delete_many({"model_id": ObjectId(mid)})
    return True


# ============ 参数调配 ============
# 模型核心超参数默认值（按模型类型）
DEFAULT_PARAMS = {
    "llm": {
        "learning_rate": 2e-5,
        "batch_size": 8,
        "epochs": 3,
        "temperature": 0.7,
        "top_p": 0.9,
        "max_tokens": 1024,
        "weight_decay": 0.01,
        "gradient_accumulation_steps": 1,
        "optimizer": "adamw",
        "lr_scheduler": "cosine",
    },
    "embedding": {
        "learning_rate": 3e-5,
        "batch_size": 32,
        "epochs": 2,
        "embedding_dim": 768,
        "max_seq_length": 512,
    },
    "vision": {
        "learning_rate": 1e-4,
        "batch_size": 16,
        "epochs": 5,
        "image_size": 224,
    },
    "multimodal": {
        "learning_rate": 1e-4,
        "batch_size": 4,
        "epochs": 3,
        "temperature": 0.8,
    },
}


def init_default_params(model_id, model_type="llm"):
    """为模型初始化默认参数配置。"""
    defaults = DEFAULT_PARAMS.get(model_type, DEFAULT_PARAMS["llm"])
    return str(model_params.insert_one({
        "model_id": ObjectId(model_id),
        "params": dict(defaults),
        "created_at": _now(),
        "updated_at": _now(),
    }).inserted_id)


def get_params(model_id):
    """获取模型的参数配置。"""
    p = model_params.find_one({"model_id": ObjectId(model_id)})
    if not p:
        return None
    p["_id"] = str(p["_id"])
    p["model_id"] = str(p["model_id"])
    return p


def update_params(model_id, params):
    """更新模型核心超参数（部分更新，保留未传的字段）。"""
    if not models.find_one({"_id": ObjectId(model_id)}):
        raise ValueError("模型不存在")
    existing = model_params.find_one({"model_id": ObjectId(model_id)})
    if not existing:
        # 若没有参数记录，先初始化
        m = models.find_one({"_id": ObjectId(model_id)})
        existing = {"params": dict(DEFAULT_PARAMS.get(m.get("model_type", "llm"), DEFAULT_PARAMS["llm"]))}
    merged = dict(existing.get("params", {}))
    merged.update(params or {})
    model_params.update_one(
        {"model_id": ObjectId(model_id)},
        {"$set": {"params": merged, "updated_at": _now()}},
        upsert=True)
    return merged


def reset_params(model_id):
    """重置为默认参数。"""
    m = models.find_one({"_id": ObjectId(model_id)})
    if not m:
        raise ValueError("模型不存在")
    defaults = DEFAULT_PARAMS.get(m.get("model_type", "llm"), DEFAULT_PARAMS["llm"])
    model_params.update_one(
        {"model_id": ObjectId(model_id)},
        {"$set": {"params": dict(defaults), "updated_at": _now()}})
    return dict(defaults)


# ============ 技能扩展 ============
def list_skills(keyword=None, category=None, model_id=None, page=1, size=50):
    cond = {}
    if keyword:
        cond["name"] = {"$regex": keyword, "$options": "i"}
    if category:
        cond["category"] = category
    if model_id:
        cond["model_id"] = ObjectId(model_id)
    total = skills.count_documents(cond)
    cur = skills.find(cond, {"name": 1, "category": 1, "description": 1,
                             "model_id": 1, "enabled": 1, "created_at": 1}) \
        .sort("created_at", -1).skip((page - 1) * size).limit(size)
    rows = []
    for d in cur:
        d["_id"] = str(d["_id"])
        d["model_id"] = str(d["model_id"]) if d.get("model_id") else None
        if d.get("model_id"):
            m = models.find_one({"_id": ObjectId(d["model_id"])}, {"name": 1})
            d["model_name"] = m["name"] if m else None
        rows.append(d)
    return {"total": total, "rows": rows}


def create_skill(name, category, description="", prompt_template=None,
                 prerequisites=None, model_id=None):
    """创建一个模型技能（能力）。

    category: 代码生成 / 知识问答 / 工具调用 / 文本生成 / 图像理解 / 翻译 ...
    prompt_template: 该技能的提示词模板（可选）
    prerequisites: 依赖的其他技能名（可选）
    model_id: 若指定，则直接挂载到该模型
    """
    if skills.find_one({"name": name}):
        raise ValueError("技能已存在：" + name)
    pre_titles = [p.strip() for p in (prerequisites or []) if p.strip()]
    missing = [p for p in pre_titles if not skills.find_one({"name": p})]
    if missing:
        raise ValueError("依赖技能不存在：" + ", ".join(missing))
    sid = skills.insert_one({
        "name": name,
        "category": category,
        "description": description or "",
        "prompt_template": prompt_template or "",
        "prerequisites": pre_titles,
        "model_id": ObjectId(model_id) if model_id else None,
        "enabled": True,
        "created_at": _now(),
        "updated_at": _now(),
    }).inserted_id
    # 依赖边
    for pre in pre_titles:
        pre_id = skills.find_one({"name": pre})["_id"]
        graph_edges.replace_one(
            {"from_skill": pre_id, "to_skill": sid},
            {"from_skill": pre_id, "to_skill": sid, "rel_type": "depends_on", "weight": 1.0},
            upsert=True)
    return str(sid)


def update_skill(sid, name=None, category=None, description=None,
                 prompt_template=None, enabled=None):
    d = skills.find_one({"_id": ObjectId(sid)})
    if not d:
        raise ValueError("技能不存在")
    upd = {}
    if name is not None:
        upd["name"] = name
    if category is not None:
        upd["category"] = category
    if description is not None:
        upd["description"] = description
    if prompt_template is not None:
        upd["prompt_template"] = prompt_template
    if enabled is not None:
        upd["enabled"] = bool(enabled)
    if upd:
        upd["updated_at"] = _now()
        skills.update_one({"_id": ObjectId(sid)}, {"$set": upd})
    return True


def delete_skill(sid):
    r = skills.delete_one({"_id": ObjectId(sid)})
    if r.deleted_count == 0:
        raise ValueError("技能不存在")
    graph_edges.delete_many({"$or": [{"from_skill": ObjectId(sid)}, {"to_skill": ObjectId(sid)}]})
    return True


def mount_skill(model_id, skill_id):
    """把技能挂载到模型（给模型增加能力）。"""
    if not models.find_one({"_id": ObjectId(model_id)}):
        raise ValueError("模型不存在")
    if not skills.find_one({"_id": ObjectId(skill_id)}):
        raise ValueError("技能不存在")
    skills.update_one({"_id": ObjectId(skill_id)}, {"$set": {"model_id": ObjectId(model_id)}})
    return True


def unmount_skill(skill_id):
    """从模型移除技能。"""
    skills.update_one({"_id": ObjectId(skill_id)}, {"$set": {"model_id": None}})
    return True
