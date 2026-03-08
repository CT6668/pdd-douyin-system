"""
数据库连接工具（后台专用）
"""

import sqlite3
import os
import json

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'data', 'db', 'main.db')


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # 支持 row['column_name'] 访问
    return conn


def query(sql, params=()):
    """执行 SELECT，返回 list[dict]"""
    conn = get_conn()
    try:
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_one(sql, params=()):
    """执行 SELECT，返回单条 dict 或 None"""
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql, params=()):
    """执行 INSERT / UPDATE / DELETE，返回 lastrowid"""
    conn = get_conn()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def json_parse(val, default=None):
    """安全解析 JSON 字符串"""
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return default
