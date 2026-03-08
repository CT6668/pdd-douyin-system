"""
熔断机制 v1.0
──────────────────────────────────────────────────────────────
三级熔断：
  L1 单条熔断  - 单条内容失败 >=3 次
  L2 时段熔断  - 同时段失败率 >50% 或频率过高
  L3 全局熔断  - 当日失败率 >30%（且发布 >=5 条）
"""

import sys
import os
import json
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.db import query, query_one, execute


class CircuitBreaker:

    # ── 全局熔断检查 ──────────────────────────────────────────

    def check_global(self) -> dict:
        """
        检查是否存在激活的全局熔断
        Returns: 熔断记录 dict 或 None
        """
        cb = query_one("""
            SELECT * FROM circuit_breaker_log
            WHERE level='L3' AND status='active'
            ORDER BY created_at DESC LIMIT 1
        """)
        return cb

    def check_time_slot(self, platform: str, time_slot_start: str) -> dict:
        """
        检查某时段是否被熔断
        time_slot_start: YYYY-MM-DD HH:MM
        """
        cb = query_one("""
            SELECT * FROM circuit_breaker_log
            WHERE level='L2' AND status='active'
              AND platform=? AND scope LIKE ?
            ORDER BY created_at DESC LIMIT 1
        """, (platform, f'%{time_slot_start[:13]}%'))
        return cb

    def check_and_trigger(self, queue_id: int) -> list:
        """
        发布失败后调用，检查是否需要触发各级熔断
        Returns: 触发的熔断列表
        """
        triggered = []
        queue = query_one("SELECT * FROM publish_queue WHERE id=?", (queue_id,))
        if not queue:
            return triggered

        platform  = queue.get('platform', 'douyin')
        scheduled = queue.get('scheduled_time', '')

        # L1: 单条熔断（失败 >=3 次）
        if queue.get('retry_count', 0) >= 3:
            cb = self._trigger(
                level='L1',
                reason=f'单条内容失败 {queue["retry_count"]} 次（已达上限）',
                detail={'queue_id': queue_id, 'fail_reason': queue.get('fail_reason')},
                scope=f'queue:{queue_id}',
                platform=platform,
            )
            triggered.append(cb)
            # 标记该条被熔断
            execute("UPDATE publish_queue SET is_circuit_broken=1, status='cancelled' WHERE id=?", (queue_id,))

        # L2: 时段熔断
        l2 = self._check_l2(platform, scheduled)
        if l2:
            cb = self._trigger(**l2)
            triggered.append(cb)
            # 冻结该时段后续队列
            self._freeze_time_slot(platform, scheduled[:13])

        # L3: 全局熔断
        l3 = self._check_l3()
        if l3:
            cb = self._trigger(**l3)
            triggered.append(cb)

        return triggered

    def _check_l2(self, platform: str, scheduled: str) -> dict:
        """L2 检查：1h 内失败率 >50%（且 >=2 条失败）"""
        if not scheduled:
            return None

        try:
            slot_start = datetime.strptime(scheduled[:16], '%Y-%m-%d %H:%M')
            slot_end   = slot_start + timedelta(hours=1)
        except ValueError:
            return None

        # 已存在激活熔断，不重复触发
        existing = self.check_time_slot(platform, scheduled)
        if existing:
            return None

        # 该时段已发布 + 失败数
        slot_s = slot_start.strftime('%Y-%m-%d %H:%M')
        slot_e = slot_end.strftime('%Y-%m-%d %H:%M')

        total_row = query_one("""
            SELECT COUNT(*) c FROM publish_queue
            WHERE platform=? AND scheduled_time BETWEEN ? AND ?
              AND status IN ('published','failed','cancelled')
        """, (platform, slot_s, slot_e))
        fail_row = query_one("""
            SELECT COUNT(*) c FROM publish_queue
            WHERE platform=? AND scheduled_time BETWEEN ? AND ?
              AND status IN ('failed','cancelled') AND fail_stage='publish'
        """, (platform, slot_s, slot_e))

        total = total_row['c'] if total_row else 0
        fail  = fail_row['c']  if fail_row  else 0

        if total >= 2 and fail / total > 0.5:
            return dict(
                level='L2',
                reason=f'时段熔断：{slot_s} 失败率 {fail}/{total} = {fail/total*100:.0f}%（>50%）',
                detail={'slot': slot_s, 'total': total, 'fail': fail},
                scope=f'slot:{slot_s}',
                platform=platform,
            )

        # 1h 内发布 >=5 条（限速）
        published_row = query_one("""
            SELECT COUNT(*) c FROM publish_queue
            WHERE platform=? AND scheduled_time BETWEEN ? AND ?
              AND status='published'
        """, (platform, slot_s, slot_e))
        pub_cnt = published_row['c'] if published_row else 0
        if pub_cnt >= 5:
            return dict(
                level='L2',
                reason=f'限速熔断：{slot_s} 1h 内已发布 {pub_cnt} 条（>=5，批量风险）',
                detail={'slot': slot_s, 'published': pub_cnt},
                scope=f'slot:{slot_s}',
                platform=platform,
            )

        return None

    def _check_l3(self) -> dict:
        """L3 检查：当日失败率 >30%（且 >=5 条已发布/失败）"""
        # 已存在激活全局熔断
        if self.check_global():
            return None

        today = datetime.now().strftime('%Y-%m-%d')
        total_row = query_one("""
            SELECT COUNT(*) c FROM publish_queue
            WHERE DATE(scheduled_time)=?
              AND status IN ('published','failed','cancelled')
        """, (today,))
        fail_row = query_one("""
            SELECT COUNT(*) c FROM publish_queue
            WHERE DATE(scheduled_time)=?
              AND status IN ('failed','cancelled') AND fail_stage='publish'
        """, (today,))

        total = total_row['c'] if total_row else 0
        fail  = fail_row['c']  if fail_row  else 0

        if total >= 5 and fail / total > 0.3:
            return dict(
                level='L3',
                reason=f'全局熔断：今日失败率 {fail}/{total} = {fail/total*100:.0f}%（>30%）',
                detail={'date': today, 'total': total, 'fail': fail},
                scope='global',
                platform=None,
            )
        return None

    def _trigger(self, level: str, reason: str, detail: dict,
                 scope: str, platform: str = None) -> dict:
        """写入熔断日志"""
        cb_id = execute("""
            INSERT INTO circuit_breaker_log
                (level, trigger_reason, trigger_detail, scope, platform, status)
            VALUES (?, ?, ?, ?, ?, 'active')
        """, (level, reason, json.dumps(detail, ensure_ascii=False), scope, platform))

        print(f"🔴 [{level}] 熔断触发：{reason}")
        return {
            'id':             cb_id,
            'level':          level,
            'trigger_reason': reason,
            'scope':          scope,
            'platform':       platform,
        }

    def _freeze_time_slot(self, platform: str, slot_prefix: str):
        """冻结某时段后续所有待发布任务"""
        execute("""
            UPDATE publish_queue
            SET status='cancelled', is_circuit_broken=1,
                fail_reason='时段熔断自动取消',
                updated_at=datetime('now','localtime')
            WHERE platform=? AND scheduled_time LIKE ?
              AND status IN ('approved','pending_approve','checked')
        """, (platform, f'{slot_prefix}%'))

    # ── 解除熔断 ─────────────────────────────────────────────

    def resolve(self, cb_id: int, resolver: str, note: str) -> dict:
        """解除熔断"""
        if not resolver:
            return {'success': False, 'error': '必须填写解除人'}
        if not note:
            return {'success': False, 'error': 'L3 全局熔断解除必须填写原因'}

        cb = query_one("SELECT * FROM circuit_breaker_log WHERE id=?", (cb_id,))
        if not cb:
            return {'success': False, 'error': '熔断记录不存在'}
        if cb['status'] == 'resolved':
            return {'success': False, 'error': '熔断已解除'}

        execute("""
            UPDATE circuit_breaker_log
            SET status='resolved', resolved_by=?,
                resolved_at=datetime('now','localtime'), resolve_note=?
            WHERE id=?
        """, (resolver, note, cb_id))

        return {
            'success':  True,
            'cb_id':    cb_id,
            'level':    cb['level'],
            'resolver': resolver,
            'message':  f'{cb["level"]} 熔断已解除',
        }

    def get_active(self) -> list:
        """查询所有激活的熔断"""
        return query("""
            SELECT * FROM circuit_breaker_log
            WHERE status='active'
            ORDER BY level DESC, created_at DESC
        """)

    def get_history(self, days: int = 7) -> list:
        """熔断历史记录"""
        since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        return query("""
            SELECT * FROM circuit_breaker_log
            WHERE created_at >= ?
            ORDER BY created_at DESC
        """, (since,))
