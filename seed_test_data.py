"""
测试数据填充脚本（基于实际表结构）
运行：python seed_test_data.py
"""

import sqlite3
import os
import json
from datetime import datetime, timedelta
import random

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, 'data', 'db', 'main.db')

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

today = datetime.now().strftime('%Y-%m-%d')
yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
print(f"今日: {today}  昨日: {yesterday}")
print("=" * 60)


# ── 1. 检查并插入商品 ─────────────────────────────────────
print("\n[1] 商品数据...")
existing = cur.execute("SELECT COUNT(*) FROM product_pool").fetchone()[0]
print(f"  现有 {existing} 条商品")

if existing < 5:
    products = [
        ('9001234', '【爆款】无线蓝牙耳机 主动降噪 超长续航30h', '3C数码', '耳机', 129.9, 0.15, 8920, 4.8),
        ('9001235', '便携式颈部按摩仪 智能热敷 USB充电', '健康护理', '按摩仪', 189.0, 0.18, 5640, 4.7),
        ('9001236', '网红美妆刷套装 专业化妆工具 20支装', '美妆', '化妆工具', 59.9, 0.22, 12300, 4.9),
        ('9001237', '智能保温杯 316不锈钢 真空保温12h', '家居', '杯子', 89.0, 0.12, 7800, 4.6),
        ('9001238', '韩国进口面膜 补水保湿 30片/盒', '美妆', '护肤', 79.0, 0.25, 15600, 4.8),
        ('9001239', '儿童益智积木 安全无毒 200+颗粒', '母婴', '玩具', 69.9, 0.20, 4200, 4.7),
        ('9001240', '运动跳绳 专业竞速 钢丝绳', '运动户外', '跳绳', 39.9, 0.28, 9800, 4.9),
        ('9001241', '厨房多功能切菜器 不锈钢刀片组合', '家居', '厨具', 49.9, 0.30, 11200, 4.7),
        ('9001242', '宠物自动饮水机 循环过滤 USB供电', '宠物', '饮水机', 99.0, 0.16, 3600, 4.5),
        ('9001243', '桌面收纳盒 简约北欧风 带抽屉设计', '家居', '收纳', 45.0, 0.24, 6700, 4.6),
    ]
    for p in products:
        cur.execute("""
        INSERT OR IGNORE INTO product_pool
        (pdd_goods_id, title, category_l1, category_l2, price, commission_rate,
         sales_30d, rating, pdd_url, cover_img, status, add_date)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7],
              f'https://mobile.yangkeduo.com/goods.html?goods_id={p[0]}',
              f'https://img.example.com/{p[0]}.jpg',
              'active', today))
    conn.commit()
    print(f"  ✅ 插入 {len(products)} 个商品")
else:
    print("  ✅ 商品数据已存在，跳过")


# 获取商品ID
product_ids = [r[0] for r in cur.execute(
    "SELECT id FROM product_pool ORDER BY id LIMIT 10").fetchall()]
products_info = [dict(r) for r in cur.execute(
    "SELECT * FROM product_pool ORDER BY id LIMIT 10").fetchall()]
print(f"  使用商品IDs: {product_ids}")


# ── 2. 商品评分 ─────────────────────────────────────────
print("\n[2] 评分数据...")
existing = cur.execute("SELECT COUNT(*) FROM product_scores WHERE score_date=?", (today,)).fetchone()[0]
if existing < 5:
    scores_base = [88.5, 82.3, 91.2, 76.8, 94.1, 71.5, 85.6, 79.3, 68.9, 77.4]
    for i, pid in enumerate(product_ids):
        t = scores_base[i % len(scores_base)]
        def rnd(base): return round(base + random.uniform(-12, 12), 1)
        cur.execute("""
        INSERT OR IGNORE INTO product_scores
        (product_id, score_date, s01_pdd_heat, s02_growth_7d, s03_trend_30d,
         s04_douyin_fit, s05_visual_strength, s06_low_explain, s07_low_decision,
         s08_impulse_price, s09_commission_val, s10_competition, s11_supply_stable,
         s12_compliance_risk, s13_refund_risk, total_score, score_version, is_selected)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (pid, today, rnd(t), rnd(t), rnd(t), rnd(t), rnd(t), rnd(t), rnd(t),
              rnd(t), rnd(t), rnd(t), rnd(t), rnd(t), rnd(t),
              t, 'v1.0', 1 if t > 80 else 0))
    conn.commit()
    print(f"  ✅ 插入 {len(product_ids)} 条评分")
else:
    print(f"  ✅ 评分数据已存在 ({existing}条)，跳过")


# ── 3. 类目热度 ─────────────────────────────────────────
print("\n[3] 类目热度...")
existing = cur.execute("SELECT COUNT(*) FROM category_radar WHERE date=?", (today,)).fetchone()[0]
if existing < 3:
    categories = [
        ('美妆', '护肤', '面膜', 92.3, 0.15, 0.08),
        ('美妆', '彩妆', '化妆工具', 89.1, 0.12, 0.06),
        ('3C数码', '音频', '蓝牙耳机', 87.5, -0.05, 0.03),
        ('健康护理', '按摩仪器', '颈部按摩', 85.1, 0.18, 0.09),
        ('家居', '厨房', '切菜器', 78.4, 0.08, 0.04),
        ('运动户外', '健身', '跳绳', 83.6, 0.22, 0.11),
        ('母婴', '玩具', '积木', 71.2, 0.05, 0.02),
        ('宠物', '宠物用品', '饮水机', 76.8, 0.20, 0.10),
    ]
    for c in categories:
        cur.execute("""
        INSERT OR IGNORE INTO category_radar
        (date, category_l1, category_l2, keyword, heat_score, trend_7d, trend_30d, data_source)
        VALUES (?,?,?,?,?,?,?,?)
        """, (today, c[0], c[1], c[2], c[3], c[4], c[5], 'mock'))
    conn.commit()
    print(f"  ✅ 插入 {len(categories)} 条类目热度")
else:
    print(f"  ✅ 类目热度已存在 ({existing}条)，跳过")


# ── 4. 内容脚本 ─────────────────────────────────────────
print("\n[4] 内容脚本...")
existing = cur.execute("SELECT COUNT(*) FROM content_tasks WHERE task_date=?", (today,)).fetchone()[0]
if existing < 3:
    content_items = [
        {
            'pid': product_ids[0],
            'type': 'douyin', 'script_type': 'review',
            'title': '蓝牙耳机真实测评',
            'cover_copy': '129块买到降噪耳机？测评来了！',
            'hook_3s': '你以为降噪耳机要大几百？错了！',
            'storyboard': json.dumps([
                {'seq': 1, 'duration': 3, 'desc': '手持耳机开场，字幕：129元买到这个？'},
                {'seq': 2, 'duration': 8, 'desc': '开箱展示外观，与大牌对比'},
                {'seq': 3, 'duration': 10, 'desc': '实测降噪效果，嘈杂环境演示'},
                {'seq': 4, 'duration': 5, 'desc': '续航测试：30h实测数据'},
                {'seq': 5, 'duration': 4, 'desc': 'CTA：链接在评论区！'}
            ], ensure_ascii=False),
            'xhs_body': '姐妹们！这个蓝牙耳机真的绝了 ✨\n\n129元买到主动降噪，续航30h！\n\n👍 优点：\n• 降噪效果媲美大牌\n• 续航超级强\n• 佩戴舒适\n\n❌ 缺点：\n• 包装略普通\n\n总体超值推荐！🎧',
            'xhs_hashtags': json.dumps(['#耳机推荐', '#好物分享', '#平价好物', '#3C数码'], ensure_ascii=False),
            'pub_time_suggest': f'{today} 18:00',
            'status': 'approved',
        },
        {
            'pid': product_ids[1],
            'type': 'douyin', 'script_type': 'problem_solution',
            'title': '颈部按摩仪使用教程',
            'cover_copy': '打工人颈椎救星，下班必用！',
            'hook_3s': '打工人颈椎还好吗？这个真的救了我！',
            'storyboard': json.dumps([
                {'seq': 1, 'duration': 3, 'desc': '痛苦表情开场：颈椎酸痛日常'},
                {'seq': 2, 'duration': 6, 'desc': '展示按摩仪外观和功能'},
                {'seq': 3, 'duration': 12, 'desc': '实际使用演示：热敷+按摩'},
                {'seq': 4, 'duration': 4, 'desc': '用后对比，表情满足'},
                {'seq': 5, 'duration': 5, 'desc': '价格公布+购买引导'}
            ], ensure_ascii=False),
            'xhs_body': '打工人必看！！颈椎痛了两年，被这个治好了💆‍♀️\n\n189元的颈部按摩仪，热敷+按摩二合一\n\n每天下班用30分钟，真的舒服到飞起！\n\n有颈椎问题的姐妹快冲！',
            'xhs_hashtags': json.dumps(['#颈椎党', '#打工人', '#好物推荐', '#健康护理'], ensure_ascii=False),
            'pub_time_suggest': f'{today} 20:00',
            'status': 'approved',
        },
        {
            'pid': product_ids[2],
            'type': 'xhs', 'script_type': 'tutorial',
            'title': '美妆刷套装如何选？',
            'cover_copy': '60块搞定全套化妆刷，新手必看！',
            'hook_3s': '美妆博主同款刷具大揭秘！',
            'storyboard': json.dumps([
                {'seq': 1, 'duration': 4, 'desc': '刷具铺开展示，视觉冲击'},
                {'seq': 2, 'duration': 8, 'desc': '逐一介绍每支刷的用法'},
                {'seq': 3, 'duration': 10, 'desc': '实操演示妆效'},
                {'seq': 4, 'duration': 3, 'desc': '价格和购买信息'}
            ], ensure_ascii=False),
            'xhs_body': '新手化妆刷入门必看！60块搞定专业套装🖌️\n\n这套20支的化妆刷，每支都有用！\n\n腮红刷/修容刷/眼影刷/粉底刷全齐了\n\n妆效提升不是一点点～\n\n#化妆教程 #美妆新手 #好物分享',
            'xhs_hashtags': json.dumps(['#化妆教程', '#美妆新手', '#好物分享', '#化妆刷'], ensure_ascii=False),
            'pub_time_suggest': f'{today} 12:00',
            'status': 'pending_review',
        },
        {
            'pid': product_ids[3],
            'type': 'douyin', 'script_type': 'review',
            'title': '保温杯实测：真的能保温12小时？',
            'cover_copy': '89元保温杯，12h保温实测！',
            'hook_3s': '花了89块，早上倒热水晚上还是热的？',
            'storyboard': json.dumps([
                {'seq': 1, 'duration': 3, 'desc': '疑问引入：真的能保12小时？'},
                {'seq': 2, 'duration': 5, 'desc': '外观展示，304不锈钢'},
                {'seq': 3, 'duration': 8, 'desc': '12h温度记录：0h/4h/8h/12h'},
                {'seq': 4, 'duration': 4, 'desc': '结论：真的可以！'},
            ], ensure_ascii=False),
            'xhs_body': '被安利了很久的保温杯，终于入手测评了！\n\n89元 316不锈钢 12h保温\n\n早上8点倒进去的开水，晚上8点还有58度！\n\n颜值在线，日常通勤必备☕',
            'xhs_hashtags': json.dumps(['#保温杯', '#好物测评', '#家居好物'], ensure_ascii=False),
            'pub_time_suggest': f'{today} 19:00',
            'status': 'draft',
        },
    ]
    for item in content_items:
        cur.execute("""
        INSERT INTO content_tasks
        (product_id, task_date, script_type, title, cover_copy, hook_3s, storyboard,
         xhs_body, xhs_hashtags, pub_time_suggest, status, platform, gen_method)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (item['pid'], today, item['script_type'], item['title'],
              item['cover_copy'], item['hook_3s'], item['storyboard'],
              item['xhs_body'], item['xhs_hashtags'],
              item['pub_time_suggest'], item['status'],
              item['type'], 'ai_gen'))
    conn.commit()
    print(f"  ✅ 插入 {len(content_items)} 条内容脚本")
else:
    print(f"  ✅ 内容脚本已存在 ({existing}条)，跳过")


# 获取内容ID
content_ids = [r[0] for r in cur.execute(
    "SELECT id FROM content_tasks WHERE task_date=? ORDER BY id LIMIT 4", (today,)).fetchall()]
print(f"  内容IDs: {content_ids}")


# ── 5. 素材任务 ─────────────────────────────────────────
print("\n[5] 素材任务...")
existing = cur.execute("SELECT COUNT(*) FROM material_render_tasks").fetchone()[0]
if existing < 3:
    render_statuses = ['done', 'done', 'processing', 'pending']
    for i, cid in enumerate(content_ids[:4]):
        cur.execute("""
        INSERT INTO material_render_tasks
        (content_task_id, product_id, platform, script_type, task_date,
         material_type, source_key_point, status)
        VALUES (?,?,?,?,?,?,?,?)
        """, (cid, product_ids[i], 'douyin', 'review', today,
              'cover', f'核心卖点展示，价格突出',
              render_statuses[i % len(render_statuses)]))
    conn.commit()
    print(f"  ✅ 插入素材任务")
else:
    print(f"  ✅ 素材任务已存在 ({existing}条)，跳过")


# ── 6. 发布记录（昨日）────────────────────────────────
print("\n[6] 发布记录（昨日）...")
existing = cur.execute(
    "SELECT COUNT(*) FROM publish_records WHERE pub_time LIKE ?", (f'{yesterday}%',)).fetchone()[0]

pub_ids = []
if existing < 2:
    for i in range(min(4, len(content_ids))):
        cid = content_ids[i]
        pid = product_ids[i]
        cur.execute("""
        INSERT INTO publish_records
        (content_task_id, product_id, platform, pub_time, actual_pub_time,
         douyin_url, status, published_by)
        VALUES (?,?,?,?,?,?,?,?)
        """, (cid, pid, 'douyin',
              f'{yesterday} {18+i*2}:00:00',
              f'{yesterday} {18+i*2}:02:00',
              f'https://www.douyin.com/video/720{i+1}000',
              'published', 'chentao'))
        pub_ids.append(cur.lastrowid)
    conn.commit()
    print(f"  ✅ 插入 {len(pub_ids)} 条发布记录")
else:
    pub_ids = [r[0] for r in cur.execute(
        "SELECT id FROM publish_records WHERE pub_time LIKE ? LIMIT 4",
        (f'{yesterday}%',)).fetchall()]
    print(f"  ✅ 已存在 {existing} 条，使用 IDs: {pub_ids}")


# ── 7. 绩效数据（昨日）──────────────────────────────
print("\n[7] 绩效数据...")
existing = cur.execute(
    "SELECT COUNT(*) FROM performance_data WHERE record_date=?", (yesterday,)).fetchone()[0]
if existing < 2:
    perf_data = [
        (45000, 28000, 1890, 234, 156, 890, 67, 5983.0, 897.5),
        (32000, 18000, 1230, 189,  98, 560, 43, 3870.0, 696.6),
        (28000, 22000,  980, 145,  87, 420, 31, 1860.0, 465.0),
        (19000, 12000,  560,  89,  45, 280, 18, 1602.0, 192.2),
    ]
    for i, pub_id in enumerate(pub_ids[:4]):
        d = perf_data[i]
        impressions, plays = d[0], d[1]
        likes, comments, shares = d[2], d[3], d[4]
        product_clicks, orders, gmv, commission = d[5], d[6], d[7], d[8]
        cur.execute("""
        INSERT INTO performance_data
        (publish_id, content_task_id, product_id, platform, record_date,
         impressions, plays, play_rate, likes, comments, shares,
         product_clicks, orders, gmv, commission,
         completion_rate, like_rate, comment_rate, product_ctr,
         ctr, cvr, data_source)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (pub_id, content_ids[i] if i < len(content_ids) else None,
              product_ids[i], 'douyin', yesterday,
              impressions, plays, round(plays/impressions, 3),
              likes, comments, shares,
              product_clicks, orders, gmv, commission,
              round(plays/impressions*0.8, 3),
              round(likes/plays, 3),
              round(comments/plays, 3),
              round(product_clicks/plays, 3),
              round(product_clicks/impressions, 3),
              round(orders/product_clicks, 3),
              'mock'))
    conn.commit()
    print(f"  ✅ 插入 {len(pub_ids)} 条绩效数据")
else:
    print(f"  ✅ 绩效数据已存在 ({existing}条)，跳过")


# ── 8. 发布队列（今日待发）──────────────────────────
print("\n[8] 发布队列...")
existing = cur.execute("SELECT COUNT(*) FROM publish_queue").fetchone()[0]
if existing < 2:
    check_result_ok = json.dumps({
        "checks": [
            {"name": "脚本完整性", "passed": True, "detail": "脚本字数达标"},
            {"name": "素材就绪", "passed": True, "detail": "封面图已生成"},
            {"name": "无违禁词", "passed": True, "detail": "检测通过"},
            {"name": "发布时间合理", "passed": True, "detail": "18:00黄金时段"},
            {"name": "商品库存充足", "passed": True, "detail": "库存>100件"}
        ],
        "warnings": [],
        "risk_level": "none"
    }, ensure_ascii=False)

    queue_items = [
        (content_ids[0], product_ids[0], 'douyin', f'{today} 18:00', 1, 'approved', 'none', 'chentao'),
        (content_ids[1], product_ids[1], 'douyin', f'{today} 20:00', 2, 'pending_approve', 'low', None),
        (content_ids[2] if len(content_ids) > 2 else content_ids[0],
         product_ids[2], 'xhs', f'{today} 12:00', 2, 'checked', 'none', None),
    ]
    for q in queue_items:
        cur.execute("""
        INSERT INTO publish_queue
        (content_task_id, product_id, platform, scheduled_time, priority,
         status, risk_level, check_passed, check_result, checked_at,
         approved_by, approved_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (q[0], q[1], q[2], q[3], q[4], q[5], q[6],
              1, check_result_ok,
              datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
              q[7],
              datetime.now().strftime('%Y-%m-%d %H:%M:%S') if q[7] else None))
    conn.commit()
    print(f"  ✅ 插入 {len(queue_items)} 条发布队列")
else:
    print(f"  ✅ 发布队列已存在 ({existing}条)，跳过")


# ── 9. 复盘数据（昨日）──────────────────────────────
print("\n[9] 复盘数据...")
existing = cur.execute(
    "SELECT COUNT(*) FROM daily_review WHERE review_date=?", (yesterday,)).fetchone()[0]
if existing == 0:
    cur.execute("""
    INSERT INTO daily_review
    (review_date, products_analyzed, products_selected, scripts_generated,
     scripts_approved, videos_published, total_commission,
     best_product_id, best_script_type,
     insights, tomorrow_suggest)
    VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (yesterday, 10, 4, 6, 4, 4, 2251.3,
          product_ids[0], 'review',
          json.dumps(['美妆类完播率最高72%', '18:00时段曝光比20:00高35%', '测评脚本点击率高22%'], ensure_ascii=False),
          json.dumps(['重点推健康护理类目', '优先测评脚本框架', '安排18:00黄金时段2条'], ensure_ascii=False)))
    conn.commit()
    print("  ✅ 插入昨日复盘数据")
else:
    print("  ✅ 复盘数据已存在，跳过")


# ── 验证 ──────────────────────────────────────────────
print("\n" + "=" * 60)
print("验证各表数据量：")
tables_check = [
    'product_pool', 'product_scores', 'category_radar',
    'content_tasks', 'material_render_tasks',
    'publish_records', 'performance_data',
    'publish_queue', 'daily_review'
]
for t in tables_check:
    cnt = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t}: {cnt} 条")

conn.close()
print("\n✅ 测试数据填充完成！")
