"""
第三页 API：复盘看板
- GET  /api/v1/review/summary         每日复盘摘要
- GET  /api/v1/review/best-product    今日最佳商品
- GET  /api/v1/review/worst-products  今日低效商品
- GET  /api/v1/review/script-type-stats 脚本类型统计
- GET  /api/v1/review/tomorrow-suggest  明日建议
- POST /api/v1/review/save            保存/更新复盘
"""

from flask import Blueprint, jsonify, request
from backend.db import query, query_one, execute, json_parse
from datetime import datetime, timedelta

review_bp = Blueprint('review', __name__)


def _get_date(req):
    return req.args.get('date', datetime.now().strftime('%Y-%m-%d'))


@review_bp.route('/review/summary', methods=['GET'])
def review_summary():
    """每日复盘摘要数字卡"""
    date = _get_date(request)

    dr = query_one("""
        SELECT * FROM daily_review WHERE review_date = ?
    """, (date,))

    # 若无复盘记录，从各表实时统计
    if not dr:
        analyzed  = query_one("SELECT COUNT(*) c FROM product_pool WHERE add_date=?", (date,))
        selected  = query_one("SELECT COUNT(*) c FROM product_pool WHERE add_date=? AND status='selected'", (date,))
        generated = query_one("SELECT COUNT(*) c FROM content_tasks WHERE task_date=?", (date,))
        approved  = query_one("SELECT COUNT(*) c FROM content_tasks WHERE task_date=? AND status='approved'", (date,))
        published = query_one("SELECT COUNT(*) c FROM publish_records WHERE DATE(pub_time)=?", (date,))
        commission_row = query_one("""
            SELECT SUM(pd.commission) total
            FROM performance_data pd
            JOIN publish_records pr ON pr.id = pd.publish_id
            WHERE pd.record_date = ?
        """, (date,))

        dr = {
            'review_date':        date,
            'products_analyzed':  analyzed['c'] if analyzed else 0,
            'products_selected':  selected['c'] if selected else 0,
            'scripts_generated':  generated['c'] if generated else 0,
            'scripts_approved':   approved['c'] if approved else 0,
            'videos_published':   published['c'] if published else 0,
            'total_commission':   commission_row['total'] or 0 if commission_row else 0,
            'insights':           None,
            'tomorrow_suggest':   None,
            '_realtime': True,
        }

    return jsonify({'date': date, 'summary': dr})


@review_bp.route('/review/best-product', methods=['GET'])
def review_best_product():
    """今日最佳商品（按 GMV 或 CTR）"""
    date = _get_date(request)

    # 优先从 daily_review 取
    dr = query_one("SELECT best_product_id FROM daily_review WHERE review_date=?", (date,))
    if dr and dr.get('best_product_id'):
        product_id = dr['best_product_id']
    else:
        # 实时计算：今日发布内容中 GMV 最高的商品
        row = query_one("""
            SELECT pd.product_id, SUM(pd.gmv) total_gmv, SUM(pd.commission) total_commission,
                   AVG(pd.ctr) avg_ctr, SUM(pd.orders) total_orders
            FROM performance_data pd
            WHERE pd.record_date = ?
            GROUP BY pd.product_id
            ORDER BY total_gmv DESC, avg_ctr DESC
            LIMIT 1
        """, (date,))
        product_id = row['product_id'] if row else None

    if not product_id:
        return jsonify({'date': date, 'best_product': None, 'message': '暂无数据'})

    product = query_one("""
        SELECT p.*, ps.total_score,
               pd_agg.total_gmv, pd_agg.total_commission, pd_agg.avg_ctr, pd_agg.total_orders
        FROM product_pool p
        LEFT JOIN product_scores ps ON ps.product_id = p.id
            AND ps.score_date = (SELECT MAX(score_date) FROM product_scores WHERE product_id = p.id)
        LEFT JOIN (
            SELECT product_id,
                   SUM(gmv) total_gmv, SUM(commission) total_commission,
                   AVG(ctr) avg_ctr, SUM(orders) total_orders
            FROM performance_data WHERE record_date = ?
            GROUP BY product_id
        ) pd_agg ON pd_agg.product_id = p.id
        WHERE p.id = ?
    """, (date, product_id))

    return jsonify({'date': date, 'best_product': product})


@review_bp.route('/review/worst-products', methods=['GET'])
def review_worst_products():
    """今日低效商品（CTR 最低 / GMV=0）"""
    date = _get_date(request)

    rows = query("""
        SELECT p.id, p.title, p.cover_img, p.category_l1,
               p.commission_amt, p.pdd_url,
               pd_agg.total_gmv, pd_agg.avg_ctr, pd_agg.total_orders,
               ps.total_score,
               ps.s06_low_explain, ps.s07_low_decision, ps.s08_impulse_price
        FROM product_pool p
        JOIN (
            SELECT product_id,
                   SUM(gmv) total_gmv, AVG(ctr) avg_ctr, SUM(orders) total_orders
            FROM performance_data WHERE record_date = ?
            GROUP BY product_id
        ) pd_agg ON pd_agg.product_id = p.id
        LEFT JOIN product_scores ps ON ps.product_id = p.id
            AND ps.score_date = (SELECT MAX(score_date) FROM product_scores WHERE product_id = p.id)
        ORDER BY pd_agg.total_gmv ASC, pd_agg.avg_ctr ASC
        LIMIT 3
    """, (date,))

    # 为每个低效商品生成原因分析
    for r in rows:
        reasons = []
        s6 = r.get('s06_low_explain') or 0
        s7 = r.get('s07_low_decision') or 0
        s8 = r.get('s08_impulse_price') or 0
        if s6 < 5:
            reasons.append('解释成本高（需要演示才能理解）')
        if s7 < 5:
            reasons.append('决策成本高（价格偏高或需比较）')
        if s8 < 5:
            reasons.append('价格带不适合冲动消费')
        if not reasons:
            reasons.append('内容质量或发布时间需优化')
        r['reason_analysis'] = reasons

    return jsonify({'date': date, 'worst_products': rows})


@review_bp.route('/review/script-type-stats', methods=['GET'])
def script_type_stats():
    """脚本类型转化率统计（今日有效脚本类型）"""
    date = _get_date(request)

    # 从 content_tasks 统计各类型数量
    type_counts = query("""
        SELECT script_type,
               COUNT(*) total,
               SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) approved,
               SUM(CASE WHEN status='published' THEN 1 ELSE 0 END) published
        FROM content_tasks
        WHERE task_date = ?
        GROUP BY script_type
    """, (date,))

    # 结合 performance_data 获取转化数据
    type_perf = query("""
        SELECT ct.script_type,
               SUM(pd.orders) total_orders,
               AVG(pd.ctr) avg_ctr,
               SUM(pd.gmv) total_gmv
        FROM performance_data pd
        JOIN publish_records pr ON pr.id = pd.publish_id
        JOIN content_tasks ct ON ct.id = pr.content_task_id
        WHERE pd.record_date = ?
        GROUP BY ct.script_type
    """, (date,))

    perf_map = {r['script_type']: r for r in type_perf}

    type_label = {
        'pain_point': '痛点型',
        'scene':      '场景型',
        'contrast':   '反差型',
        'list':       '列举型',
    }

    result = []
    for row in type_counts:
        st   = row['script_type']
        perf = perf_map.get(st, {})
        result.append({
            'script_type':    st,
            'label':          type_label.get(st, st),
            'total':          row['total'],
            'approved':       row['approved'],
            'published':      row['published'],
            'total_orders':   perf.get('total_orders') or 0,
            'avg_ctr':        round(perf.get('avg_ctr') or 0, 4),
            'total_gmv':      perf.get('total_gmv') or 0,
        })

    # 按 GMV 降序排列，判断最有效类型
    result.sort(key=lambda x: x['total_gmv'], reverse=True)
    if result:
        result[0]['is_best'] = True

    return jsonify({'date': date, 'script_types': result})


@review_bp.route('/review/tomorrow-suggest', methods=['GET'])
def tomorrow_suggest():
    """明日调整建议"""
    date = _get_date(request)

    dr = query_one("SELECT tomorrow_suggest, insights FROM daily_review WHERE review_date=?", (date,))

    if dr and dr.get('tomorrow_suggest'):
        suggests = json_parse(dr['tomorrow_suggest'], [])
        if isinstance(suggests, str):
            suggests = [suggests]
    else:
        # 实时生成基础建议
        suggests = _generate_auto_suggests(date)

    return jsonify({'date': date, 'suggests': suggests})


def _generate_auto_suggests(date):
    """基于当日数据自动生成明日建议"""
    suggests = []

    # 1. 分析热度上升的类目
    hot_cats = query("""
        SELECT category_l1, category_l2, heat_score, trend_7d
        FROM category_radar
        WHERE date = ? AND trend_7d = 'rising'
        ORDER BY heat_score DESC LIMIT 3
    """, (date,))
    if hot_cats:
        cats = '、'.join([f"{r['category_l1']}/{r['category_l2']}" for r in hot_cats])
        suggests.append(f"📈 优先选品：{cats}（热度上升趋势）")
    else:
        suggests.append("📌 继续关注近期表现稳定的主力类目")

    # 2. 分析最有效脚本类型
    best_type = query_one("""
        SELECT ct.script_type, SUM(pd.gmv) gmv
        FROM performance_data pd
        JOIN publish_records pr ON pr.id = pd.publish_id
        JOIN content_tasks ct ON ct.id = pr.content_task_id
        WHERE pd.record_date = ?
        GROUP BY ct.script_type ORDER BY gmv DESC LIMIT 1
    """, (date,))
    if best_type and best_type.get('gmv', 0) > 0:
        type_label = {'pain_point': '痛点型', 'scene': '场景型', 'contrast': '反差型', 'list': '列举型'}
        label = type_label.get(best_type['script_type'], best_type['script_type'])
        suggests.append(f"✍️ 明日脚本：增加{label}脚本比例（今日转化率最高）")

    # 3. 佣金分析
    commission_row = query_one("""
        SELECT SUM(commission) total FROM performance_data WHERE record_date = ?
    """, (date,))
    total_commission = commission_row['total'] or 0 if commission_row else 0
    if total_commission < 100:
        suggests.append("💰 佣金偏低：优先筛选佣金率 > 20% 的商品，提升单条内容收益")

    # 兜底建议
    if len(suggests) < 2:
        suggests.append("🔄 保持当前选品节奏，关注评分 80 分以上商品的发布时机")

    return suggests


@review_bp.route('/review/save', methods=['POST'])
def save_review():
    """保存/更新每日复盘报告"""
    data = request.get_json(force=True)
    date = data.get('review_date', datetime.now().strftime('%Y-%m-%d'))

    # 检查是否已有记录
    existing = query_one("SELECT id FROM daily_review WHERE review_date = ?", (date,))

    import json as _json

    tomorrow_suggest = data.get('tomorrow_suggest', '')
    if isinstance(tomorrow_suggest, list):
        tomorrow_suggest = _json.dumps(tomorrow_suggest, ensure_ascii=False)

    if existing:
        execute("""
            UPDATE daily_review
            SET insights = ?,
                tomorrow_suggest = ?,
                best_product_id = ?,
                worst_product_id = ?,
                best_script_type = ?,
                weight_update_suggest = ?,
                updated_by = ?
            WHERE review_date = ?
        """, (
            data.get('insights'),
            tomorrow_suggest,
            data.get('best_product_id'),
            data.get('worst_product_id'),
            data.get('best_script_type'),
            data.get('weight_update_suggest'),
            data.get('updated_by', 'admin'),
            date,
        ))
        return jsonify({'success': True, 'action': 'updated', 'date': date})
    else:
        rid = execute("""
            INSERT INTO daily_review
                (review_date, insights, tomorrow_suggest,
                 best_product_id, worst_product_id, best_script_type,
                 weight_update_suggest, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            date,
            data.get('insights'),
            tomorrow_suggest,
            data.get('best_product_id'),
            data.get('worst_product_id'),
            data.get('best_script_type'),
            data.get('weight_update_suggest'),
            data.get('updated_by', 'admin'),
        ))
        return jsonify({'success': True, 'action': 'created', 'id': rid, 'date': date})
