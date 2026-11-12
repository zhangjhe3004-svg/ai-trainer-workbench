# -*- coding: utf-8 -*-
"""Flask 接口 + 网页界面：AI 训练师工作台（AI Trainer Workbench）。

核心模块：模型管理 / 参数调配 / 技能扩展 / 数据训练 / 知识库 / 数据集 / LLM / 向量检索。
训练师在这里注册模型、调配超参数、给模型增加技能、用数据训练模型并追踪评测。
"""
from flask import Flask, jsonify, request, render_template

from db import init_indexes
from services import model, dataset, document, training
from services import llm, vector, version, nlp

app = Flask(__name__)


def ok(data=None):
    return jsonify({"code": 0, "data": data})


def err(msg, code=400):
    return jsonify({"code": code, "msg": msg}), code


# ============ 页面 ============
@app.get("/")
def index():
    return render_template("index.html")


# ============ 模型管理 ============
@app.get("/api/models")
def api_list_models():
    kw = request.args
    return ok(model.list_models(kw.get("keyword"), kw.get("model_type"),
                                int(kw.get("page", 1)), int(kw.get("size", 50))))


@app.get("/api/models/<mid>")
def api_get_model(mid):
    d = model.get_model(mid)
    return ok(d) if d else err("模型不存在", 404)


@app.post("/api/models")
def api_create_model():
    b = request.get_json()
    try:
        mid = model.create_model(b["name"], b["base_model"],
                                 b.get("model_type", "llm"),
                                 b.get("description", ""), b.get("tags", []),
                                 b.get("source"))
        return ok({"id": mid})
    except ValueError as e:
        return err(str(e))


@app.post("/api/models/browse-dir")
def api_browse_dir():
    """浏览本地目录（供前端选择模型文件夹）。"""
    b = request.get_json(silent=True) or {}
    try:
        return ok(model.browse_local_dir(b.get("path")))
    except ValueError as e:
        return err(str(e), 404)


@app.post("/api/models/detect-source")
def api_detect_source():
    """检测模型来源类型并校验。"""
    b = request.get_json(silent=True) or {}
    try:
        return ok(model.detect_source(b.get("source_path", "")))
    except ValueError as e:
        return err(str(e))


@app.put("/api/models/<mid>")
def api_update_model(mid):
    b = request.get_json()
    try:
        model.update_model(mid, b.get("name"), b.get("description"),
                           b.get("tags"), b.get("status"))
        return ok()
    except ValueError as e:
        return err(str(e), 404)


@app.delete("/api/models/<mid>")
def api_delete_model(mid):
    try:
        model.delete_model(mid)
        return ok()
    except ValueError as e:
        return err(str(e), 404)


# ============ 参数调配 ============
@app.get("/api/models/<mid>/params")
def api_get_params(mid):
    p = model.get_params(mid)
    return ok(p) if p else err("参数配置不存在", 404)


@app.put("/api/models/<mid>/params")
def api_update_params(mid):
    b = request.get_json()
    try:
        merged = model.update_params(mid, b.get("params", {}))
        return ok({"params": merged})
    except ValueError as e:
        return err(str(e), 404)


@app.post("/api/models/<mid>/params/reset")
def api_reset_params(mid):
    try:
        params = model.reset_params(mid)
        return ok({"params": params})
    except ValueError as e:
        return err(str(e), 404)


# ============ 技能扩展 ============
@app.get("/api/skills")
def api_list_skills():
    kw = request.args
    return ok(model.list_skills(kw.get("keyword"), kw.get("category"),
                                kw.get("model_id"),
                                int(kw.get("page", 1)), int(kw.get("size", 50))))


@app.post("/api/skills")
def api_create_skill():
    b = request.get_json()
    try:
        sid = model.create_skill(b["name"], b["category"],
                                 b.get("description", ""),
                                 b.get("prompt_template"),
                                 b.get("prerequisites", []),
                                 b.get("model_id"))
        return ok({"id": sid})
    except ValueError as e:
        return err(str(e))


@app.put("/api/skills/<sid>")
def api_update_skill(sid):
    b = request.get_json()
    try:
        model.update_skill(sid, b.get("name"), b.get("category"),
                           b.get("description"), b.get("prompt_template"),
                           b.get("enabled"))
        return ok()
    except ValueError as e:
        return err(str(e), 404)


@app.delete("/api/skills/<sid>")
def api_delete_skill(sid):
    try:
        model.delete_skill(sid)
        return ok()
    except ValueError as e:
        return err(str(e), 404)


@app.post("/api/models/<mid>/skills/<sid>")
def api_mount_skill(mid, sid):
    """给模型挂载技能（增加能力）。"""
    try:
        model.mount_skill(mid, sid)
        return ok()
    except ValueError as e:
        return err(str(e), 404)


@app.delete("/api/skills/<sid>/mount")
def api_unmount_skill(sid):
    """从模型移除技能。"""
    try:
        model.unmount_skill(sid)
        return ok()
    except ValueError as e:
        return err(str(e), 404)


# ============ 数据集管理 ============
@app.get("/api/datasets")
def api_list_datasets():
    kw = request.args
    return ok(dataset.list_datasets(kw.get("keyword"), kw.get("dataset_type"),
                                    int(kw.get("page", 1)), int(kw.get("size", 50))))


@app.get("/api/datasets/<did>")
def api_get_dataset(did):
    d = dataset.get_dataset(did)
    return ok(d) if d else err("数据集不存在", 404)


@app.post("/api/datasets")
def api_create_dataset():
    b = request.get_json()
    try:
        did = dataset.create_dataset(b["name"], b.get("description", ""),
                                     b.get("dataset_type", "raw"),
                                     b.get("tags", []), b.get("samples", []))
        return ok({"id": did})
    except ValueError as e:
        return err(str(e))


@app.post("/api/datasets/import")
def api_import_dataset():
    """导入数据集：JSON/JSONL/CSV 文本。"""
    b = request.get_json()
    try:
        fmt = b.get("format", "json")
        if fmt == "csv":
            did = dataset.import_dataset_csv(b["name"], b.get("description", ""),
                                             b.get("dataset_type", "raw"),
                                             b.get("tags", []), b["content"])
        else:
            did = dataset.import_dataset_json(b["name"], b.get("description", ""),
                                              b.get("dataset_type", "raw"),
                                              b.get("tags", []), b["content"])
        return ok({"id": did})
    except ValueError as e:
        return err(str(e))


@app.get("/api/datasets/<did>/preview")
def api_preview_dataset(did):
    kw = request.args
    try:
        return ok(dataset.preview_samples(did, int(kw.get("offset", 0)),
                                          int(kw.get("limit", 5))))
    except ValueError as e:
        return err(str(e), 404)


@app.delete("/api/datasets/<did>")
def api_delete_dataset(did):
    try:
        dataset.delete_dataset(did)
        return ok()
    except ValueError as e:
        return err(str(e), 404)


@app.post("/api/datasets/import-file")
def api_import_dataset_file():
    """文件上传导入：JSON / JSONL / CSV 自动识别。"""
    f = request.files.get("file")
    name = request.form.get("name")
    if not f or not name:
        return err("缺少文件或数据集名称")
    try:
        content = f.read().decode("utf-8")
        did = dataset.import_dataset_file(
            name, request.form.get("description", ""),
            request.form.get("dataset_type", "raw"),
            request.form.getlist("tags"), content, f.filename)
        return ok({"id": did})
    except Exception as e:
        return err(str(e))


@app.post("/api/datasets/<did>/split")
def api_split_dataset(did):
    """数据拆分：train / valid / test。"""
    b = request.get_json(silent=True) or {}
    try:
        counts = dataset.split_dataset(
            did,
            float(b.get("train_ratio", 0.8)),
            float(b.get("valid_ratio", 0.1)),
            float(b.get("test_ratio", 0.1)),
            int(b.get("seed", 42)))
        return ok({"counts": counts})
    except ValueError as e:
        return err(str(e), 404)


@app.get("/api/datasets/<did>/split")
def api_get_split(did):
    """查看数据集拆分结果。"""
    kw = request.args
    try:
        return ok(dataset.get_split(did, kw.get("split", "train")))
    except ValueError as e:
        return err(str(e), 404)


# ============ 知识库 ============
@app.get("/api/documents")
def api_list_documents():
    kw = request.args
    return ok(document.list_documents(kw.get("keyword"), kw.get("model_id"),
                                      int(kw.get("page", 1)), int(kw.get("size", 50))))


@app.post("/api/documents")
def api_create_document():
    b = request.get_json()
    try:
        did = document.create_document(b["title"], b["content"],
                                       b.get("model_id"), b.get("doc_type", "note"),
                                       b.get("summary"), b.get("tags", []),
                                       b.get("image_b64"), b.get("image_mime", "image/jpeg"))
        return ok({"id": did})
    except ValueError as e:
        return err(str(e))


@app.put("/api/documents/<did>")
def api_update_document(did):
    b = request.get_json()
    try:
        document.update_document(did, b.get("title"), b.get("content"),
                                 b.get("model_id"), b.get("doc_type"),
                                 b.get("summary"), b.get("tags"))
        return ok()
    except ValueError as e:
        return err(str(e), 404)


@app.delete("/api/documents/<did>")
def api_delete_document(did):
    try:
        document.delete_document(did)
        return ok()
    except ValueError as e:
        return err(str(e), 404)


# ============ 训练运行与评测 ============
@app.get("/api/runs")
def api_list_runs():
    kw = request.args
    return ok(training.list_runs(kw.get("keyword"), kw.get("status"), kw.get("model_id"),
                                 int(kw.get("page", 1)), int(kw.get("size", 50))))


@app.get("/api/runs/<rid>")
def api_get_run(rid):
    d = training.get_run(rid)
    return ok(d) if d else err("训练运行不存在", 404)


@app.post("/api/runs")
def api_create_run():
    b = request.get_json()
    try:
        rid = training.create_run(b["name"], b["model_id"], b["dataset_id"],
                                  b.get("task_type", "fine_tuning"),
                                  b.get("params"), b.get("description", ""),
                                  b.get("mode", "simulate"))
        return ok({"id": rid})
    except ValueError as e:
        return err(str(e))


@app.post("/api/runs/<rid>/execute")
def api_execute_run(rid):
    """执行训练运行（模拟或真实）。"""
    try:
        result = training.execute_run(rid)
        return ok(result)
    except Exception as e:
        return err(str(e), 500)


@app.post("/api/runs/<rid>/start-async")
def api_start_run_async(rid):
    """异步执行训练（后台线程，立即返回）。"""
    try:
        return ok(training.start_run_async(rid))
    except ValueError as e:
        return err(str(e), 404)


@app.get("/api/runs/<rid>/progress")
def api_get_run_progress(rid):
    """查询训练实时进度与日志。"""
    try:
        return ok(training.get_run_progress(rid))
    except ValueError as e:
        return err(str(e), 404)


@app.put("/api/runs/<rid>/status")
def api_update_run_status(rid):
    b = request.get_json()
    try:
        training.update_run_status(rid, b["status"])
        return ok()
    except ValueError as e:
        return err(str(e), 404)


@app.delete("/api/runs/<rid>")
def api_delete_run(rid):
    try:
        training.delete_run(rid)
        return ok()
    except ValueError as e:
        return err(str(e), 404)


@app.get("/api/evaluations")
def api_list_evaluations():
    kw = request.args
    return ok(training.list_evaluations(kw.get("run_id"),
                                        int(kw.get("page", 1)), int(kw.get("size", 50))))


@app.post("/api/evaluations")
def api_add_evaluation():
    b = request.get_json()
    try:
        eid = training.add_evaluation(b["run_id"], b["metric"], b["value"], b.get("note"))
        return ok({"id": eid})
    except ValueError as e:
        return err(str(e))


@app.delete("/api/evaluations/<eid>")
def api_delete_evaluation(eid):
    try:
        training.delete_evaluation(eid)
        return ok()
    except ValueError as e:
        return err(str(e), 404)


# ============ 模型版本管理 ============
@app.get("/api/versions")
def api_list_versions():
    kw = request.args
    return ok(version.list_versions(kw.get("model_id"), kw.get("status"),
                                    int(kw.get("page", 1)), int(kw.get("size", 50))))


@app.get("/api/versions/<vid>")
def api_get_version(vid):
    d = version.get_version(vid)
    return ok(d) if d else err("版本不存在", 404)


@app.post("/api/versions")
def api_create_version():
    """手动创建模型版本。"""
    b = request.get_json()
    try:
        vid = version.create_version(b["model_id"], b.get("run_id"),
                                     b.get("note", ""), b.get("metrics"))
        return ok({"id": vid})
    except ValueError as e:
        return err(str(e))


@app.post("/api/versions/<vid>/release")
def api_release_version(vid):
    """发布版本（标记为线上可用）。"""
    try:
        version.release_version(vid)
        return ok()
    except ValueError as e:
        return err(str(e), 404)


@app.post("/api/versions/<vid>/archive")
def api_archive_version(vid):
    """归档（下线）版本。"""
    try:
        version.archive_version(vid)
        return ok()
    except ValueError as e:
        return err(str(e), 404)


@app.delete("/api/versions/<vid>")
def api_delete_version(vid):
    try:
        version.delete_version(vid)
        return ok()
    except ValueError as e:
        return err(str(e), 404)


@app.get("/api/versions/compare/<mid>")
def api_compare_versions(mid):
    """横向对比同一模型的所有版本指标。"""
    try:
        return ok(version.compare_versions(mid))
    except Exception as e:
        return err(str(e), 500)


@app.post("/api/models/<mid>/infer")
def api_model_infer(mid):
    """基于模型某版本做推理（未指定版本则用已发布版本）。"""
    b = request.get_json()
    try:
        return ok(version.infer(mid, b.get("version"), b.get("prompt", "")))
    except ValueError as e:
        return err(str(e), 404)


# ============ LLM 接入 + 向量检索 ============
@app.get("/api/llm/status")
def api_llm_status():
    return ok({
        "llm_backend": llm.backend(),
        "llm_model": llm.LLM_MODEL if llm.backend() == "openai" else
                     (llm.OLLAMA_MODEL if llm.backend() == "ollama" else None),
        "embed_model": llm.LLM_EMBED_MODEL if llm.backend() == "openai" else
                       (llm.OLLAMA_EMBED_MODEL if llm.backend() == "ollama" else "hash-projection"),
    })


@app.post("/api/llm/chat")
def api_llm_chat():
    """RAG 问答：检索知识库 → 交给 LLM 生成回答。"""
    b = request.get_json()
    try:
        res = vector.rag_chat(b["question"], history=b.get("history"),
                              top_k=int(b.get("top_k", 5)))
        cid = b.get("conversation_id", "default")
        vector.save_conversation(cid, "user", b["question"])
        vector.save_conversation(cid, "assistant", res["answer"],
                                 {"backend": res["backend"], "model": res["model"]})
        return ok(res)
    except Exception as e:
        return err(str(e), 500)


@app.get("/api/llm/conversations/<cid>")
def api_llm_conversations(cid):
    return ok(vector.list_conversations(cid))


@app.post("/api/llm/embed")
def api_llm_embed():
    b = request.get_json()
    try:
        r = llm.embed(b.get("texts", b.get("text", "")))
        return ok({"dim": r["dim"], "backend": r["backend"], "model": r["model"],
                   "vectors": r["vectors"]})
    except Exception as e:
        return err(str(e), 500)


@app.post("/api/vector/index-documents")
def api_vector_index_documents():
    try:
        n = vector.index_all_documents()
        return ok({"indexed": n})
    except Exception as e:
        return err(str(e), 500)


@app.post("/api/vector/index-skills")
def api_vector_index_skills():
    try:
        n = vector.index_all_skills()
        return ok({"indexed": n})
    except Exception as e:
        return err(str(e), 500)


@app.get("/api/vector/search")
def api_vector_search():
    kw = request.args
    try:
        rows = vector.search_similar(kw.get("q", ""),
                                     limit=int(kw.get("limit", 5)),
                                     source_type=kw.get("source_type"),
                                     content_type=kw.get("content_type"))
        return ok({"rows": rows})
    except Exception as e:
        return err(str(e), 500)


@app.post("/api/vector/auto-assign")
def api_vector_auto_assign():
    b = request.get_json()
    try:
        matches = vector.auto_assign_skill(b.get("text", ""), top_k=int(b.get("top_k", 3)))
        return ok({"matches": matches})
    except Exception as e:
        return err(str(e), 500)


@app.post("/api/vector/assign-document/<doc_id>")
def api_vector_assign_document(doc_id):
    try:
        matches = vector.assign_document_skill(doc_id, auto=True)
        return ok({"matches": matches})
    except Exception as e:
        return err(str(e), 500)


@app.post("/api/vector/assign-dataset/<dataset_id>")
def api_vector_assign_dataset(dataset_id):
    try:
        result = vector.assign_dataset_skill(dataset_id)
        return ok({"distribution": result})
    except Exception as e:
        return err(str(e), 500)


# ============ 多模态（图片向量化 + 视觉理解） ============
@app.post("/api/vector/index-image")
def api_vector_index_image():
    """多模态图片向量化：把图片（base64）写入向量数据库。"""
    b = request.get_json()
    try:
        iid = vector.index_image(
            b.get("source_type", "image"), b.get("source_id", "manual"),
            b.get("image_b64"), b.get("caption", ""), b.get("title", ""),
            {"mime": b.get("mime", "image/jpeg")})
        return ok({"id": iid})
    except Exception as e:
        return err(str(e), 500)


@app.post("/api/llm/vision")
def api_llm_vision():
    """多模态视觉理解：文本 + 图片 → 描述/问答。"""
    b = request.get_json()
    try:
        res = llm.chat_vision(b.get("prompt", ""), b.get("image_b64"),
                              b.get("image_url"), b.get("mime", "image/jpeg"))
        return ok(res)
    except Exception as e:
        return err(str(e), 500)


# ============ NLP 自然语言处理 ============
@app.get("/api/nlp/functions")
def api_nlp_functions():
    """列出所有可用 NLP 功能。"""
    return ok(nlp.list_functions())


@app.post("/api/nlp/run")
def api_nlp_run():
    """执行 NLP 功能。body: {"function": "sentiment", "params": {"text": "..."}}"""
    b = request.get_json()
    try:
        result = nlp.run_nlp(b.get("function"), b.get("params", {}))
        return ok(result)
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(str(e), 500)


if __name__ == "__main__":
    init_indexes()
    app.run(host="127.0.0.1", port=5000, debug=False)
