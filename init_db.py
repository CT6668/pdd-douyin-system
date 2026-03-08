"""
完整数据库初始化脚本
包含：核心业务表 + 发布系统表 + 测试数据
运行：python init_db.py
"""

import sqlite3
import os
import json
from datetime import datetime, timedelta
import random

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(ROOT, 'data', 'db')
DB_PATH = os.path.join(DB_DIR, 'main.db')

os.makedirs(DB_DIR, exist_ok=True)


def get_conn():
    return sqlite3.connect(DB_PATH)


def create_core_tables(conn):
    cur = conn.cursor()
    print("\n[1] 创建核心业务表...")

    # 商品池
    cur.execute("""
    CREATE TABLE IF NOT EXISTS product_pool (
        id              INTEGER  PRIMARY KEY AUTOINCREMENT,
        pdd_product_id  TEXT     UNIQUE,
        title           TEXT     NOT NULL,
        category        TEXT,
        sub_category    TEXT,
        price           REAL     DEFAULT 0,
        commission_rate REAL     DEFAULT 0,
        sales_30d       INTEGER  DEFAULT 0,
        rating          REAL     DEFAULT 0,
        stock_status    TEXT     DEFAULT 'sufficient',
        product_url     TEXT,
        image_url       TEXT,
        status          TEXT     DEFAULT 'active',
        created_at      TEXT     DEFAULT (datetime('now','localtime')),
        updated_at      TEXT     DEFAULT (datetime('now','localtime'))
    )
    """)

    # 商品评分卡
    cur.execute("""
    CREATE TABLE IF NOT EXISTS product_scorecards (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id          INTEGER NOT NULL REFERENCES product_pool(id),
        score_date          TEXT    NOT NULL,
        total_score         REAL    DEFAULT 0,
        price_score         REAL    DEFAULT 0,
        commission_score    REAL    DEFAULT 0,
        sales_score         REAL    DEFAULT 0,
        rating_score        REAL    DEFAULT 0,
        trend_score         REAL    DEFAULT 0,
        stock_score         REAL    DEFAULT 0,
        competition_score   REAL    DEFAULT 0,
        seasonal_score      REAL    DEFAULT 0,
        visual_score        REAL    DEFAULT 0,
        review_score        REAL    DEFAULT 0,
        platform_score      REAL    DEFAULT 0,
        margin_score        REAL    DEFAULT 0,
        score_detail        TEXT,
        created_at          TEXT    DEFAULT (datetime('now','localtime'))
    )
    """)

    # 类目热度
    cur.execute("""
    CREATE TABLE IF NOT EXISTS category_stats (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        category        TEXT    NOT NULL,
        stat_date       TEXT    NOT NULL,
        heat_score      REAL    DEFAULT 0,
        product_count   INTEGER DEFAULT 0,
        avg_commission  REAL    DEFAULT 0,
        trend           TEXT    DEFAULT 'stable',
        note            TEXT,
        created_at      TEXT    DEFAULT (datetime('now','localtime')),
        UNIQUE(category, stat_date)
    )
    """)

    # 内容任务
    cur.execute("""
    CREATE TABLE IF NOT EXISTS content_tasks (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id          INTEGER NOT NULL REFERENCES product_pool(id),
        content_type        TEXT    DEFAULT 'douyin',
        script_type         TEXT    DEFAULT 'review',
        title               TEXT,
        douyin_script       TEXT,
        douyin_hooks        TEXT,
        xhs_body            TEXT,
        xhs_hashtags        TEXT,
        cover_suggestion    TEXT,
        publish_time_suggest TEXT,
        status              TEXT    DEFAULT 'draft',
        review_status       TEXT    DEFAULT 'pending',
        reviewer            TEXT,
        review_note         TEXT,
        created_at          TEXT    DEFAULT (datetime('now','localtime')),
        updated_at          TEXT    DEFAULT (datetime('now','localtime'))
    )
    """)

    # 素材渲染任务
    cur.execute("""
    CREATE TABLE IF NOT EXISTS material_render_tasks (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        content_task_id INTEGER REFERENCES content_tasks(id),
        product_id      INTEGER REFERENCES product_pool(id),
        asset_type      TEXT    DEFAULT 'cover',
        source_key_point TEXT,
        render_status   TEXT    DEFAULT 'pending',
        output_path     TEXT,
        created_at      TEXT    DEFAULT (datetime('now','localtime')),
        updated_at      TEXT    DEFAULT (datetime('now','localtime'))
    )
    """)

    # 发布记录
    cur.execute("""
    CREATE TABLE IF NOT EXISTS publish_records (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        content_task_id INTEGER REFERENCES content_tasks(id),
        product_id      INTEGER REFERENCES product_pool(id),
        platform        TEXT    DEFAULT 'douyin',
        platform_id     TEXT,
        platform_url    TEXT,
        publish_time    TEXT,
        actual_pub_time TEXT,
        pub_exception   TEXT,
        risk_hint       TEXT,
        xhs_note_id     TEXT,
        xhs_note_url    TEXT,
        xhs_link_type   TEXT,
        xhs_promo_url   TEXT,
        status          TEXT    DEFAULT 'pending',
        created_at      TEXT    DEFAULT (datetime('now','localtime'))
    )
    """)

    # 数据回传
    cur.execute("""
    CREATE TABLE IF NOT EXISTS performance_data (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        publish_record_id INTEGER REFERENCES publish_records(id),
        content_task_id INTEGER REFERENCES content_tasks(id),
        product_id      INTEGER REFERENCES product_pool(id),
        platform        TEXT    DEFAULT 'douyin',
        stat_date       TEXT    NOT NULL,
        impressions     INTEGER DEFAULT 0,
        plays           INTEGER DEFAULT 0,
        likes           INTEGER DEFAULT 0,
        comments        INTEGER DEFAULT 0,
        shares          INTEGER DEFAULT 0,
        product_clicks  INTEGER DEFAULT 0,
        orders          INTEGER DEFAULT 0,
        revenue         REAL    DEFAULT 0,
        commission      REAL    DEFAULT 0,
        completion_rate REAL    DEFAULT 0,
        like_rate       REAL    DEFAULT 0,
        comment_rate    REAL    DEFAULT 0,
        product_ctr     REAL    DEFAULT 0,
        pub_exception   TEXT,
        risk_hint       TEXT,
        data_lag_hours  REAL    DEFAULT 0,
        created_at      TEXT    DEFAULT (datetime('now','localtime')),
        updated_at      TEXT    DEFAULT (datetime('now','localtime'))
    )
    """)

    # 复盘洞察
    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_insights (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        insight_date    TEXT    NOT NULL UNIQUE,
        best_product_id INTEGER REFERENCES product_pool(id),
        summary         TEXT,
        key_findings    TEXT,
        tomorrow_suggest TEXT,
        saved_by        TEXT,
        created_at      TEXT    DEFAULT (datetime('now','localtime'))
    )
    """)

    # 发布队列
    cur.execute("""
    CREATE TABLE IF NOT EXISTS publish_queue (
        id                INTEGER  PRIMARY KEY AUTOINCREMENT,
        content_task_id   INTEGER  NOT NULL REFERENCES content_tasks(id),
        product_id        INTEGER  NOT NULL REFERENCES product_pool(id),
        platform          TEXT     NOT NULL DEFAULT 'douyin',
        scheduled_time    TEXT     NOT NULL,
        priority          INTEGER  DEFAULT 2,
        check_passed      INTEGER  DEFAULT 0,
        check_result      TEXT,
        checked_at        TEXT,
        approved_by       TEXT,
        approved_at       TEXT,
        approval_note     TEXT,
        risk_level        TEXT     DEFAULT 'none',
        risk_flags        TEXT,
        is_circuit_broken INTEGER  DEFAULT 0,
        status            TEXT     DEFAULT 'pending_check',
        publish_record_id INTEGER  REFERENCES publish_records(id),
        fail_reason       TEXT,
        fail_stage        TEXT,
        retry_count       INTEGER  DEFAULT 0,
        created_at        TEXT     DEFAULT (datetime('now','localtime')),
        updated_at        TEXT     DEFAULT (datetime('now','localtime'))
    )
    """)

    # 熔断日志
    cur.execute("""
    CREATE TABLE IF NOT EXISTS circuit_breaker_log (
        id              INTEGER  PRIMARY KEY AUTOINCREMENT,
        level           TEXT     NOT NULL,
        trigger_reason  TEXT     NOT NULL,
        trigger_detail  TEXT,
        scope           TEXT,
        platform        TEXT,
        status          TEXT     DEFAULT 'active',
        resolved_by     TEXT,
        resolved_at     TEXT,
        resolve_note    TEXT,
        created_at      TEXT     DEFAULT (datetime('now','localtime'))
    )
    """)

    conn.commit()

    # 索引（commit后再建，避免找不到列）
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_product_category ON product_pool(category)",
        "CREATE INDEX IF NOT EXISTS idx_score_product ON product_scorecards(product_id, score_date)",
        "CREATE INDEX IF NOT EXISTS idx_content_product ON content_tasks(product_id)",
        "CREATE INDEX IF NOT EXISTS idx_perf_date ON performance_data(stat_date)",
        "CREATE INDEX IF NOT EXISTS idx_pq_status ON publish_queue(status)",
        "CREATE INDEX IF NOT EXISTS idx_cb_status ON circuit_breaker_log(status)",
    ]
    for idx in indexes:
        cur.execute(idx)
    conn.commit()

    print("  ✅ 核心表创建完成")


def insert_test_data(conn):
    cur = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

    print("\n[2] 插入测试数据...")

    # ── 商品数据 ──────────────────────────────────────────
    products = [
        ('PDD001', '【爆款】无线蓝牙耳机 主动降噪 超长续航', '3C数码', '耳机', 129.9, 0.15, 8920, 4.8),
        ('PDD002', '便携式颈部按摩仪 智能热敷 USB充电', '健康护理', '按摩仪', 189.0, 0.18, 5640, 4.7),
        ('PDD003', '网红美妆刷套装 专业化妆工具 20支', '美妆', '化妆工具', 59.9, 0.22, 12300, 4.9),
        ('PDD004', '智能保温杯 316不锈钢 真空保温12h', '家居', '杯子', 89.0, 0.12, 7800, 4.6),
        ('PDD005', '韩国进口面膜 补水保湿 30片/盒', '美妆', '护肤', 79.0, 0.25, 15600, 4.8),
        ('PDD006', '儿童益智积木 安全无毒 200+颗粒', '母婴', '玩具', 69.9, 0.20, 4200, 4.7),
        ('PDD007', '运动跳绳 专业竞速 钢丝绳', '运动户外', '跳绳', 39.9, 0.28, 9800, 4.9),
        ('PDD008', '厨房多功能切菜器 不锈钢刀片', '家居', '厨具', 49.9, 0.30, 11200, 4.7),
        ('PDD009', '宠物自动饮水机 循环过滤 USB', '宠物', '饮水机', 99.0, 0.16, 3600, 4.5),
        ('PDD010', '桌面收纳盒 简约北欧风 带抽屉', '家居', '收纳', 45.0, 0.24, 6700, 4.6),
    ]

    product_ids = []
    for p in products:
        cur.execute("""
        INSERT OR IGNORE INTO product_pool
        (pdd_product_id, title, category, sub_category, price, commission_rate,
         sales_30d, rating, product_url, image_url, status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7],
              f'https://mobile.yangkeduo.com/goods.html?goods_id={p[0]}',
              f'https://img.example.com/{p[0]}.jpg',
              'active'))
        row = cur.execute("SELECT id FROM product_pool WHERE pdd_product_id=?", (p[0],)).fetchone()
        product_ids.append(row[0])

    print(f"  ✅ 插入 {len(products)} 个商品")

    # ── 评分卡 ──────────────────────────────────────────────
    scores_base = [88.5, 82.3, 91.2, 76.8, 94.1, 71.5, 85.6, 79.3, 68.9, 77.4]
    for i, pid in enumerate(product_ids):
        total = scores_base[i]
        detail = {
            "维度": ["价格竞争力", "佣金", "销量", "评分", "趋势", "库存", "竞争度", "季节性", "视觉", "评论质量", "平台支持", "毛利"],
            "得分": [round(total + random.uniform(-10, 10), 1) for _ in range(12)]
        }
        cur.execute("""
        INSERT OR IGNORE INTO product_scorecards
        (product_id, score_date, total_score, price_score, commission_score,
         sales_score, rating_score, trend_score, stock_score, competition_score,
         seasonal_score, visual_score, review_score, platform_score, margin_score,
         score_detail)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (pid, today, total,
              round(total + random.uniform(-8, 8), 1),
              round(total + random.uniform(-8, 8), 1),
              round(total + random.uniform(-8, 8), 1),
              round(total + random.uniform(-8, 8), 1),
              round(total + random.uniform(-8, 8), 1),
              round(total + random.uniform(-8, 8), 1),
              round(total + random.uniform(-8, 8), 1),
              round(total + random.uniform(-8, 8), 1),
              round(total + random.uniform(-8, 8), 1),
              round(total + random.uniform(-8, 8), 1),
              round(total + random.uniform(-8, 8), 1),
              round(total + random.uniform(-8, 8), 1),
              json.dumps(detail, ensure_ascii=False)))

    print(f"  ✅ 插入 {len(product_ids)} 条评分卡")

    # ── 类目热度 ──────────────────────────────────────────
    categories = [
        ('美妆', 92.3, 28, 0.235, 'rising'),
        ('3C数码', 87.5, 15, 0.168, 'stable'),
        ('健康护理', 85.1, 22, 0.192, 'rising'),
        ('家居', 78.4, 35, 0.198, 'stable'),
        ('运动户外', 83.6, 18, 0.255, 'rising'),
        ('母婴', 71.2, 12, 0.215, 'stable'),
        ('宠物', 76.8, 14, 0.172, 'rising'),
    ]
    for c in categories:
        cur.execute("""
        INSERT OR REPLACE INTO category_stats
        (category, stat_date, heat_score, product_count, avg_commission, trend)
        VALUES (?,?,?,?,?,?)
        """, (c[0], today, c[1], c[2], c[3], c[4]))

    print(f"  ✅ 插入 {len(categories)} 个类目热度")

    # ── 内容脚本 ──────────────────────────────────────────
    script_templates = [
        {
            'type': 'review',
            'douyin': '【开箱测评】买了{title}，真的值{price}吗？\n\n第一幕：开箱展示，外观惊艳\n第二幕：实测对比，效果炸裂\n第三幕：真实反馈，这几点要注意\n\n#开箱 #{category}好物 #测评',
            'xhs': '姐妹们！这个{title}真的绝了 ✨\n\n入手{price}元，佣金{commission}%，来来来看看值不值！\n\n👍 优点：\n• 品质超出预期\n• 性价比极高\n• 到货很快\n\n❌ 缺点：\n• 包装一般\n\n总体来说非常推荐！喜欢的姐妹点个收藏💕\n\n#{category} #好物分享 #种草'
        },
        {
            'type': 'tutorial',
            'douyin': '【教程干货】{title}怎么用效果最好？老用户手把手教你！\n\n第一步：…\n第二步：…\n第三步：…\n\n记得点赞收藏！\n\n#{category}教程 #使用技巧',
            'xhs': '分享一个超实用的{title}使用教程！\n\n很多人买了不会用，今天教大家正确方法👇\n\nStep 1：准备工作\nStep 2：正确操作\nStep 3：效果展示\n\n学会了的点个❤️\n\n#使用教程 #{category}'
        },
        {
            'type': 'problem_solution',
            'douyin': '【解决痛点】一直找不到好用的{sub_category}？这个{title}真的太香了！\n\n#好物推荐 #{category}',
            'xhs': '终于找到了！解决了我{sub_category}的大难题 🎉\n\n{title}\n\n之前试过好多款都不满意，这个真的不一样！\n\n大家有同款需求的可以入手～\n\n#{category}好物 #解决痛点'
        }
    ]

    content_ids = []
    for i, pid in enumerate(product_ids[:6]):  # 前6个商品生成内容
        p_info = products[i]
        tmpl = script_templates[i % len(script_templates)]
        douyin_script = tmpl['douyin'].format(
            title=p_info[1][:15],
            price=p_info[4],
            category=p_info[2],
            sub_category=p_info[3],
            commission=int(p_info[5]*100)
        )
        xhs_body = tmpl['xhs'].format(
            title=p_info[1][:15],
            price=p_info[4],
            category=p_info[2],
            sub_category=p_info[3],
            commission=int(p_info[5]*100)
        )

        status = ['approved', 'approved', 'pending_review', 'approved', 'pending_review', 'draft'][i]
        cur.execute("""
        INSERT INTO content_tasks
        (product_id, content_type, script_type, title, douyin_script, douyin_hooks,
         xhs_body, xhs_hashtags, cover_suggestion, publish_time_suggest, status, review_status)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (pid, 'douyin', tmpl['type'],
              f'{p_info[1][:20]} - {tmpl["type"]}脚本',
              douyin_script,
              json.dumps(['钩子1：引发好奇', '钩子2：痛点共鸣', '钩子3：惊喜转折'], ensure_ascii=False),
              xhs_body,
              json.dumps([f'#{p_info[2]}', '#好物分享', '#种草', '#测评'], ensure_ascii=False),
              f'主图：{p_info[1][:10]}，文案：真的值了！',
              f'{today} 18:00' if i % 2 == 0 else f'{today} 20:00',
              status,
              'approved' if status == 'approved' else 'pending'))
        content_ids.append(cur.lastrowid)

    print(f"  ✅ 插入 {len(content_ids)} 条内容脚本")

    # ── 素材任务（部分已完成）─────────────────────────────
    for i, (cid, pid) in enumerate(zip(content_ids[:4], product_ids[:4])):
        render_status = ['done', 'done', 'processing', 'pending'][i]
        cur.execute("""
        INSERT INTO material_render_tasks
        (content_task_id, product_id, asset_type, source_key_point, render_status, output_path)
        VALUES (?,?,?,?,?,?)
        """, (cid, pid, 'cover',
              f'核心卖点：{products[i][3]}好物，价格实惠',
              render_status,
              f'/materials/output/cover_{cid}.jpg' if render_status == 'done' else None))

    print(f"  ✅ 插入素材任务")

    # ── 发布记录（昨日数据）──────────────────────────────
    pub_record_ids = []
    for i, (cid, pid) in enumerate(zip(content_ids[:4], product_ids[:4])):
        cur.execute("""
        INSERT INTO publish_records
        (content_task_id, product_id, platform, platform_url,
         publish_time, actual_pub_time, status)
        VALUES (?,?,?,?,?,?,?)
        """, (cid, pid, 'douyin',
              f'https://www.douyin.com/video/00{i+1}000',
              f'{yesterday} {18+i*2}:00:00',
              f'{yesterday} {18+i*2}:02:00',
              'published'))
        pub_record_ids.append(cur.lastrowid)

    print(f"  ✅ 插入 {len(pub_record_ids)} 条发布记录")

    # ── 数据回传（昨日绩效）─────────────────────────────
    perf_data = [
        (45000, 28000, 1890, 234, 156, 890, 67, 5983, 897),
        (32000, 18000, 1230, 189, 98, 560, 43, 3870, 697),
        (28000, 22000, 980, 145, 87, 420, 31, 1860, 465),
        (19000, 12000, 560, 89, 45, 280, 18, 1602, 192),
    ]
    for i, (rid, pid, cid) in enumerate(zip(pub_record_ids, product_ids[:4], content_ids[:4])):
        d = perf_data[i]
        impressions, plays = d[0], d[1]
        likes, comments, shares = d[2], d[3], d[4]
        product_clicks, orders, revenue, commission = d[5], d[6], d[7], d[8]
        cur.execute("""
        INSERT INTO performance_data
        (publish_record_id, content_task_id, product_id, platform, stat_date,
         impressions, plays, likes, comments, shares,
         product_clicks, orders, revenue, commission,
         completion_rate, like_rate, comment_rate, product_ctr)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (rid, cid, pid, 'douyin', yesterday,
              impressions, plays, likes, comments, shares,
              product_clicks, orders, revenue, commission,
              round(plays/impressions, 3),
              round(likes/plays, 3),
              round(comments/plays, 3),
              round(product_clicks/plays, 3)))

    print(f"  ✅ 插入 {len(perf_data)} 条绩效数据")

    # ── 发布队列（今日待发布）──────────────────────────
    queue_data = [
        (content_ids[0], product_ids[0], 'douyin', f'{today} 18:00', 1, 'approved', 'none'),
        (content_ids[1], product_ids[1], 'douyin', f'{today} 20:00', 2, 'pending_approve', 'low'),
        (content_ids[3], product_ids[3], 'xhs',    f'{today} 19:00', 2, 'checked', 'none'),
    ]
    for q in queue_data:
        check_result = json.dumps({
            "checks": [
                {"name": "脚本完整性", "passed": True},
                {"name": "素材就绪", "passed": True},
                {"name": "无违禁词", "passed": True},
                {"name": "发布时间合理", "passed": True},
                {"name": "商品库存充足", "passed": True}
            ],
            "warnings": [],
            "risk_flags": []
        }, ensure_ascii=False)

        cur.execute("""
        INSERT INTO publish_queue
        (content_task_id, product_id, platform, scheduled_time, priority,
         status, risk_level, check_passed, check_result, checked_at,
         approved_by, approved_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (q[0], q[1], q[2], q[3], q[4],
              q[5], q[6],
              1, check_result, datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
              'chentao' if q[5] == 'approved' else None,
              datetime.now().strftime('%Y-%m-%d %H:%M:%S') if q[5] == 'approved' else None))

    print(f"  ✅ 插入 {len(queue_data)} 条发布队列")

    # ── 复盘洞察 ────────────────────────────────────────
    cur.execute("""
    INSERT OR IGNORE INTO daily_insights
    (insight_date, best_product_id, summary, key_findings, tomorrow_suggest, saved_by)
    VALUES (?,?,?,?,?,?)
    """, (yesterday, product_ids[0],
          '昨日发布4条内容，总曝光12.4万，最佳商品为蓝牙耳机（佣金897元）',
          json.dumps([
              '美妆类内容完播率最高，平均72%',
              '18:00发布时段比20:00曝光多35%',
              '测评类脚本比教程类点击率高22%'
          ], ensure_ascii=False),
          json.dumps([
              '明日重点推健康护理类目，热度上升中',
              '优先使用测评类脚本框架',
              '安排18:00黄金时段发布2条内容'
          ], ensure_ascii=False),
          'chentao'))

    print(f"  ✅ 插入昨日复盘洞察")

    conn.commit()
    print("\n  ✅ 全部测试数据插入完成！")


if __name__ == '__main__':
    print("=" * 60)
    print("PDD带货运营系统 - 数据库初始化")
    print("=" * 60)
    print(f"DB路径: {DB_PATH}")

    conn = get_conn()
    create_core_tables(conn)
    insert_test_data(conn)
    conn.close()

    # 验证
    conn = sqlite3.connect(DB_PATH)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    print(f"\n✅ 已创建 {len(tables)} 张表：{[t[0] for t in tables]}")
    conn.close()

    print("\n" + "=" * 60)
    print("✅ 数据库初始化完成！")
    print("=" * 60)
