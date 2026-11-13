# -*- coding: utf-8 -*-
"""连接层：MongoDB 连接、业务库与训练库集合句柄。

AI 训练师工作台（AI Trainer Workbench）：
- 用户是「AI 训练师」，操作对象是「模型」。
- 核心能力：模型注册 / 参数调配 / 技能扩展 / 数据训练 / 评测追踪。

连接串支持通过环境变量 MONGO_URI 覆盖，默认连接本机 127.0.0.1:27017。
"""
import os

from pymongo import MongoClient
from pymongo.write_concern import WriteConcern

URI = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017")

client = MongoClient(URI, serverSelectionTimeoutMS=5000)

# ============ 业务库 trainer ============
biz = client["trainer"]

# 模型注册表：训练师管理的模型实例
models = biz.models
# 模型版本：训练产出的模型版本（版本号 / 来源训练 / 指标快照 / 状态 / 发布）
model_versions = biz.model_versions
# 模型参数配置：每个模型的核心超参数（learning rate / batch size / epochs / 温度 / top_p 等）
model_params = biz.model_params
# 模型技能：给模型增加的能力（skill），如「代码生成」「知识问答」「工具调用」等
skills = biz.skills
# 数据集：用于训练模型的数据
datasets = biz.datasets
# 知识库文档：注入给模型的知识（RAG / 知识增强）
documents = biz.documents
# 训练运行：一次训练任务的执行记录（配置快照 + 状态 + 指标）
training_runs = biz.training_runs
# 评测指标：训练/模型的表现度量
evaluations = biz.evaluations
# 向量索引：embedding 存储（向量数据库）
vector_index = biz.vector_index
# LLM 对话历史
llm_conversations = biz.llm_conversations

# ============ 工程能力（提示词 / 微调 / 评测 / 护栏 / 可观测） ============
# 提示词模板：名称、系统提示、正文、变量、few-shot 示例、技巧、采样参数
prompts = biz.prompts
# 提示词版本：每次修改生成快照，支持回溯与 A/B 对比
prompt_versions = biz.prompt_versions
# 黄金评测集：输入 + 预期输出 + 关键词，用于回归测试
evalsets = biz.evalsets
# 评测运行：一次批量评测的结果汇总与逐条明细
eval_runs = biz.eval_runs
# 红队测试用例：提示注入 / PII / 敏感内容样本
guardrail_tests = biz.guardrail_tests
# 调用追踪：模型调用耗时、token 估算、成本、状态
traces = biz.traces

# ============ 训练库 trainer_ai ============
ai = client["trainer_ai"]
# 训练样本：从数据集抽取、供训练使用的正/负样本
samples = ai.samples
# 特征与画像：模型/技能/数据集的衍生特征
features = ai.features
# 技能依赖边：技能之间的依赖关系
graph_edges = ai.graph_edges
# 实验元数据：训练实验记录
runs = ai.runs


def init_indexes():
    """建库后调用一次，确保索引存在（幂等）。"""
    # 模型：名称唯一 + 按类型/状态
    models.create_index([("name", 1)], name="uniq_model_name", unique=True)
    models.create_index([("model_type", 1), ("created_at", -1)], name="idx_model_type_time")
    models.create_index([("status", 1)], name="idx_model_status")

    # 模型版本：按模型 + 版本号唯一 + 按状态
    model_versions.create_index([("model_id", 1), ("version", 1)], name="uniq_model_version", unique=True)
    model_versions.create_index([("model_id", 1), ("created_at", -1)], name="idx_ver_model_time")
    model_versions.create_index([("status", 1)], name="idx_ver_status")

    # 模型参数：关联模型
    model_params.create_index([("model_id", 1), ("updated_at", -1)], name="idx_param_model_time")

    # 模型技能：名称唯一 + 按类别
    skills.create_index([("name", 1)], name="uniq_skill_name", unique=True)
    skills.create_index([("category", 1)], name="idx_skill_category")

    # 数据集：名称唯一 + 按类型/标签
    datasets.create_index([("name", 1)], name="uniq_dataset_name", unique=True)
    datasets.create_index([("dataset_type", 1), ("created_at", -1)], name="idx_ds_type_time")
    datasets.create_index([("tags", 1)], name="idx_ds_tags")

    # 知识库文档：关联模型 + 标题文本
    documents.create_index([("model_id", 1), ("created_at", -1)], name="idx_doc_model_time")
    documents.create_index([("title", "text"), ("content", "text")], name="idx_doc_text", default_language="none")

    # 训练运行：按模型 + 状态
    training_runs.create_index([("model_id", 1), ("created_at", -1)], name="idx_run_model_time")
    training_runs.create_index([("status", 1), ("created_at", -1)], name="idx_run_status")

    # 评测：按训练运行
    evaluations.create_index([("run_id", 1), ("metric", 1)], name="idx_eval_run_metric")

    # 向量索引：按来源 + 时间
    vector_index.create_index([("source_type", 1), ("source_id", 1)], name="idx_vec_source")
    vector_index.create_index([("created_at", -1)], name="idx_vec_time")
    vector_index.create_index([("content_type", 1)], name="idx_vec_content_type")

    # 对话历史：按会话 + 时间
    llm_conversations.create_index([("conversation_id", 1), ("created_at", -1)], name="idx_conv_time")

    # 提示词模板：名称唯一 + 技巧分类
    prompts.create_index([("name", 1)], name="uniq_prompt_name", unique=True)
    prompts.create_index([("technique", 1), ("created_at", -1)], name="idx_prompt_technique")
    prompt_versions.create_index([("prompt_id", 1), ("version", 1)],
                                 name="uniq_prompt_version", unique=True)

    # 评测：评测集名称唯一，运行按评测集 + 时间
    evalsets.create_index([("name", 1)], name="uniq_evalset_name", unique=True)
    eval_runs.create_index([("evalset_id", 1), ("created_at", -1)], name="idx_evalrun_set_time")

    # 护栏测试：按类别
    guardrail_tests.create_index([("category", 1)], name="idx_guard_category")

    # 可观测性：按时间 / 模型 / 状态
    traces.create_index([("created_at", -1)], name="idx_trace_time")
    traces.create_index([("model", 1), ("status", 1)], name="idx_trace_model_status")

    # 训练库
    samples.create_index([("model_id", 1), ("skill_id", 1)], name="uniq_model_skill", unique=True)
    samples.create_index([("label", 1), ("created_at", 1)], name="idx_label_time")
    graph_edges.create_index([("from_skill", 1), ("to_skill", 1)], name="uniq_edge", unique=True)
