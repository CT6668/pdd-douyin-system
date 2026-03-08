"""
数据回传模块 v1.0
──────────────────────────────────────────────────────────────
职责：
  - 手动录入发布后的表现数据
  - 批量导入 CSV/JSON 数据
  - 数据质量验证
  - 回传后触发复盘摘要更新
"""

import sys
import os
import json
import csv
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from backend.db import query, query_one, execute


# ── 回传字段规范 ─────────────────────────────────────────────
PERF_FIELDS = {
    # field_name: (type, required, description, min, max)
    'impressions':       ('int',   True,  '曝光量',     0,   None),
    'plays':             ('int',   False, '播放量',     0,   None),
    'completion_rate':   ('float', False, '完播率',     0.0, 1.0),
    'likes':             ('int',   False, '点赞数',     0,   None),
    'like_rate':         ('float', False, '点赞率',     0.0, 1.0),
    'comments':          ('int',   False, '评论数',     0,   None),
    'comment_rate':      ('float', False, '评论率',     0.0, 1.0),
    'shares':            ('int',   False, '分享数',     0,   None),
    'saves':             ('int',   False, '收藏数',     0,   None),
    'product_clicks':    ('int',   False, '商品点击数', 0,   None),
    'product_ctr':       ('float', False, '商品点击率', 0.0, 1.0),
    'orders':            ('int',   True,  '成交数',     0,   None),
    'gmv':               ('float', True,  'GMV（元）',  0.0, None),
    'commission':        ('float', True,  '佣金（元）', 0.0, None),
    'pub_exception':     ('str',   False, '发布异常描述', None, None),
    'risk_hint':         ('str',   False, '风险提示',  None, None),
}


class PerformanceTracker:

    # ── 单条录入 ─────────────────────────────────────────────

    def record(self, publish_record_id: int, data: dict,
               data_source: str = 'manual') -> dict:
        """
        录入单条发布表现数据
        publish_record_id: publish_records.id
        data: 包含 PERF_FIELDS 中字段的 dict
        """
        # 验证
        validation = self._validate(data)
        if not validation['valid']:
            return {'success': False, 'errors': validation['errors']}

        # 获取关联信息
        pr = query_one("""
            SELECT pr.*, pq.check_result, pq.risk_flags,
                   ct.id AS content_task_id, ct.script_type, ct.platform
            FROM publish_records pr
            LEFT JOIN publish_queue pq ON pq.publish_record_id = pr.id
            LEFT JOIN content_tasks ct ON ct.id = pr.content_task_id
            WHERE pr.id = ?
        """, (publish_record_id,))

        if not pr:
            return {'success': False, 'error': f'发布记录 {publish_record_id} 不存在'}

        record_date = data.get('record_date',
                               (pr.get('pub_time') or datetime.now().strftime('%Y-%m-%d'))[:10])

        # 计算派生指标
        impressions = int(data.get('impressions', 0) or 0)
        data = self._derive_rates(data, impressions)

        # 数据延迟计算
        pub_time_str = pr.get('actual_pub_time') or pr.get('pub_time') or ''
        data_lag = self._calc_lag(pub_time_str)

        # 风险提示：来自队列的 risk_flags
        risk_hint = data.get('risk_hint') or pr.get('risk_flags') or '[]'

        # 写入 performance_data
        perf_id = execute("""
            INSERT OR REPLACE INTO performance_data (
                publish_id, product_id, content_task_id, platform,
                record_date,
                impressions, plays, completion_rate, avg_watch_pct,
                likes, like_rate, comments, comment_rate,
                shares, saves,
                product_clicks, product_ctr,
                orders, gmv, commission,
                ctr, cvr, roi,
                pub_exception, risk_hint, data_lag_hours,
                data_source, notes
            ) VALUES (
                ?, ?, ?, ?,
                ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?
            )
        """, (
            publish_record_id,
            pr.get('product_id'),
            pr.get('content_task_id'),
            pr.get('platform', 'douyin'),
            record_date,

            impressions,
            int(data.get('plays', 0) or 0),
            float(data.get('completion_rate', 0) or 0),
            float(data.get('avg_watch_pct', 0) or 0),

            int(data.get('likes', 0) or 0),
            float(data.get('like_rate', 0) or 0),
            int(data.get('comments', 0) or 0),
            float(data.get('comment_rate', 0) or 0),

            int(data.get('shares', 0) or 0),
            int(data.get('saves', 0) or 0),

            int(data.get('product_clicks', 0) or 0),
            float(data.get('product_ctr', 0) or 0),

            int(data.get('orders', 0) or 0),
            float(data.get('gmv', 0) or 0),
            float(data.get('commission', 0) or 0),

            float(data.get('ctr', 0) or 0),
            float(data.get('cvr', 0) or 0),
            float(data.get('roi', 0) or 0),

            str(data.get('pub_exception', '') or ''),
            str(risk_hint),
            data_lag,

            data_source,
            str(data.get('notes', '') or ''),
        ))

        # 同步更新 publish_records
        if data.get('pub_exception'):
            execute("""
                UPDATE publish_records SET pub_exception=? WHERE id=?
            """, (data['pub_exception'], publish_record_id))

        return {
            'success':    True,
            'perf_id':    perf_id,
            'record_date': record_date,
            'summary':    self._build_summary(data, impressions),
        }

    def record_by_content(self, content_task_id: int, data: dict,
                           data_source: str = 'manual') -> dict:
        """通过 content_task_id 录入（自动关联最新 publish_record）"""
        pr = query_one("""
            SELECT id FROM publish_records
            WHERE content_task_id=?
            ORDER BY created_at DESC LIMIT 1
        """, (content_task_id,))

        if not pr:
            return {'success': False, 'error': f'content_task_id={content_task_id} 无发布记录，请先完成发布'}

        return self.record(pr['id'], data, data_source)

    # ── 批量导入 ─────────────────────────────────────────────

    def import_csv(self, csv_path: str) -> dict:
        """
        批量从 CSV 导入表现数据
        CSV 必须包含列：publish_record_id 或 content_task_id + impressions + orders + gmv + commission
        """
        if not os.path.exists(csv_path):
            return {'success': False, 'error': f'文件不存在：{csv_path}'}

        results  = []
        success  = 0
        fail     = 0

        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for i, row in enumerate(reader, 1):
                try:
                    # 数值转换
                    data = {}
                    for k, v in row.items():
                        k = k.strip()
                        if k in ('impressions', 'plays', 'likes', 'comments',
                                 'shares', 'saves', 'product_clicks', 'orders'):
                            data[k] = int(v or 0)
                        elif k in ('completion_rate', 'like_rate', 'comment_rate',
                                   'product_ctr', 'gmv', 'commission', 'ctr', 'cvr', 'roi'):
                            data[k] = float(v or 0)
                        else:
                            data[k] = v.strip() if v else ''

                    # 确定发布记录ID
                    if 'publish_record_id' in data and data['publish_record_id']:
                        r = self.record(int(data['publish_record_id']), data, 'csv_import')
                    elif 'content_task_id' in data and data['content_task_id']:
                        r = self.record_by_content(int(data['content_task_id']), data, 'csv_import')
                    else:
                        r = {'success': False, 'error': '缺少 publish_record_id 或 content_task_id'}

                    results.append({'row': i, **r})
                    if r.get('success'):
                        success += 1
                    else:
                        fail += 1

                except Exception as e:
                    results.append({'row': i, 'success': False, 'error': str(e)})
                    fail += 1

        return {
            'success':  True,
            'total':    success + fail,
            'imported': success,
            'failed':   fail,
            'details':  results,
        }

    # ── 查询 ─────────────────────────────────────────────────

    def get_daily_summary(self, date: str = None) -> dict:
        """当日表现汇总"""
        if not date:
            date = datetime.now().strftime('%Y-%m-%d')

        row = query_one("""
            SELECT
                COUNT(DISTINCT pd.publish_id)     AS pub_count,
                SUM(pd.impressions)               AS total_impressions,
                AVG(pd.completion_rate)           AS avg_completion_rate,
                AVG(pd.like_rate)                 AS avg_like_rate,
                AVG(pd.comment_rate)              AS avg_comment_rate,
                AVG(pd.product_ctr)               AS avg_product_ctr,
                SUM(pd.orders)                    AS total_orders,
                SUM(pd.gmv)                       AS total_gmv,
                SUM(pd.commission)                AS total_commission
            FROM performance_data pd
            WHERE pd.record_date = ?
        """, (date,))

        return {'date': date, 'summary': row or {}}

    def get_content_performance(self, content_task_id: int) -> dict:
        """单条内容的完整表现数据"""
        rows = query("""
            SELECT pd.*, pr.pub_time, pr.platform, pr.status AS pub_status
            FROM performance_data pd
            JOIN publish_records pr ON pr.id = pd.publish_id
            WHERE pd.content_task_id = ?
            ORDER BY pd.record_date DESC
        """, (content_task_id,))
        return {'content_task_id': content_task_id, 'records': rows}

    # ── 工具函数 ─────────────────────────────────────────────

    def _validate(self, data: dict) -> dict:
        """数据验证"""
        errors = []
        for field, (ftype, required, desc, fmin, fmax) in PERF_FIELDS.items():
            val = data.get(field)
            if required and (val is None or val == ''):
                errors.append(f'{field}（{desc}）为必填项')
                continue
            if val is None or val == '':
                continue
            try:
                if ftype == 'int':
                    val = int(val)
                elif ftype == 'float':
                    val = float(val)
            except (ValueError, TypeError):
                errors.append(f'{field} 类型错误（应为 {ftype}）')
                continue
            if fmin is not None and val < fmin:
                errors.append(f'{field} 值 {val} 不能小于 {fmin}')
            if fmax is not None and val > fmax:
                errors.append(f'{field}（{desc}）值 {val} 超出范围（max={fmax}）')

        return {'valid': len(errors) == 0, 'errors': errors}

    def _derive_rates(self, data: dict, impressions: int) -> dict:
        """自动计算派生比率（如果原始数据已有则不覆盖）"""
        if impressions <= 0:
            return data

        def safe_rate(numerator_key, rate_key):
            if not data.get(rate_key) and data.get(numerator_key):
                data[rate_key] = round(int(data[numerator_key] or 0) / impressions, 6)

        safe_rate('likes',          'like_rate')
        safe_rate('comments',       'comment_rate')
        safe_rate('product_clicks', 'product_ctr')
        safe_rate('plays',          'ctr')

        # CVR = orders / product_clicks
        pc = int(data.get('product_clicks', 0) or 0)
        if pc > 0 and not data.get('cvr'):
            data['cvr'] = round(int(data.get('orders', 0) or 0) / pc, 6)

        # ROI = gmv / (commission 成本 proxy)
        # 这里简化：ROI 不自动计算，需手动填入

        return data

    def _calc_lag(self, pub_time_str: str) -> float:
        """计算数据延迟小时数"""
        if not pub_time_str:
            return 0.0
        try:
            pt  = datetime.strptime(pub_time_str[:16], '%Y-%m-%d %H:%M')
            lag = (datetime.now() - pt).total_seconds() / 3600
            return round(max(lag, 0), 2)
        except ValueError:
            return 0.0

    def _build_summary(self, data: dict, impressions: int) -> dict:
        return {
            'impressions':     impressions,
            'orders':          data.get('orders', 0),
            'gmv':             data.get('gmv', 0),
            'commission':      data.get('commission', 0),
            'completion_rate': f"{float(data.get('completion_rate', 0) or 0)*100:.1f}%",
            'like_rate':       f"{float(data.get('like_rate', 0) or 0)*100:.2f}%",
            'product_ctr':     f"{float(data.get('product_ctr', 0) or 0)*100:.2f}%",
        }


# ── 字段规范输出（供参考）───────────────────────────────────
def print_field_spec():
    print("\n回传数据字段规范：")
    print(f"{'字段名':<22} {'类型':<8} {'必填':<6} {'说明'}")
    print("-" * 60)
    for field, (ftype, required, desc, fmin, fmax) in PERF_FIELDS.items():
        req_mark = '✅' if required else '  '
        range_str = ''
        if fmin is not None or fmax is not None:
            range_str = f' [{fmin or 0}-{fmax or "∞"}]'
        print(f"{field:<22} {ftype:<8} {req_mark}  {desc}{range_str}")


if __name__ == '__main__':
    print_field_spec()
