"""
发布系统 DB 迁移脚本
新增：publish_queue / circuit_breaker_log / performance_data 字段补全
运行：python publish/init_publish_tables.py
"""

import sqlite3
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, 'data', 'db', 'main.db')


def get_conn():
    return sqlite3.connect(DB_PATH)


def column_exists(conn, table, column):
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def add_column_if_missing(conn, table, column, definition):
    if not column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        print(f"  + {table}.{column}")
    else:
        print(f"  ~ {table}.{column} 已存在，跳过")


def run():
    conn = get_conn()
    cur  = conn.cursor()
    print("=" * 60)
    print("发布系统 DB 迁移")
    print("=" * 60)

    # ──────────────────────────────────────────────────────────
    # 表1：待发布队列
    # ──────────────────────────────────────────────────────────
    print("\n[1] 创建 publish_queue 表...")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS publish_queue (
        id                INTEGER  PRIMARY KEY AUTOINCREMENT,
        content_task_id   INTEGER  NOT NULL REFERENCES content_tasks(id),
        product_id        INTEGER  NOT NULL REFERENCES product_pool(id),
        platform          TEXT     NOT NULL DEFAULT 'douyin',

        -- 计划发布时间
        scheduled_time    TEXT     NOT NULL,     -- YYYY-MM-DD HH:MM
        priority          INTEGER  DEFAULT 2,    -- 1高/2中/3低

        -- 发布前检查
        check_passed      INTEGER  DEFAULT 0,    -- 0=未检查 1=通过 2=有警告 3=未通过
        check_result      TEXT,                  -- JSON: 各维度检查详情
        checked_at        TEXT,

        -- 人工审批（必须）
        approved_by       TEXT,                  -- 审批人 MIS
        approved_at       TEXT,
        approval_note     TEXT,

        -- 风险识别
        risk_level        TEXT     DEFAULT 'none',  -- none/low/medium/high
        risk_flags        TEXT,                     -- JSON数组

        -- 熔断标记
        is_circuit_broken INTEGER  DEFAULT 0,    -- 0/1

        -- 发布状态机
        -- pending_check → checked → pending_approve → approved
        -- → publishing → published / failed / cancelled
        status            TEXT     DEFAULT 'pending_check',

        -- 执行结果
        publish_record_id INTEGER  REFERENCES publish_records(id),
        fail_reason       TEXT,
        fail_stage        TEXT,    -- check/approve/publish
        retry_count       INTEGER  DEFAULT 0,

        created_at        TEXT     DEFAULT (datetime('now','localtime')),
        updated_at        TEXT     DEFAULT (datetime('now','localtime'))
    )
    """)
    print("  ✅ publish_queue 表已就绪")

    # ──────────────────────────────────────────────────────────
    # 表2：熔断日志
    # ──────────────────────────────────────────────────────────
    print("\n[2] 创建 circuit_breaker_log 表...")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS circuit_breaker_log (
        id              INTEGER  PRIMARY KEY AUTOINCREMENT,
        level           TEXT     NOT NULL,  -- L1/L2/L3
        trigger_reason  TEXT     NOT NULL,  -- 触发原因描述
        trigger_detail  TEXT,               -- JSON详情（失败记录等）
        scope           TEXT,               -- 影响范围: queue_id/time_slot/global
        platform        TEXT,               -- 影响平台
        status          TEXT     DEFAULT 'active',  -- active/resolved
        resolved_by     TEXT,               -- 解除人
        resolved_at     TEXT,
        resolve_note    TEXT,               -- 解除原因
        created_at      TEXT     DEFAULT (datetime('now','localtime'))
    )
    """)
    print("  ✅ circuit_breaker_log 表已就绪")

    # ──────────────────────────────────────────────────────────
    # 表3：publish_records 字段补全
    # ──────────────────────────────────────────────────────────
    print("\n[3] 补全 publish_records 字段...")
    extras = [
        ('xhs_note_id',    'TEXT'),
        ('xhs_note_url',   'TEXT'),
        ('xhs_link_type',  'TEXT'),
        ('xhs_promo_url',  'TEXT'),
        ('actual_pub_time','TEXT'),     # 实际发布时间（区别于计划时间）
        ('pub_exception',  'TEXT'),     # 发布异常描述
        ('risk_hint',      'TEXT'),     # 风险提示（JSON）
    ]
    for col, defn in extras:
        add_column_if_missing(conn, 'publish_records', col, defn)

    # ──────────────────────────────────────────────────────────
    # 表4：performance_data 字段补全
    # ──────────────────────────────────────────────────────────
    print("\n[4] 补全 performance_data 字段...")
    perf_extras = [
        ('content_task_id',   'INTEGER'),
        ('platform',          'TEXT DEFAULT "douyin"'),
        ('completion_rate',   'REAL DEFAULT 0'),
        ('like_rate',         'REAL DEFAULT 0'),
        ('comment_rate',      'REAL DEFAULT 0'),
        ('product_ctr',       'REAL DEFAULT 0'),
        ('pub_exception',     'TEXT'),
        ('risk_hint',         'TEXT'),
        ('data_lag_hours',    'REAL DEFAULT 0'),
    ]
    for col, defn in perf_extras:
        add_column_if_missing(conn, 'performance_data', col, defn)

    # ──────────────────────────────────────────────────────────
    # 索引
    # ──────────────────────────────────────────────────────────
    print("\n[5] 创建索引...")
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_pq_status ON publish_queue(status)",
        "CREATE INDEX IF NOT EXISTS idx_pq_schedule ON publish_queue(scheduled_time)",
        "CREATE INDEX IF NOT EXISTS idx_pq_platform ON publish_queue(platform)",
        "CREATE INDEX IF NOT EXISTS idx_cb_status ON circuit_breaker_log(status)",
        "CREATE INDEX IF NOT EXISTS idx_perf_content ON performance_data(content_task_id)",
    ]
    for idx in indexes:
        cur.execute(idx)
    print("  ✅ 索引创建完成")

    conn.commit()
    conn.close()
    print("\n" + "=" * 60)
    print("✅ 所有迁移完成！")
    print("=" * 60)


if __name__ == '__main__':
    run()
