"""
发布队列 API
- GET  /api/v1/publish/queue            查询发布队列
- POST /api/v1/publish/enqueue          入队（单条）
- POST /api/v1/publish/enqueue-batch    批量入队
- POST /api/v1/publish/approve          审批通过
- POST /api/v1/publish/reject           驳回
- POST /api/v1/publish/recheck          重新检查
- GET  /api/v1/publish/pending-approve  待审批列表
- GET  /api/v1/publish/stats            今日队列统计
- GET  /api/v1/breaker/active           激活的熔断
- POST /api/v1/breaker/resolve          解除熔断
- GET  /api/v1/breaker/history          熔断历史
- POST /api/v1/tracker/record           录入表现数据
- GET  /api/v1/tracker/daily            当日表现汇总
- GET  /api/v1/tracker/content/<id>     单条内容表现
"""

import sys
import os
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from flask import Blueprint, jsonify, request
from datetime import datetime
from publish.queue   import PublishQueue
from publish.breaker import CircuitBreaker
from publish.tracker import PerformanceTracker, PERF_FIELDS

publish_bp = Blueprint('publish', __name__)

_queue   = PublishQueue()
_breaker = CircuitBreaker()
_tracker = PerformanceTracker()


# ── 队列管理 ──────────────────────────────────────────────────

@publish_bp.route('/publish/queue', methods=['GET'])
def get_queue():
    date     = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    status   = request.args.get('status', '')
    platform = request.args.get('platform', '')
    items    = _queue.get_queue(date, status or None, platform or None)

    # 解析 JSON 字段
    for item in items:
        if item.get('check_result'):
            try:
                import json
                item['check_result'] = json.loads(item['check_result'])
            except Exception:
                pass
        if item.get('risk_flags'):
            try:
                import json
                item['risk_flags'] = json.loads(item['risk_flags'])
            except Exception:
                pass

    return jsonify({'date': date, 'total': len(items), 'items': items})


@publish_bp.route('/publish/enqueue', methods=['POST'])
def enqueue():
    data = request.get_json(force=True)
    content_task_id = data.get('content_task_id')
    scheduled_time  = data.get('scheduled_time')
    priority        = int(data.get('priority', 2))
    operator        = data.get('operator', 'admin')

    if not content_task_id:
        return jsonify({'error': '缺少 content_task_id'}), 400
    if not scheduled_time:
        return jsonify({'error': '缺少 scheduled_time（格式 YYYY-MM-DD HH:MM）'}), 400

    result = _queue.enqueue(int(content_task_id), scheduled_time, priority, operator)
    return jsonify(result), 200 if result.get('success') else 400


@publish_bp.route('/publish/enqueue-batch', methods=['POST'])
def enqueue_batch():
    data        = request.get_json(force=True)
    content_ids = data.get('content_ids', [])
    base_date   = data.get('base_date', datetime.now().strftime('%Y-%m-%d'))
    operator    = data.get('operator', 'admin')

    if not content_ids:
        return jsonify({'error': '缺少 content_ids'}), 400

    results = _queue.enqueue_batch(content_ids, base_date, operator)
    success = sum(1 for r in results if r.get('success'))
    return jsonify({
        'total':   len(results),
        'success': success,
        'failed':  len(results) - success,
        'results': results,
    })


@publish_bp.route('/publish/approve', methods=['POST'])
def approve():
    data      = request.get_json(force=True)
    queue_id  = data.get('queue_id')
    approver  = data.get('approver', '').strip()
    note      = data.get('note', '')

    if not queue_id:
        return jsonify({'error': '缺少 queue_id'}), 400
    if not approver:
        return jsonify({'error': '必须填写审批人（approver）'}), 400

    result = _queue.approve(int(queue_id), approver, note)
    return jsonify(result), 200 if result.get('success') else 400


@publish_bp.route('/publish/reject', methods=['POST'])
def reject():
    data     = request.get_json(force=True)
    queue_id = data.get('queue_id')
    approver = data.get('approver', 'admin')
    reason   = data.get('reason', '')

    if not queue_id:
        return jsonify({'error': '缺少 queue_id'}), 400
    if not reason:
        return jsonify({'error': '驳回必须填写原因'}), 400

    result = _queue.reject(int(queue_id), approver, reason)
    return jsonify(result)


@publish_bp.route('/publish/recheck', methods=['POST'])
def recheck():
    data     = request.get_json(force=True)
    queue_id = data.get('queue_id')
    if not queue_id:
        return jsonify({'error': '缺少 queue_id'}), 400
    result = _queue.recheck(int(queue_id))
    return jsonify(result)


@publish_bp.route('/publish/pending-approve', methods=['GET'])
def pending_approve():
    items = _queue.get_pending_approve()
    return jsonify({'total': len(items), 'items': items})


@publish_bp.route('/publish/stats', methods=['GET'])
def queue_stats():
    date  = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    stats = _queue.get_stats(date)
    return jsonify({'date': date, 'stats': stats})


# ── 熔断管理 ──────────────────────────────────────────────────

@publish_bp.route('/breaker/active', methods=['GET'])
def breaker_active():
    items = _breaker.get_active()
    return jsonify({'count': len(items), 'items': items})


@publish_bp.route('/breaker/resolve', methods=['POST'])
def breaker_resolve():
    data     = request.get_json(force=True)
    cb_id    = data.get('cb_id')
    resolver = data.get('resolver', '').strip()
    note     = data.get('note', '').strip()

    if not cb_id:
        return jsonify({'error': '缺少 cb_id'}), 400
    if not resolver:
        return jsonify({'error': '必须填写解除人（resolver）'}), 400
    if not note:
        return jsonify({'error': '必须填写解除原因（note）'}), 400

    result = _breaker.resolve(int(cb_id), resolver, note)
    return jsonify(result), 200 if result.get('success') else 400


@publish_bp.route('/breaker/history', methods=['GET'])
def breaker_history():
    days  = int(request.args.get('days', 7))
    items = _breaker.get_history(days)
    return jsonify({'days': days, 'count': len(items), 'items': items})


# ── 数据回传 ──────────────────────────────────────────────────

@publish_bp.route('/tracker/record', methods=['POST'])
def tracker_record():
    data              = request.get_json(force=True)
    publish_record_id = data.get('publish_record_id')
    content_task_id   = data.get('content_task_id')

    if publish_record_id:
        result = _tracker.record(int(publish_record_id), data,
                                 data.get('data_source', 'manual'))
    elif content_task_id:
        result = _tracker.record_by_content(int(content_task_id), data,
                                            data.get('data_source', 'manual'))
    else:
        return jsonify({'error': '需要 publish_record_id 或 content_task_id'}), 400

    return jsonify(result), 200 if result.get('success') else 400


@publish_bp.route('/tracker/daily', methods=['GET'])
def tracker_daily():
    date   = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    result = _tracker.get_daily_summary(date)
    return jsonify(result)


@publish_bp.route('/tracker/content/<int:content_id>', methods=['GET'])
def tracker_content(content_id):
    result = _tracker.get_content_performance(content_id)
    return jsonify(result)


@publish_bp.route('/tracker/fields', methods=['GET'])
def tracker_fields():
    """回传字段规范（供前端表单生成用）"""
    fields = []
    for field, (ftype, required, desc, fmin, fmax) in PERF_FIELDS.items():
        fields.append({
            'field':    field,
            'type':     ftype,
            'required': required,
            'desc':     desc,
            'min':      fmin,
            'max':      fmax,
        })
    return jsonify({'fields': fields})
