# -*- coding: utf-8 -*-
"""Flask 接口 + 网页界面：AI 训练师工作台（AI Trainer Workbench）。

核心模块：模型管理 / 参数调配 / 技能扩展 / 数据训练 / 知识库 / 数据集 / LLM / 向量检索。
训练师在这里注册模型、调配超参数、给模型增加技能、用数据训练模型并追踪评测。
"""
from flask import Flask, jsonify, request, render_template

from db import init_indexes
from services import model, dataset, document, training
from services import llm, vector, version, nlp
from services import prompt as prompt_svc, finetune, evalset, guardrail, trace

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


# ============ 工程能力：统一辅助 ============
def _body():
    return request.get_json(silent=True) or {}


def _safe(fn, *args, **kwargs):
    """统一执行服务函数并包装返回值 / 异常。"""
    try:
        return ok(fn(*args, **kwargs))
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        return err(str(e), 500)


# ============ 提示词工程 ============
@app.get("/api/prompts/techniques")
def api_pe_techniques():
    return ok(prompt_svc.list_techniques())


@app.post("/api/prompts/auto-generate")
def api_pe_auto():
    b = _body()
    return _safe(prompt_svc.auto_generate, b.get("task", ""),
                 b.get("n", 3), b.get("constraints", ""))


@app.post("/api/prompts/compare")
def api_pe_compare():
    b = _body()
    return _safe(prompt_svc.compare, b.get("pid_a"), b.get("pid_b"),
                 b.get("variables"))


@app.get("/api/prompts")
def api_pe_list():
    return _safe(prompt_svc.list_prompts, request.args.get("keyword"),
                 request.args.get("technique"),
                 int(request.args.get("page", 1)), int(request.args.get("size", 50)))


@app.post("/api/prompts")
def api_pe_create():
    b = _body()
    return _safe(prompt_svc.create_prompt,
                 name=b.get("name"), content=b.get("content"),
                 system_prompt=b.get("system_prompt", ""),
                 technique=b.get("technique", "zero_shot"),
                 description=b.get("description", ""),
                 examples=b.get("examples"), sampling=b.get("sampling"),
                 json_schema=b.get("json_schema"), tags=b.get("tags"),
                 note=b.get("note", "创建模板"))


@app.get("/api/prompts/<pid>")
def api_pe_get(pid):
    return _safe(prompt_svc.get_prompt, pid)


@app.put("/api/prompts/<pid>")
def api_pe_update(pid):
    b = _body()
    return _safe(prompt_svc.update_prompt, pid, b.get("fields", b), b.get("note", "更新模板"))


@app.delete("/api/prompts/<pid>")
def api_pe_delete(pid):
    return _safe(prompt_svc.delete_prompt, pid)


@app.get("/api/prompts/<pid>/versions")
def api_pe_versions(pid):
    return _safe(prompt_svc.list_versions, pid)


@app.get("/api/prompt-versions/<vid>")
def api_pe_version_detail(vid):
    return _safe(prompt_svc.get_version, vid)


@app.post("/api/prompts/<pid>/restore/<vid>")
def api_pe_restore(pid, vid):
    return _safe(prompt_svc.restore_version, pid, vid)


@app.post("/api/prompts/<pid>/preview")
def api_pe_preview(pid):
    b = _body()
    return _safe(prompt_svc.preview, pid, b.get("variables"), b.get("technique"))


@app.post("/api/prompts/<pid>/run")
def api_pe_run(pid):
    b = _body()
    return _safe(prompt_svc.run_prompt, pid, b.get("variables"),
                 b.get("technique"), bool(b.get("guard", False)))


# ============ 微调策略 ============
@app.get("/api/finetune/methods")
def api_ft_methods():
    return ok(finetune.list_methods())


@app.get("/api/finetune/methods/<key>")
def api_ft_method(key):
    return _safe(finetune.get_method, key)


@app.post("/api/finetune/command-preview")
def api_ft_cmd():
    b = _body()
    return _safe(finetune.command_preview, b.get("method", "sft"),
                 b.get("model_name", "Qwen2.5-7B"),
                 b.get("dataset_name", "my_dataset"),
                 b.get("source_path", ""))


@app.get("/api/finetune/runs")
def api_ft_runs():
    return _safe(finetune.list_finetune_runs, request.args.get("method"),
                 int(request.args.get("limit", 50)))


@app.post("/api/finetune/runs")
def api_ft_create():
    b = _body()
    return _safe(finetune.create_finetune_run,
                 b.get("name"), b.get("model_id"), b.get("dataset_id"),
                 b.get("method", "sft"), b.get("overrides"),
                 b.get("mode", "simulate"), b.get("description", ""))


# ============ 评测中心 ============
@app.get("/api/evalsets")
def api_ev_sets():
    return _safe(evalset.list_evalsets, request.args.get("keyword"),
                 int(request.args.get("page", 1)), int(request.args.get("size", 50)))


@app.post("/api/evalsets")
def api_ev_create():
    b = _body()
    return _safe(evalset.create_evalset, b.get("name"),
                 b.get("description", ""), b.get("cases"), b.get("tags"))


@app.get("/api/evalsets/<eid>")
def api_ev_get(eid):
    return _safe(evalset.get_evalset, eid)


@app.post("/api/evalsets/<eid>/cases")
def api_ev_cases(eid):
    return _safe(evalset.add_cases, eid, _body().get("cases", []))


@app.post("/api/evalsets/<eid>/import-dataset")
def api_ev_import(eid):
    b = _body()
    return _safe(evalset.import_from_dataset, eid, b.get("dataset_id"),
                 b.get("limit", 100))


@app.post("/api/evalsets/<eid>/run")
def api_ev_run(eid):
    b = _body()
    return _safe(evalset.run_evaluation, eid,
                 b.get("target_type", "sample"), b.get("target_id"),
                 b.get("variables"), bool(b.get("judge", False)),
                 b.get("name", ""), b.get("pass_threshold", 0.6))


@app.delete("/api/evalsets/<eid>")
def api_ev_delete(eid):
    return _safe(evalset.delete_evalset, eid)


@app.get("/api/evalruns")
def api_ev_runs():
    return _safe(evalset.list_runs, request.args.get("evalset_id"),
                 int(request.args.get("limit", 50)))


@app.post("/api/evalruns/compare")
def api_ev_compare():
    b = _body()
    return _safe(evalset.compare_runs, b.get("rid_a"), b.get("rid_b"))


@app.get("/api/evalruns/<rid>")
def api_ev_run_detail(rid):
    return _safe(evalset.get_run, rid)


# ============ 安全护栏 ============
@app.post("/api/guard/scan")
def api_gd_scan():
    b = _body()
    return _safe(guardrail.scan, b.get("text", ""),
                 bool(b.get("do_mask", True)), bool(b.get("block_injection", True)))


@app.post("/api/guard/init")
def api_gd_init():
    return _safe(guardrail.init_cases, bool(_body().get("force", False)))


@app.post("/api/guard/redteam")
def api_gd_redteam():
    return _safe(guardrail.run_redteam, _body().get("cases"))


@app.get("/api/guard/cases")
def api_gd_cases():
    return _safe(guardrail.list_cases, request.args.get("category"))


@app.post("/api/guard/cases")
def api_gd_add():
    b = _body()
    return _safe(guardrail.add_case, b.get("category"), b.get("text"),
                 b.get("expect", "block"))


@app.delete("/api/guard/cases/<cid>")
def api_gd_delete(cid):
    return _safe(guardrail.delete_case, cid)


# ============ 可观测性 ============
@app.get("/api/traces/summary")
def api_tr_summary():
    return _safe(trace.summary, int(request.args.get("days", 7)))


@app.get("/api/traces")
def api_tr_list():
    return _safe(trace.list_traces, request.args.get("kind"),
                 request.args.get("status"), int(request.args.get("limit", 50)))


@app.delete("/api/traces")
def api_tr_clear():
    return _safe(trace.clear)


# ============ RAG 进阶 / 完整采样参数 ============
@app.get("/api/vector/chunk-strategies")
def api_vec_strategies():
    return ok(vector.list_chunk_strategies())


@app.post("/api/vector/chunk")
def api_vec_chunk():
    b = _body()
    return _safe(vector.chunk_text, b.get("text", ""),
                 b.get("strategy", "recursive"), b.get("size", 400),
                 b.get("overlap", 50))


@app.post("/api/vector/hybrid-search")
def api_vec_hybrid():
    b = _body()
    return _safe(vector.hybrid_search, b.get("query", ""),
                 b.get("limit", 5), b.get("alpha", 0.5),
                 b.get("content_type"))


@app.post("/api/vector/rewrite")
def api_vec_rewrite():
    b = _body()
    return _safe(vector.rewrite_query, b.get("query", ""), b.get("n", 2))


@app.post("/api/rag/advanced")
def api_rag_advanced():
    b = _body()
    return _safe(vector.rag_chat_advanced, b.get("question", ""),
                 b.get("top_k", 5), b.get("strategy", "hybrid"),
                 bool(b.get("do_rewrite", False)),
                 bool(b.get("do_rerank", True)), b.get("history"))


@app.post("/api/llm/chat-full")
def api_llm_chat_full():
    b = _body()
    return _safe(llm.chat_full, b.get("messages", []),
                 b.get("params"), b.get("json_schema"))


if __name__ == "__main__":
    init_indexes()
    app.run(host="127.0.0.1", port=5000, debug=False)
