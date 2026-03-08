"""
统一日志工具
所有模块通过 get_logger(__name__) 获取 logger
日志同时输出到：控制台 + logs/YYYY-MM-DD.log
"""

import logging
import os
from datetime import datetime
from pathlib import Path


# 项目根目录（相对于本文件向上两级）
_ROOT = Path(__file__).parent.parent
_LOGS_DIR = _ROOT / "logs"


def get_logger(name: str, level: str = None) -> logging.Logger:
    """
    获取统一格式的 logger
    :param name: 模块名，通常传 __name__
    :param level: 日志级别，默认读环境变量 LOG_LEVEL，否则 INFO
    """
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    # 确定日志级别
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level, logging.INFO))

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 控制台 handler
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # 文件 handler（按天滚动，文件名：YYYY-MM-DD.log）
    log_file = _LOGS_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


def log_exception(logger: logging.Logger, msg: str, exc: Exception):
    """
    记录异常（含完整 traceback）
    用法：log_exception(logger, "任务失败", e)
    """
    logger.error(f"{msg} | {type(exc).__name__}: {exc}", exc_info=True)


def log_task_start(logger: logging.Logger, task_name: str, params: dict = None):
    """记录任务开始"""
    param_str = f" | 参数: {params}" if params else ""
    logger.info(f"▶ 任务开始: {task_name}{param_str}")


def log_task_end(logger: logging.Logger, task_name: str, success: bool, result: str = ""):
    """记录任务结束"""
    status = "✅ 成功" if success else "❌ 失败"
    result_str = f" | {result}" if result else ""
    logger.info(f"■ 任务结束: {task_name} → {status}{result_str}")


def log_human_required(logger: logging.Logger, action: str, reason: str):
    """
    记录需要人工介入的节点
    所有高风险/审核节点都应调用此函数
    """
    logger.warning(f"🙋 [人工节点] 需要人工操作: {action} | 原因: {reason}")


# ─────────────────────────────────────────────
# 快速测试
# ─────────────────────────────────────────────
if __name__ == "__main__":
    logger = get_logger("test")
    log_task_start(logger, "测试任务", {"key": "value"})
    logger.info("这是一条普通日志")
    logger.warning("这是一条警告")
    log_human_required(logger, "审核脚本内容", "脚本生成完毕，需人工核查合规性")
    log_task_end(logger, "测试任务", True, "共处理3条记录")
    print(f"\n日志文件：{_LOGS_DIR}/{datetime.now().strftime('%Y-%m-%d')}.log")
