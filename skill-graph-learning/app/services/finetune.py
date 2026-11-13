# -*- coding: utf-8 -*-
"""微调策略服务：方法库、专属超参模板、微调任务创建与训练命令生成。

覆盖主流模型定制方法：监督微调（SFT）、LoRA、QLoRA、全参数微调、
指令调优、DPO、RLHF、知识蒸馏。
每种方法带独立超参模板，可直接创建训练运行，或生成真实训练命令占位符。
"""
from datetime import datetime, timezone

from bson import ObjectId

from db import training_runs
from services import training


def _now():
    return datetime.now(timezone.utc)


METHODS = {
    "sft": {
        "name": "监督微调 SFT",
        "category": "标准微调",
        "description": "用带标签的「指令-回答」数据对更新模型权重，适配特定任务或领域。",
        "data_format": "instruction",
        "trainable": "全部参数",
        "task_type": "fine_tuning",
        "params": {
            "learning_rate": 2e-5, "batch_size": 8, "epochs": 3,
            "max_seq_length": 2048, "warmup_ratio": 0.03,
            "weight_decay": 0.01, "gradient_accumulation_steps": 1,
            "optimizer": "adamw", "lr_scheduler": "cosine",
        },
    },
    "lora": {
        "name": "LoRA 低秩适配",
        "category": "参数高效微调",
        "description": "冻结基座权重，仅训练低秩增量矩阵，显存占用低、可插拔多个适配器。",
        "data_format": "instruction",
        "trainable": "低秩适配器",
        "task_type": "lora",
        "params": {
            "learning_rate": 1e-4, "batch_size": 4, "epochs": 3,
            "lora_r": 16, "lora_alpha": 32, "lora_dropout": 0.05,
            "target_modules": ["q_proj", "v_proj"],
            "max_seq_length": 2048, "gradient_accumulation_steps": 4,
        },
    },
    "qlora": {
        "name": "QLoRA 量化微调",
        "category": "参数高效微调",
        "description": "在 4-bit 量化基座上做 LoRA，单卡即可微调大模型。",
        "data_format": "instruction",
        "trainable": "量化基座上的低秩适配器",
        "task_type": "lora",
        "params": {
            "learning_rate": 2e-4, "batch_size": 2, "epochs": 3,
            "lora_r": 64, "lora_alpha": 16, "lora_dropout": 0.05,
            "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"],
            "quant_bits": 4, "quant_type": "nf4", "double_quant": True,
            "compute_dtype": "bfloat16", "max_seq_length": 1024,
            "gradient_accumulation_steps": 8,
        },
    },
    "full": {
        "name": "全参数微调",
        "category": "标准微调",
        "description": "更新全部模型权重，效果上限高但算力与数据需求最大。",
        "data_format": "instruction",
        "trainable": "全部参数",
        "task_type": "fine_tuning",
        "params": {
            "learning_rate": 1e-5, "batch_size": 2, "epochs": 2,
            "max_seq_length": 1024, "warmup_ratio": 0.05,
            "gradient_checkpointing": True, "optimizer": "adamw",
            "deepspeed_stage": "zero3",
        },
    },
    "instruction": {
        "name": "指令调优",
        "category": "对齐微调",
        "description": "用多样化任务指令数据训练，提升模型遵循人类指令的能力。",
        "data_format": "instruction",
        "trainable": "全部参数",
        "task_type": "fine_tuning",
        "params": {
            "learning_rate": 2e-5, "batch_size": 16, "epochs": 2,
            "max_seq_length": 2048, "instruction_template": "alpaca",
            "warmup_ratio": 0.03, "num_instructions": 10000,
        },
    },
    "dpo": {
        "name": "DPO 直接偏好优化",
        "category": "偏好对齐",
        "description": "用「优选/拒绝」成对偏好数据直接优化策略，无需显式奖励模型。",
        "data_format": "preference",
        "trainable": "策略模型（含参考模型）",
        "task_type": "rlhf",
        "params": {
            "learning_rate": 5e-6, "batch_size": 2, "epochs": 1,
            "beta": 0.1, "max_length": 1024, "max_prompt_length": 512,
            "loss_type": "sigmoid", "reference_free": False,
        },
    },
    "rlhf": {
        "name": "RLHF 人类反馈强化学习",
        "category": "偏好对齐",
        "description": "训练奖励模型，再用 PPO 强化学习对齐人类偏好。",
        "data_format": "preference",
        "trainable": "策略模型 + 奖励模型",
        "task_type": "rlhf",
        "params": {
            "learning_rate": 1e-6, "batch_size": 4, "epochs": 1,
            "reward_model": "", "ppo_epochs": 1, "kl_coeff": 0.05,
            "clip_ratio": 0.2, "max_seq_length": 1024,
        },
    },
    "distill": {
        "name": "知识蒸馏",
        "category": "模型压缩",
        "description": "用教师模型的输出训练小模型，在保留能力的同时降低推理成本。",
        "data_format": "instruction",
        "trainable": "学生模型全部参数",
        "task_type": "fine_tuning",
        "params": {
            "learning_rate": 5e-5, "batch_size": 16, "epochs": 3,
            "teacher_model": "", "distill_temperature": 2.0,
            "alpha": 0.5, "max_seq_length": 1024,
        },
    },
}


def list_methods():
    """返回方法库（含默认超参）。"""
    out = []
    for key, m in METHODS.items():
        row = {k: v for k, v in m.items() if k != "params"}
        row["key"] = key
        row["params"] = dict(m["params"])
        out.append(row)
    return out


def get_method(key):
    if key not in METHODS:
        raise ValueError("不支持的微调方法：" + str(key))
    return METHODS[key]


def build_params(key, overrides=None):
    """方法默认超参 + 调用方覆盖。"""
    m = get_method(key)
    p = dict(m["params"])
    p.update(overrides or {})
    return p


def create_finetune_run(name, model_id, dataset_id, method="sft",
                        overrides=None, mode="simulate", description=""):
    """按指定方法创建微调训练运行，复用现有 training_runs 流程。

    额外写入 finetune_method / method_label / method_config，
    使异步训练、进度、指标、自动版本生成等既有能力全部可用。
    """
    m = get_method(method)
    params = build_params(method, overrides)
    rid = training.create_run(
        name=name, model_id=model_id, dataset_id=dataset_id,
        task_type=m["task_type"], params=params,
        description=description or ("%s 微调任务" % m["name"]),
        mode=mode,
    )
    training_runs.update_one(
        {"_id": ObjectId(rid)},
        {"$set": {
            "finetune_method": method,
            "method_label": m["name"],
            "method_category": m["category"],
            "method_config": params,
            "data_format": m["data_format"],
            "updated_at": _now(),
        }})
    return rid


def list_finetune_runs(method=None, limit=50):
    """列出由微调策略创建的训练运行。"""
    cond = {"finetune_method": {"$exists": True}}
    if method:
        cond["finetune_method"] = method
    rows = []
    for r in training_runs.find(cond).sort("created_at", -1).limit(int(limit)):
        r["_id"] = str(r["_id"])
        r["model_id"] = str(r["model_id"]) if r.get("model_id") else None
        r["dataset_id"] = str(r["dataset_id"]) if r.get("dataset_id") else None
        rows.append(r)
    return rows


def command_preview(method="sft", model_name="Qwen2.5-7B",
                    dataset_name="my_dataset", source_path=""):
    """生成可复制的真实训练命令模板（llama-factory / trl 风格）。

    占位符与 TRAIN_CMD 一致：{model} {source_path} {dataset} {params_json}，
    另新增 {method} {method_params_json}，便于直接对接本地训练框架。
    """
    m = get_method(method)
    p = m["params"]

    # 只替换本方法自己的超参占位符；{source_path}/{dataset}/{method} 等业务占位符
    # 原样保留，供 TRAIN_CMD 在真实训练时注入。
    def _fill(tpl, mapping):
        for k, v in mapping.items():
            tpl = tpl.replace("{" + k + "}", str(v))
        return tpl

    common = ("--model_name_or_path \"{source_path}\" "
              "--dataset \"{dataset}\" --output_dir ./output/{method} "
              "--learning_rate {lr} --num_train_epochs {ep} "
              "--per_device_train_batch_size {bs}")

    if method in ("lora", "qlora"):
        cmd = ("llamafactory-cli train --stage sft --do_train True "
               "--finetuning_type lora --lora_rank {r} --lora_alpha {alpha} "
               "--lora_dropout {drop} --lora_target {targets} " + common)
        if method == "qlora":
            cmd += " --quantization_bit {bits} --quantization_type {qtype}"
        cmd = _fill(cmd, {
            "r": p["lora_r"], "alpha": p["lora_alpha"], "drop": p["lora_dropout"],
            "targets": ",".join(p["target_modules"]),
            "bits": p.get("quant_bits", 4), "qtype": p.get("quant_type", "nf4"),
            "lr": p["learning_rate"], "ep": p["epochs"], "bs": p["batch_size"],
        })
    elif method == "dpo":
        cmd = ("trl dpo --model_name_or_path \"{source_path}\" --dataset \"{dataset}\" "
               "--beta {beta} --learning_rate {lr} --num_train_epochs {ep} "
               "--output_dir ./output/dpo")
        cmd = _fill(cmd, {"beta": p["beta"], "lr": p["learning_rate"], "ep": p["epochs"]})
    elif method == "rlhf":
        cmd = ("# 阶段 1：训练奖励模型\n"
               "trl reward-modeling --model_name_or_path \"{source_path}\" "
               "--dataset \"{dataset}\" --output_dir ./output/reward\n"
               "# 阶段 2：PPO 策略优化\n"
               "trl ppo --model_name_or_path \"{source_path}\" "
               "--reward_model ./output/reward --kl_coef {kl} "
               "--learning_rate {lr} --output_dir ./output/ppo")
        cmd = _fill(cmd, {"kl": p["kl_coeff"], "lr": p["learning_rate"]})
    else:
        cmd = ("llamafactory-cli train --stage sft --do_train True "
               "--finetuning_type full " + common)
        cmd = _fill(cmd, {"lr": p["learning_rate"], "ep": p["epochs"], "bs": p["batch_size"]})

    return {
        "method": method,
        "method_label": m["name"],
        "command": cmd,
        "placeholders": ["{model}", "{source_path}", "{dataset}",
                         "{params_json}", "{method}", "{method_params_json}"],
        "params": dict(p),
        "note": "示例命令，实际使用请按本地训练框架调整；可在环境变量 TRAIN_CMD 中配置。",
    }
