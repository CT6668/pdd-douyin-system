"""
第一页 API：选品看板
- GET /api/v1/category/today        今日重点类目
- GET /api/v1/products/top10        今日 Top10 候选商品
- GET /api/v1/products/<id>/scorecard  单商品 13 维评分
- PATCH /api/v1/products/<id>/status   更新商品状态
"""

from flask import Blueprint, jsonify, request
from backend.db import query, query_one, execute
from datetime import datetime

products_bp = Blueprint('products', __name__)


@products_bp.route('/category/today', methods=['GET'])
def category_today():
    """今日重点类目（热度排序 TOP5）"""
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    rows = query("""
        SELECT category_l1, category_l2, keyword,
               heat_score, trend_7d, trend_30d, notes
        FROM category_radar
        WHERE date = ?
        ORDER BY heat_score DESC
        LIMIT 10
    """, (date,))

    # 若今日无数据，取最近一天
    if not rows:
        rows = query("""
            SELECT category_l1, category_l2, keyword,
                   heat_score, trend_7d, trend_30d, notes, date
            FROM category_radar
            ORDER BY date DESC, heat_score DESC
            LIMIT 10
        """)

    return jsonify({'date': date, 'categories': rows})


@products_bp.route('/products/top10', methods=['GET'])
def products_top10():
    """今日 Top10 候选商品（按总分降序）"""
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))

    rows = query("""
        SELECT p.id, p.pdd_goods_id, p.title, p.category_l1, p.category_l2,
               p.price, p.origin_price, p.commission_rate, p.commission_amt,
               p.sales_30d, p.sales_7d, p.rating, p.review_count,
               p.pdd_url, p.cover_img, p.status,
               ps.total_score,
               ps.s01_pdd_heat, ps.s04_douyin_fit, ps.s05_visual_strength,
               ps.s09_commission_val
        FROM product_pool p
        LEFT JOIN product_scores ps ON ps.product_id = p.id
            AND ps.score_date = (
                SELECT MAX(score_date) FROM product_scores WHERE product_id = p.id
            )
        WHERE p.add_date = ?
           OR p.status IN ('selected', 'scoring', 'scored')
        ORDER BY ps.total_score DESC NULLS LAST
        LIMIT 10
    """, (date,))

    # 若今日无数据，取已选中 / 近期高分商品
    if not rows:
        rows = query("""
            SELECT p.id, p.pdd_goods_id, p.title, p.category_l1, p.category_l2,
                   p.price, p.origin_price, p.commission_rate, p.commission_amt,
                   p.sales_30d, p.sales_7d, p.rating, p.review_count,
                   p.pdd_url, p.cover_img, p.status,
                   ps.total_score,
                   ps.s01_pdd_heat, ps.s04_douyin_fit, ps.s05_visual_strength,
                   ps.s09_commission_val
            FROM product_pool p
            LEFT JOIN product_scores ps ON ps.product_id = p.id
                AND ps.score_date = (
                    SELECT MAX(score_date) FROM product_scores WHERE product_id = p.id
                )
            ORDER BY ps.total_score DESC NULLS LAST
            LIMIT 10
        """)

    return jsonify({'date': date, 'products': rows})


@products_bp.route('/products/<int:product_id>/scorecard', methods=['GET'])
def product_scorecard(product_id):
    """单商品完整评分卡（13 维 + 基础信息）"""
    product = query_one("""
        SELECT id, pdd_goods_id, title, category_l1, category_l2,
               price, origin_price, commission_rate, commission_amt,
               sales_30d, sales_7d, rating, review_count,
               pdd_url, cover_img, status, notes
        FROM product_pool WHERE id = ?
    """, (product_id,))

    if not product:
        return jsonify({'error': '商品不存在'}), 404

    score = query_one("""
        SELECT * FROM product_scores
        WHERE product_id = ?
        ORDER BY score_date DESC
        LIMIT 1
    """, (product_id,))

    # 13 维标签映射
    dim_labels = {
        's01_pdd_heat':        '拼多多热度',
        's02_growth_7d':       '7天增速',
        's03_trend_30d':       '30天趋势',
        's04_douyin_fit':      '抖音适配度',
        's05_visual_strength': '视觉展示强度',
        's06_low_explain':     '低解释成本',
        's07_low_decision':    '低决策成本',
        's08_impulse_price':   '冲动消费适合度',
        's09_commission_val':  '佣金价值',
        's10_competition':     '竞争难度（低=好）',
        's11_supply_stable':   '供给稳定性',
        's12_compliance_risk': '合规风险（低=好）',
        's13_refund_risk':     '退货风险（低=好）',
    }

    dimensions = []
    if score:
        for key, label in dim_labels.items():
            dimensions.append({
                'key': key,
                'label': label,
                'value': score.get(key, 0),
            })

    return jsonify({
        'product': product,
        'score': score,
        'dimensions': dimensions,
    })


@products_bp.route('/products/<int:product_id>/status', methods=['PATCH'])
def update_product_status(product_id):
    """更新商品状态（selected / rejected / pending）"""
    data = request.get_json(force=True)
    new_status = data.get('status')
    if new_status not in ('selected', 'rejected', 'pending', 'scoring', 'scored'):
        return jsonify({'error': '无效状态值'}), 400

    execute("""
        UPDATE product_pool
        SET status = ?, updated_at = datetime('now','localtime')
        WHERE id = ?
    """, (new_status, product_id))

    return jsonify({'success': True, 'product_id': product_id, 'status': new_status})
