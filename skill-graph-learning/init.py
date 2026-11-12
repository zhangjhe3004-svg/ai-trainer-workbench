# -*- coding: utf-8 -*-
"""一键初始化：建库、建索引、造演示数据。

用法：python init.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))

from db import init_indexes, client


def main():
    print("正在初始化 AI 训练师工作台...")
    # 清空旧数据，保证幂等（可选：注释掉则保留已有数据）
    print("[0/3] 清理旧数据...")
    client.drop_database("trainer")
    client.drop_database("trainer_ai")
    client.drop_database("learning")      # 兼容清理旧版学习系统库
    client.drop_database("learning_ai")

    # 建索引（幂等）
    init_indexes()
    print("[1/3] 索引初始化完成")

    # 造演示数据
    import subprocess
    data_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "generate_data.py")
    subprocess.run([sys.executable, data_script,
                    "--models", "6", "--skills", "20",
                    "--datasets", "8", "--documents", "30", "--runs", "12"], check=True)
    print("[2/3] 演示数据生成完成")

    print("[3/3] 初始化完成！")
    print()
    print("下一步：")
    print("  网页界面：cd app && python app.py  （浏览器访问 http://127.0.0.1:5000/）")
    print("  命令行：  cd app && python cli.py")


if __name__ == "__main__":
    main()
