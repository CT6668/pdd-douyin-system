"""
第二页 API：内容看板
- GET  /api/v1/content               内容列表（支持筛选）
- GET  /api/v1/content/<id>/script   脚本完整内容
- GET  /api/v1/content/<id>/materials 素材渲染状态
- PATCH /api/v1/content/<id>/status   脚本审核
- GET  /api/v1/publish/schedule       今日发布安排
"""

from flask import Blueprint, jsonify, request
from backend.db import query, query_one, execute, json_parse
from datetime import datetime
import json

content_bp = Blueprint('content', __name__)


@content_bp.route('/content', methods=['GET'])
def content_list():
    """内容列表（按日期/平台/状态筛选）"""
    date     = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    platform = request.args.get('platform', '')   # douyin / xiaohongshu / ''=全部
    status   = request.args.get('status', '')     # draft/approved/rejected/''=全部
    page     = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    offset   = (page - 1) * per_page

    conditions = ['ct.task_date = ?']
    params = [date]

    if platform:
        conditions.append('ct.platform = ?')
        params.append(platform)
    if status:
        conditions.append('ct.status = ?')
        params.append(status)

    where = ' AND '.join(conditions)

    rows = query(f"""
        SELECT ct.id, ct.product_id, ct.task_date, ct.platform, ct.script_type,
               ct.title, ct.cover_copy, ct.hook_3s,
               ct.xhs_body AS cover_title,
               ct.pub_time_suggest, ct.cta, ct.status,
               ct.gen_method, ct.reviewer, ct.review_at, ct.notes,
               p.title AS product_title, p.cover_img, p.commission_amt,
               p.pdd_url
        FROM content_tasks ct
        JOIN product_pool p ON p.id = ct.product_id
        WHERE {where}
        ORDER BY ct.id DESC
        LIMIT ? OFFSET ?
    """, params + [per_page, offset])

    # 统计总数
    count_row = query_one(f"""
        SELECT COUNT(*) as cnt FROM content_tasks ct WHERE {where}
    """, params)
    total = count_row['cnt'] if count_row else 0

    return jsonify({
        'date': date, 'platform': platform, 'status': status,
        'total': total, 'page': page, 'per_page': per_page,
        'items': rows,
    })


@content_bp.route('/content/<int:content_id>/script', methods=['GET'])
def content_script(content_id):
    """单条脚本完整内容"""
    ct = query_one("""
        SELECT ct.*, p.title AS product_title, p.cover_img, p.pdd_url,
               p.price, p.commission_amt, p.category_l1
        FROM content_tasks ct
        JOIN product_pool p ON p.id = ct.product_id
        WHERE ct.id = ?
    """, (content_id,))

    if not ct:
        return jsonify({'error': '内容不存在'}), 404

    # 兼容新旧字段名
    # 小红书封面标题：优先 cover_title，回退到 xhs_body 首行
    if not ct.get('cover_title'):
        xhs_body = ct.get('xhs_body', '') or ''
        ct['cover_title'] = xhs_body.split('\n')[0][:20] if xhs_body else ''
    if not ct.get('body_text'):
        ct['body_text'] = ct.get('xhs_body', '')
    if not ct.get('hashtags'):
        ct['hashtags'] = ct.get('xhs_hashtags', '[]')
    if not ct.get('images_spec'):
        ct['images_spec'] = ct.get('xhs_img_guide', '[]')

    # 解析 JSON 字段
    ct['storyboard_parsed']   = json_parse(ct.get('storyboard'), [])
    ct['images_spec_parsed']  = json_parse(ct.get('images_spec'), [])
    ct['hashtags_parsed']     = json_parse(ct.get('hashtags'), [])
    ct['compliance_parsed']   = json_parse(ct.get('compliance_check'), {})

    return jsonify({'script': ct})


@content_bp.route('/content/<int:content_id>/materials', methods=['GET'])
def content_materials(content_id):
    """素材渲染任务状态"""
    tasks = query("""
        SELECT id, platform, material_type, seq_index, filename, filepath,
               status, script_version, overlay_text, img_purpose,
               created_at, updated_at
        FROM material_render_tasks
        WHERE content_task_id = ?
        ORDER BY seq_index
    """, (content_id,))

    # 统计
    stats = {'total': len(tasks), 'done': 0, 'pending': 0, 'failed': 0}
    for t in tasks:
        s = t.get('status', 'pending')
        if s == 'done':
            stats['done'] += 1
        elif s == 'failed':
            stats['failed'] += 1
        else:
            stats['pending'] += 1

    return jsonify({'content_id': content_id, 'stats': stats, 'tasks': tasks})


@content_bp.route('/content/<int:content_id>/status', methods=['PATCH'])
def update_content_status(content_id):
    """脚本审核（approved / rejected / pending_review）"""
    data       = request.get_json(force=True)
    new_status = data.get('status')
    reviewer   = data.get('reviewer', 'admin')
    reason     = data.get('reason', '')

    valid = ('draft', 'pending_review', 'approved', 'rejected', 'published')
    if new_status not in valid:
        return jsonify({'error': '无效状态值'}), 400

    execute("""
        UPDATE content_tasks
        SET status = ?, reviewer = ?, review_at = datetime('now','localtime'),
            reject_reason = ?, updated_at = datetime('now','localtime')
        WHERE id = ?
    """, (new_status, reviewer, reason, content_id))

    return jsonify({'success': True, 'content_id': content_id, 'status': new_status})


@content_bp.route('/publish/schedule', methods=['GET'])
def publish_schedule():
    """今日发布时间安排"""
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))

    rows = query("""
        SELECT ct.id, ct.platform, ct.script_type,
               ct.cover_copy,
               ct.pub_time_suggest, ct.status,
               p.title AS product_title, p.pdd_url
        FROM content_tasks ct
        JOIN product_pool p ON p.id = ct.product_id
        WHERE ct.task_date = ?
          AND ct.status IN ('approved', 'published')
        ORDER BY ct.platform, ct.pub_time_suggest
    """, (date,))

    # 按平台分组
    douyin    = [r for r in rows if r['platform'] == 'douyin']
    xiaohongshu = [r for r in rows if r['platform'] == 'xiaohongshu']

    # 建议发布时段摘要
    time_guide = {
        'douyin': [
            {'slot': '07:00-09:00', 'desc': '早高峰通勤，碎片时间'},
            {'slot': '12:00-14:00', 'desc': '午休，最高触达'},
            {'slot': '20:00-22:00', 'desc': '黄金时段，最高转化'},
        ],
        'xiaohongshu': [
            {'slot': '09:00-11:00', 'desc': '上班前浏览期'},
            {'slot': '12:00-14:00', 'desc': '午休种草高峰'},
            {'slot': '21:00-23:00', 'desc': '睡前刷手机，收藏率高'},
        ],
    }

    return jsonify({
        'date': date,
        'douyin':       {'items': douyin,       'guide': time_guide['douyin']},
        'xiaohongshu':  {'items': xiaohongshu,  'guide': time_guide['xiaohongshu']},
    })
