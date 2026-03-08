"""
通用统计 API
- GET /api/v1/stats/overview            全局概览数字卡
- GET /api/v1/materials/upload/pending  待人工上传素材
- POST /api/v1/materials/upload/confirm 确认上传完成
"""

from flask import Blueprint, jsonify, request
from backend.db import query, query_one, execute
from datetime import datetime

stats_bp = Blueprint('stats', __name__)


@stats_bp.route('/stats/overview', methods=['GET'])
def stats_overview():
    """全局概览数字卡（首页 Header 区）"""
    today = datetime.now().strftime('%Y-%m-%d')

    products_total    = query_one("SELECT COUNT(*) c FROM product_pool", ())
    products_selected = query_one("SELECT COUNT(*) c FROM product_pool WHERE status='selected'", ())
    scripts_total     = query_one("SELECT COUNT(*) c FROM content_tasks", ())
    scripts_approved  = query_one("SELECT COUNT(*) c FROM content_tasks WHERE status='approved'", ())
    materials_done    = query_one("SELECT COUNT(*) c FROM material_render_tasks WHERE status='done'", ())
    materials_total   = query_one("SELECT COUNT(*) c FROM material_render_tasks", ())
    total_commission  = query_one("SELECT SUM(commission) s FROM performance_data", ())

    return jsonify({
        'today': today,
        'products':   {'total': products_total['c'], 'selected': products_selected['c']},
        'scripts':    {'total': scripts_total['c'],  'approved': scripts_approved['c']},
        'materials':  {'total': materials_total['c'], 'done': materials_done['c']},
        'commission': {'total': total_commission['s'] or 0},
    })


@stats_bp.route('/materials/upload/pending', methods=['GET'])
def materials_upload_pending():
    """待人工上传的素材清单"""
    rows = query("""
        SELECT mrt.id, mrt.content_task_id, mrt.product_id,
               mrt.platform, mrt.material_type, mrt.seq_index,
               mrt.filename, mrt.filepath,
               mrt.script_version, mrt.status,
               mrt.source_key_point,
               p.title AS product_title,
               ct.cover_copy
        FROM material_render_tasks mrt
        JOIN product_pool p ON p.id = mrt.product_id
        JOIN content_tasks ct ON ct.id = mrt.content_task_id
        WHERE mrt.status IN ('pending', 'failed')
        ORDER BY mrt.platform, mrt.product_id, mrt.seq_index
        LIMIT 100
    """)

    return jsonify({'count': len(rows), 'items': rows})


@stats_bp.route('/materials/upload/confirm', methods=['POST'])
def materials_upload_confirm():
    """确认人工上传完成，更新状态为 done"""
    data = request.get_json(force=True)
    task_ids = data.get('task_ids', [])

    if not task_ids:
        return jsonify({'error': '未提供 task_ids'}), 400

    updated = 0
    for tid in task_ids:
        execute("""
            UPDATE material_render_tasks
            SET status = 'done', updated_at = datetime('now','localtime')
            WHERE id = ?
        """, (tid,))
        updated += 1

    return jsonify({'success': True, 'updated': updated})
