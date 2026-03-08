"""
待发布队列管理 v1.0
──────────────────────────────────────────────────────────────
职责：
  - 将 approved 脚本加入发布队列
  - 查询今日/未来队列
  - 人工审批（approve / reject）
  - 状态流转
  - 重试机制
"""

import sys
import os
import json
from datetime import datetime, timedelta
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.db import query, query_one, execute
from publish.checker import PrePublishChecker
from publish.breaker import CircuitBreaker


class PublishQueue:

    def __init__(self):
        self.checker = PrePublishChecker()
        self.breaker = CircuitBreaker()

    # ── 入队 ─────────────────────────────────────────────────

    def enqueue(self, content_task_id: int, scheduled_time: str,
                priority: int = 2, operator: str = 'system') -> dict:
        """
        将一条 approved 脚本加入发布队列并自动运行检查
        Returns: {'success': bool, 'queue_id': int, 'check_result': dict}
        """

        # 全局熔断检查（最优先）
        cb = self.breaker.check_global()
        if cb:
            return {
                'success': False,
                'error': f'[熔断] 全局熔断中，无法入队：{cb["trigger_reason"]}',
                'circuit_breaker': cb,
            }

        # 脚本存在且已 approved
        ct = query_one("SELECT * FROM content_tasks WHERE id=?", (content_task_id,))
        if not ct:
            return {'success': False, 'error': f'脚本 {content_task_id} 不存在'}
        if ct['status'] != 'approved':
            return {'success': False, 'error': f'脚本状态为 {ct["status"]}，必须 approved 才可入队'}

        # 校验时间格式
        try:
            st = datetime.strptime(scheduled_time[:16], '%Y-%m-%d %H:%M')
            scheduled_time = st.strftime('%Y-%m-%d %H:%M')
        except ValueError:
            return {'success': False, 'error': f'时间格式错误：{scheduled_time}，请用 YYYY-MM-DD HH:MM'}

        # 是否已在队列中（避免重复入队）
        existing = query_one("""
            SELECT id FROM publish_queue
            WHERE content_task_id=? AND status NOT IN ('published','cancelled','failed')
        """, (content_task_id,))
        if existing:
            return {
                'success': False,
                'error': f'该脚本已在队列中（queue_id={existing["id"]}）',
            }

        # 写入队列
        queue_id = execute("""
            INSERT INTO publish_queue
                (content_task_id, product_id, platform, scheduled_time, priority, status)
            VALUES (?, ?, ?, ?, ?, 'pending_check')
        """, (content_task_id, ct['product_id'], ct.get('platform', 'douyin'),
              scheduled_time, priority))

        # 自动运行检查
        check_result = self.checker.run(queue_id)

        return {
            'success':      True,
            'queue_id':     queue_id,
            'check_result': check_result,
            'need_approve': check_result.get('check_passed', 1) >= 1,
        }

    def enqueue_batch(self, content_ids: list, base_date: str = None,
                      operator: str = 'system') -> list:
        """
        批量入队：按 pub_time_suggest 自动推算发布时间
        base_date: 默认今天 YYYY-MM-DD
        """
        if not base_date:
            base_date = datetime.now().strftime('%Y-%m-%d')

        results = []
        for cid in content_ids:
            ct = query_one("SELECT * FROM content_tasks WHERE id=?", (cid,))
            if not ct:
                results.append({'content_id': cid, 'success': False, 'error': '脚本不存在'})
                continue

            # 解析建议时间 -> 取第一个时段的开始时间
            sched = self._parse_suggest_time(ct.get('pub_time_suggest', ''), base_date)
            r = self.enqueue(cid, sched, operator=operator)
            r['content_id'] = cid
            results.append(r)

        return results

    def _parse_suggest_time(self, suggest: str, base_date: str) -> str:
        """从 pub_time_suggest 文本中提取第一个时段的开始时间"""
        # 匹配 HH:MM 格式
        matches = re.findall(r'(\d{2}):(\d{2})', suggest)
        if matches:
            h, m = matches[0]
            return f"{base_date} {h}:{m}"
        # 默认 20:00
        return f"{base_date} 20:00"

    # ── 查询 ─────────────────────────────────────────────────

    def get_queue(self, date: str = None, status: str = None,
                  platform: str = None) -> list:
        """查询发布队列"""
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')

        conditions = ["DATE(pq.scheduled_time) = ?"]
        params = [date]
        if status:
            conditions.append("pq.status = ?")
            params.append(status)
        if platform:
            conditions.append("pq.platform = ?")
            params.append(platform)

        where = ' AND '.join(conditions)
        return query(f"""
            SELECT pq.*,
                   ct.cover_copy, ct.hook_3s, ct.script_type, ct.status AS script_status,
                   ct.reviewer,
                   p.title AS product_title, p.cover_img, p.commission_amt, p.pdd_url
            FROM publish_queue pq
            JOIN content_tasks ct ON ct.id = pq.content_task_id
            JOIN product_pool  p  ON p.id  = pq.product_id
            WHERE {where}
            ORDER BY pq.priority ASC, pq.scheduled_time ASC
        """, params)

    def get_pending_approve(self) -> list:
        """待人工审批列表"""
        return query("""
            SELECT pq.*,
                   ct.cover_copy, ct.hook_3s, ct.script_type, ct.reviewer,
                   p.title AS product_title, p.cover_img, p.pdd_url
            FROM publish_queue pq
            JOIN content_tasks ct ON ct.id = pq.content_task_id
            JOIN product_pool  p  ON p.id  = pq.product_id
            WHERE pq.status IN ('checked','pending_approve')
            ORDER BY pq.priority ASC, pq.scheduled_time ASC
        """)

    def get_stats(self, date: str = None) -> dict:
        """今日队列统计"""
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')
        rows = query("""
            SELECT status, COUNT(*) cnt
            FROM publish_queue
            WHERE DATE(scheduled_time) = ?
            GROUP BY status
        """, (date,))
        stats = {r['status']: r['cnt'] for r in rows}
        stats['total'] = sum(stats.values())
        return stats

    # ── 审批 ─────────────────────────────────────────────────

    def approve(self, queue_id: int, approver: str, note: str = '') -> dict:
        """
        人工审批通过
        - 必须填写 approver
        - 检查是否有高风险需要 override
        """
        if not approver or approver.strip() == '':
            return {'success': False, 'error': '必须填写审批人（approver）'}

        queue = query_one("SELECT * FROM publish_queue WHERE id=?", (queue_id,))
        if not queue:
            return {'success': False, 'error': '队列记录不存在'}

        if queue['status'] not in ('checked', 'pending_approve', 'check_failed'):
            return {
                'success': False,
                'error':   f'当前状态 {queue["status"]} 无法审批（需要 checked/pending_approve）',
            }

        # 高风险：需要额外 note 说明
        if queue.get('risk_level') == 'high' and not note:
            return {
                'success': False,
                'error':   '高风险内容必须在 approval_note 中填写风险确认说明',
            }

        # 全局熔断二次检查
        cb = self.breaker.check_global()
        if cb:
            return {
                'success': False,
                'error': f'[熔断] 全局熔断中，审批暂停：{cb["trigger_reason"]}',
            }

        execute("""
            UPDATE publish_queue
            SET status='approved', approved_by=?, approved_at=datetime('now','localtime'),
                approval_note=?, is_circuit_broken=0,
                updated_at=datetime('now','localtime')
            WHERE id=?
        """, (approver, note, queue_id))

        return {
            'success':    True,
            'queue_id':   queue_id,
            'approver':   approver,
            'status':     'approved',
            'message':    '✅ 审批通过，等待发布时间窗口',
        }

    def reject(self, queue_id: int, approver: str, reason: str) -> dict:
        """人工驳回"""
        if not reason:
            return {'success': False, 'error': '驳回必须填写原因'}

        execute("""
            UPDATE publish_queue
            SET status='cancelled', approved_by=?, approved_at=datetime('now','localtime'),
                approval_note=?, fail_reason=?, fail_stage='approve',
                updated_at=datetime('now','localtime')
            WHERE id=?
        """, (approver, reason, reason, queue_id))

        return {'success': True, 'queue_id': queue_id, 'status': 'cancelled'}

    def mark_published(self, queue_id: int, publish_record_id: int) -> dict:
        """标记发布成功"""
        execute("""
            UPDATE publish_queue
            SET status='published', publish_record_id=?,
                updated_at=datetime('now','localtime')
            WHERE id=?
        """, (publish_record_id, queue_id))
        return {'success': True, 'queue_id': queue_id}

    def mark_failed(self, queue_id: int, reason: str, stage: str = 'publish') -> dict:
        """标记发布失败，触发熔断检测"""
        # 重试次数检查
        queue = query_one("SELECT retry_count FROM publish_queue WHERE id=?", (queue_id,))
        retry = (queue['retry_count'] if queue else 0) + 1

        new_status = 'failed' if retry >= 3 else 'pending_approve'
        execute("""
            UPDATE publish_queue
            SET status=?, fail_reason=?, fail_stage=?, retry_count=?,
                updated_at=datetime('now','localtime')
            WHERE id=?
        """, (new_status, reason, stage, retry, queue_id))

        # 触发熔断检测
        self.breaker.check_and_trigger(queue_id)

        return {
            'success':    True,
            'queue_id':   queue_id,
            'retry_count': retry,
            'status':     new_status,
        }

    def recheck(self, queue_id: int) -> dict:
        """重新运行发布前检查"""
        execute("""
            UPDATE publish_queue SET status='pending_check',
                updated_at=datetime('now','localtime')
            WHERE id=?
        """, (queue_id,))
        return self.checker.run(queue_id)
