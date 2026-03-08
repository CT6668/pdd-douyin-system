"""
发布前检查引擎 v1.0
──────────────────────────────────────────────────────────────
8条强制检查 + 风险动作识别
调用：
    from publish.checker import PrePublishChecker
    result = PrePublishChecker().run(queue_id)
"""

import sys
import os
import json
import re
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.db import query, query_one, execute


# ── 高危合规词列表 ────────────────────────────────────────────
HIGH_RISK_WORDS = [
    '国家级', '最高级', '全网第一', '史上最',
    '100%', '永久', '治愈疾病', '根治', '特效',
    '无条件退款', '假一赔十', '官方认证',
]

# 预警关键词（中风险，提示不阻断）
MEDIUM_RISK_WORDS = [
    '最', '第一', '唯一', '极', '纯天然', '无副作用',
    '无添加', '绿色', '有机', '秒杀', '最低价',
]


class CheckResult:
    """单项检查结果"""
    PASS    = 'pass'
    WARNING = 'warning'
    FAIL    = 'fail'

    def __init__(self, name: str, status: str, message: str, detail=None):
        self.name    = name
        self.status  = status
        self.message = message
        self.detail  = detail

    def to_dict(self):
        return {
            'name':    self.name,
            'status':  self.status,
            'message': self.message,
            'detail':  self.detail,
        }


class PrePublishChecker:
    """发布前检查引擎"""

    def run(self, queue_id: int) -> dict:
        """
        运行全部检查，返回汇总结果
        Returns:
          {
            'queue_id': int,
            'overall': 'pass' | 'warning' | 'fail',
            'check_passed': 1 | 2 | 3,
            'checks': [ CheckResult.to_dict(), ... ],
            'risk_level': 'none' | 'low' | 'medium' | 'high',
            'risk_flags': [ str, ... ],
          }
        """
        queue = query_one("SELECT * FROM publish_queue WHERE id=?", (queue_id,))
        if not queue:
            return {'error': f'队列记录 {queue_id} 不存在'}

        content_id = queue['content_task_id']
        product_id = queue['product_id']
        platform   = queue['platform']
        scheduled  = queue['scheduled_time']

        content = query_one("SELECT * FROM content_tasks WHERE id=?", (content_id,))
        product = query_one("SELECT * FROM product_pool  WHERE id=?", (product_id,))

        results  = []
        risk_flags = []

        # ── 必通检查 ─────────────────────────────────────────

        # 1. 脚本状态
        results.append(self._check_script_status(content))

        # 2. 素材完整性
        results.append(self._check_materials(content_id))

        # 3. 发布时间合理性
        results.append(self._check_scheduled_time(scheduled))

        # 4. 商品有效性
        results.append(self._check_product_status(product))

        # 5. 合规词检查
        r5, rf5 = self._check_compliance(content)
        results.append(r5)
        risk_flags.extend(rf5)

        # ── 警告检查 ─────────────────────────────────────────

        # 6. 重复发布检查
        results.append(self._check_duplicate(product_id, platform, content_id))

        # 7. 佣金链接检查
        results.append(self._check_commission_link(content, product))

        # 8. 发布时段建议
        results.append(self._check_time_slot(scheduled, content))

        # ── 风险动作识别 ──────────────────────────────────────
        risk_flags.extend(self._identify_risks(queue, content, product))

        # ── 汇总 ─────────────────────────────────────────────
        has_fail    = any(r.status == CheckResult.FAIL    for r in results)
        has_warning = any(r.status == CheckResult.WARNING for r in results)

        if has_fail:
            overall      = CheckResult.FAIL
            check_passed = 3
        elif has_warning:
            overall      = CheckResult.WARNING
            check_passed = 2
        else:
            overall      = CheckResult.PASS
            check_passed = 1

        # 风险等级
        if any('HIGH' in f for f in risk_flags):
            risk_level = 'high'
        elif any('MEDIUM' in f for f in risk_flags):
            risk_level = 'medium'
        elif risk_flags:
            risk_level = 'low'
        else:
            risk_level = 'none'

        summary = {
            'queue_id':     queue_id,
            'overall':      overall,
            'check_passed': check_passed,
            'checks':       [r.to_dict() for r in results],
            'risk_level':   risk_level,
            'risk_flags':   risk_flags,
        }

        # 回写数据库
        execute("""
            UPDATE publish_queue
            SET check_passed=?, check_result=?, checked_at=?,
                risk_level=?, risk_flags=?,
                status = CASE WHEN ? = 3 THEN 'check_failed'
                              ELSE 'checked' END,
                updated_at=datetime('now','localtime')
            WHERE id=?
        """, (
            check_passed,
            json.dumps(summary['checks'], ensure_ascii=False),
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            risk_level,
            json.dumps(risk_flags, ensure_ascii=False),
            check_passed,
            queue_id,
        ))

        # 若 risk=high，强制要求 override
        if risk_level == 'high':
            execute("""
                UPDATE publish_queue SET is_circuit_broken=1,
                    status='pending_approve', updated_at=datetime('now','localtime')
                WHERE id=?
            """, (queue_id,))
            summary['note'] = '⚠️ 高风险：已标记需人工 override 才可发布'
        elif check_passed <= 2:
            execute("""
                UPDATE publish_queue SET status='pending_approve',
                    updated_at=datetime('now','localtime')
                WHERE id=?
            """, (queue_id,))

        return summary

    # ── 具体检查函数 ──────────────────────────────────────────

    def _check_script_status(self, content) -> CheckResult:
        name = '脚本状态检查'
        if not content:
            return CheckResult(name, CheckResult.FAIL, '脚本不存在')
        if content['status'] == 'approved':
            return CheckResult(name, CheckResult.PASS, '✅ 脚本已通过人工审核')
        return CheckResult(name, CheckResult.FAIL,
                           f'❌ 脚本状态为 {content["status"]}，必须 approved 才可发布',
                           {'current_status': content['status']})

    def _check_materials(self, content_id) -> CheckResult:
        name  = '素材完整性检查'
        total = query_one("SELECT COUNT(*) c FROM material_render_tasks WHERE content_task_id=?", (content_id,))
        done  = query_one("SELECT COUNT(*) c FROM material_render_tasks WHERE content_task_id=? AND status='done'", (content_id,))
        t = total['c'] if total else 0
        d = done['c']  if done  else 0
        if t == 0:
            return CheckResult(name, CheckResult.FAIL, '❌ 无任何素材渲染记录')
        if d == 0:
            return CheckResult(name, CheckResult.FAIL,
                               f'❌ {t} 条素材全部未完成（status 非 done）',
                               {'total': t, 'done': d})
        if d < t:
            return CheckResult(name, CheckResult.WARNING,
                               f'⚠️ 素材 {d}/{t} 已完成，可发布但建议补全',
                               {'total': t, 'done': d})
        return CheckResult(name, CheckResult.PASS, f'✅ {d}/{t} 条素材全部就绪')

    def _check_scheduled_time(self, scheduled) -> CheckResult:
        name = '发布时间合理性'
        try:
            st = datetime.strptime(scheduled, '%Y-%m-%d %H:%M')
        except ValueError:
            try:
                st = datetime.strptime(scheduled, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return CheckResult(name, CheckResult.FAIL, f'❌ 时间格式错误：{scheduled}')

        now    = datetime.now()
        delta  = (st - now).total_seconds() / 60

        if delta < -5:
            return CheckResult(name, CheckResult.FAIL,
                               f'❌ 计划时间已过期（{scheduled}）',
                               {'scheduled': scheduled, 'now': now.strftime('%Y-%m-%d %H:%M')})
        if delta < 30:
            return CheckResult(name, CheckResult.WARNING,
                               f'⚠️ 发布时间不足 30 分钟（{delta:.0f}min 后），留给审批的时间很短',
                               {'minutes_left': round(delta)})
        return CheckResult(name, CheckResult.PASS,
                           f'✅ 发布时间合理，距发布 {delta/60:.1f}h')

    def _check_product_status(self, product) -> CheckResult:
        name = '商品有效性检查'
        if not product:
            return CheckResult(name, CheckResult.FAIL, '❌ 商品不存在')
        if product['status'] in ('selected', 'scored'):
            return CheckResult(name, CheckResult.PASS,
                               f'✅ 商品状态正常（{product["status"]}）')
        if product['status'] == 'rejected':
            return CheckResult(name, CheckResult.FAIL,
                               f'❌ 商品已被拒绝（{product["title"][:20]}）')
        return CheckResult(name, CheckResult.WARNING,
                           f'⚠️ 商品状态为 {product["status"]}，建议确认是否有效')

    def _check_compliance(self, content) -> tuple:
        name = '合规词检查'
        if not content:
            return CheckResult(name, CheckResult.FAIL, '❌ 无内容'), []

        # 拼接所有文本
        text = ' '.join([
            content.get('cover_copy', '') or '',
            content.get('hook_3s', '') or '',
            content.get('subtitle', '') or '',
            content.get('voiceover', '') or '',
            content.get('xhs_body', '') or '',
            content.get('title', '') or '',
        ])

        risk_flags = []
        hit_high   = [w for w in HIGH_RISK_WORDS   if w in text]
        hit_medium = [w for w in MEDIUM_RISK_WORDS if w in text]

        if hit_high:
            risk_flags.append(f'[HIGH] 高危合规词：{hit_high}')
            return CheckResult(name, CheckResult.FAIL,
                               f'❌ 含高危违规词：{hit_high}',
                               {'hit': hit_high}), risk_flags

        if hit_medium:
            risk_flags.append(f'[MEDIUM] 预警关键词：{hit_medium}')
            return CheckResult(name, CheckResult.WARNING,
                               f'⚠️ 含预警词（需人工确认）：{hit_medium}',
                               {'hit': hit_medium}), risk_flags

        return CheckResult(name, CheckResult.PASS, '✅ 未检测到违规关键词'), risk_flags

    def _check_duplicate(self, product_id, platform, content_id) -> CheckResult:
        name = '重复发布检查'
        # 24h 内同商品同平台是否已发布
        yesterday = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
        recent = query_one("""
            SELECT COUNT(*) c FROM publish_records pr
            WHERE pr.product_id = ?
              AND pr.platform   = ?
              AND pr.pub_time  >= ?
              AND pr.status     = 'published'
        """, (product_id, platform, yesterday))
        count = recent['c'] if recent else 0
        if count >= 3:
            return CheckResult(name, CheckResult.FAIL,
                               f'❌ 24h 内该商品已发布 {count} 条，超限（刷量风险）',
                               {'count_24h': count})
        if count >= 1:
            return CheckResult(name, CheckResult.WARNING,
                               f'⚠️ 24h 内该商品已发布 {count} 条，请确认是否必要',
                               {'count_24h': count})
        return CheckResult(name, CheckResult.PASS, '✅ 24h 内无重复发布记录')

    def _check_commission_link(self, content, product) -> CheckResult:
        name = '佣金链接检查'
        if not content or not product:
            return CheckResult(name, CheckResult.WARNING, '⚠️ 无法验证（数据缺失）')
        has_mount   = bool(content.get('mount_suggest'))
        has_pdd_url = bool(product.get('pdd_url'))
        if has_mount and has_pdd_url:
            return CheckResult(name, CheckResult.PASS, '✅ 商品挂载建议 + 拼多多链接均已就绪')
        if not has_pdd_url:
            return CheckResult(name, CheckResult.WARNING, '⚠️ 商品无拼多多链接，无法追踪转化')
        return CheckResult(name, CheckResult.WARNING, '⚠️ 缺少挂载建议，建议补充商品挂载方式')

    def _check_time_slot(self, scheduled, content) -> CheckResult:
        name = '发布时段建议'
        try:
            st   = datetime.strptime(scheduled[:16], '%Y-%m-%d %H:%M')
            hour = st.hour
        except Exception:
            return CheckResult(name, CheckResult.WARNING, '⚠️ 无法解析发布时间')

        # 抖音黄金时段
        golden_slots = [(7,9), (12,14), (20,22)]
        in_golden = any(s <= hour < e for s, e in golden_slots)

        suggest = content.get('pub_time_suggest', '') if content else ''

        if in_golden:
            return CheckResult(name, CheckResult.PASS,
                               f'✅ {hour}:00 处于黄金发布时段')
        return CheckResult(name, CheckResult.WARNING,
                           f'⚠️ {hour}:00 非建议时段（黄金时段：7-9点/12-14点/20-22点）',
                           {'suggested': suggest})

    def _identify_risks(self, queue, content, product) -> list:
        """识别所有风险动作，返回 risk_flags 列表"""
        flags = []

        if not content:
            return flags

        # HIGH: 未经人工审核
        if not content.get('reviewer'):
            flags.append('[HIGH] 脚本未设置审核人 reviewer（可能未经人工核查）')

        # HIGH: 封面含价格词 + 无实际商品挂载
        cover_text = content.get('cover_copy', '') or ''
        price_pattern = re.search(r'\d+\.?\d*\s*[元块]|¥\d+|\d+折', cover_text)
        if price_pattern and not content.get('mount_suggest'):
            flags.append('[HIGH] 封面含价格词但无商品挂载（虚假促销风险）')

        # HIGH: 6h 内同商品已发布 >=2 条
        six_hours_ago = (datetime.now() - timedelta(hours=6)).strftime('%Y-%m-%d %H:%M:%S')
        recent_6h = query_one("""
            SELECT COUNT(*) c FROM publish_records
            WHERE product_id=? AND platform=? AND pub_time>=? AND status='published'
        """, (queue['product_id'], queue['platform'], six_hours_ago))
        cnt6h = recent_6h['c'] if recent_6h else 0
        if cnt6h >= 2:
            flags.append(f'[HIGH] 6h 内同商品已发布 {cnt6h} 条（疑似刷量）')

        # MEDIUM: 素材仅 AI 生成
        mat_manual = query_one("""
            SELECT COUNT(*) c FROM material_render_tasks
            WHERE content_task_id=? AND status='done' AND source_key_point IS NOT NULL
        """, (queue['content_task_id'],))
        # 如果没有人工上传记录（filepath 包含 manual/）
        mat_manual2 = query_one("""
            SELECT COUNT(*) c FROM material_render_tasks
            WHERE content_task_id=? AND filepath LIKE '%manual%'
        """, (queue['content_task_id'],))
        if (mat_manual2['c'] if mat_manual2 else 0) == 0:
            flags.append('[MEDIUM] 素材仅为 AI 合成，未包含人工上传的真实商品图')

        # MEDIUM: 脚本含预警词
        text_full = ' '.join([
            content.get('cover_copy', '') or '',
            content.get('hook_3s', '') or '',
        ])
        hit_medium = [w for w in MEDIUM_RISK_WORDS if w in text_full]
        if hit_medium:
            flags.append(f'[MEDIUM] 脚本含预警关键词：{hit_medium}')

        # MEDIUM: 当日待发布队列已有 >=10 条
        today = datetime.now().strftime('%Y-%m-%d')
        queue_today = query_one("""
            SELECT COUNT(*) c FROM publish_queue
            WHERE DATE(scheduled_time)=? AND status NOT IN ('published','cancelled','failed')
        """, (today,))
        cnt_today = queue_today['c'] if queue_today else 0
        if cnt_today >= 10:
            flags.append(f'[MEDIUM] 今日待发布队列已有 {cnt_today} 条（批量发布风险）')

        # LOW: 商品评分低
        if product and product.get('status') == 'pending':
            flags.append('[LOW] 商品未完成评分，质量未经系统验证')

        return flags
