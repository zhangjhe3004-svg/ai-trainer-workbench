# -*- coding: utf-8 -*-
"""知识库服务：知识文档 CRUD + 关联模型（知识注入）。

对应 roadmap.sh AI Engineer：Embeddings / Knowledge / RAG。
知识文档是注入给模型的知识载体（RAG / 知识增强），可向量化后用于语义检索。
"""
from datetime import datetime, timezone

from bson import ObjectId

from db import documents, models


def _now():
    return datetime.now(timezone.utc)


def list_documents(keyword=None, model_id=None, page=1, size=50):
    cond = {}
    if keyword:
        cond["$or"] = [
            {"title": {"$regex": keyword, "$options": "i"}},
            {"content": {"$regex": keyword, "$options": "i"}},
        ]
    if model_id:
        cond["model_id"] = ObjectId(model_id)
    total = documents.count_documents(cond)
    cur = documents.find(cond, {"title": 1, "model_id": 1, "doc_type": 1,
                                "summary": 1, "created_at": 1}) \
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


def get_document(did):
    d = documents.find_one({"_id": ObjectId(did)})
    if not d:
        return None
    d["_id"] = str(d["_id"])
    d["model_id"] = str(d["model_id"]) if d.get("model_id") else None
    return d


def create_document(title, content, model_id=None, doc_type="note", summary=None,
                    tags=None, image_b64=None, image_mime="image/jpeg"):
    """新增知识文档，可关联模型（注入给模型的知识）。

    支持多模态：可携带图片（image_b64），文档会同时向量化文本与图片，
    使 RAG 检索时能召回图文内容。
    """
    doc = {
        "title": title,
        "content": content,
        "doc_type": doc_type,  # note / article / reference / example / image
        "summary": summary or "",
        "tags": tags or [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    if model_id:
        if not models.find_one({"_id": ObjectId(model_id)}):
            raise ValueError("模型不存在")
        doc["model_id"] = ObjectId(model_id)
    # 多模态：图片字段
    if image_b64:
        doc["has_image"] = True
        doc["image_mime"] = image_mime
    did = documents.insert_one(doc).inserted_id

    # 自动向量化入库（构建向量数据库）
    try:
        from services import vector
        vector.index_document(str(did))
        # 若有图片，额外索引图片向量（多模态）
        if image_b64:
            vector.index_image("document", str(did), image_b64,
                               caption=title + " " + (summary or ""),
                               title=title, extra={"model_id": str(doc.get("model_id")) if doc.get("model_id") else None,
                                                    "mime": image_mime})
    except Exception:
        pass  # 向量化失败不阻塞主流程

    return str(did)


def update_document(did, title=None, content=None, model_id=None, doc_type=None, summary=None, tags=None):
    d = documents.find_one({"_id": ObjectId(did)})
    if not d:
        raise ValueError("文档不存在")
    upd = {}
    if title is not None:
        upd["title"] = title
    if content is not None:
        upd["content"] = content
    if doc_type is not None:
        upd["doc_type"] = doc_type
    if summary is not None:
        upd["summary"] = summary
    if tags is not None:
        upd["tags"] = tags
    if model_id is not None:
        if model_id and not models.find_one({"_id": ObjectId(model_id)}):
            raise ValueError("模型不存在")
        upd["model_id"] = ObjectId(model_id) if model_id else None
    if upd:
        upd["updated_at"] = _now()
        documents.update_one({"_id": ObjectId(did)}, {"$set": upd})
        # 内容变更后重新向量化
        try:
            from services import vector
            vector.index_document(did)
        except Exception:
            pass
    return True


def delete_document(did):
    r = documents.delete_one({"_id": ObjectId(did)})
    if r.deleted_count == 0:
        raise ValueError("文档不存在")
    # 级联删除向量索引
    try:
        from db import vector_index
        vector_index.delete_many({"source_type": "document", "source_id": did})
    except Exception:
        pass
    return True


def list_by_model(model_id):
    """按模型列出其知识文档。"""
    cur = documents.find({"model_id": ObjectId(model_id)},
                         {"title": 1, "doc_type": 1, "summary": 1})
    return [{"id": str(d["_id"]), "title": d["title"],
             "doc_type": d.get("doc_type"), "summary": d.get("summary", "")}
            for d in cur]
