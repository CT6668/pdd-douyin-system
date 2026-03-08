"""
商品评分模块（13维评分卡）
支持：手动打分 / 半自动打分（规则推导）

使用方法：
    from scoring.scorer import ProductScorer
    scorer = ProductScorer()

    # 手动打分（适合MVP阶段）
    scores = scorer.score_manual(product_id=1, scores_dict={
        "s01_pdd_heat": 8,
        "s04_douyin_fit": 9,
        ...
    })

    # 自动规则打分（部分维度可根据数据自动计算）
    scores = scorer.score_auto(product_data={
        "price": 29.9,
        "sales_7d": 1200,
        "commission_rate": 15,
        ...
    })
"""

import sqlite3
import json
from datetime import date
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db" / "main.db"


# ─────────────────────────────────────────────
# 13维评分维度定义
# ─────────────────────────────────────────────
SCORE_DIMENSIONS = [
    {
        "key": "s01_pdd_heat",
        "name": "拼多多热度",
        "weight_key": "w01_pdd_heat",
        "desc": "商品在拼多多的当前搜索热度和销量热度",
        "auto_rule": "by_sales_30d",       # 可自动计算
        "score_guide": {
            10: "月销10w+，搜索排名前3",
            8:  "月销5w+，搜索前10",
            6:  "月销1w+，搜索前50",
            4:  "月销5000+",
            2:  "月销<5000，热度低",
        }
    },
    {
        "key": "s02_growth_7d",
        "name": "近7天增速",
        "weight_key": "w02_growth_7d",
        "desc": "近7天销量相比上一个7天的增长率",
        "auto_rule": "by_sales_7d_vs_30d",
        "score_guide": {
            10: "增速>50%，强劲上升",
            8:  "增速20%-50%",
            6:  "增速5%-20%，平稳增长",
            4:  "增速<5%，基本持平",
            2:  "下降趋势",
        }
    },
    {
        "key": "s03_trend_30d",
        "name": "近30天趋势",
        "weight_key": "w03_trend_30d",
        "desc": "商品30天内的整体市场趋势",
        "auto_rule": None,                  # 需手动
        "score_guide": {
            10: "持续上升，30天内新品",
            8:  "稳中有升",
            6:  "平稳期",
            4:  "开始下滑",
            2:  "明显下滑，接近退热",
        }
    },
    {
        "key": "s04_douyin_fit",
        "name": "抖音传播适配度",
        "weight_key": "w04_douyin_fit",
        "desc": "商品在抖音短视频场景下的传播适配程度（权重最高）",
        "auto_rule": None,
        "score_guide": {
            10: "强视觉冲击，0解释，看1秒就懂，适合15s内展示",
            8:  "视觉不错，几乎不需要解释，容易种草",
            6:  "需要简单介绍，但不复杂，1-2个镜头能说清",
            4:  "需要一定解释成本，展示效果一般",
            2:  "很难用短视频展示，解释成本极高",
        }
    },
    {
        "key": "s05_visual_strength",
        "name": "视觉展示强度",
        "weight_key": "w05_visual_strength",
        "desc": "商品外观/使用场景的视觉冲击力",
        "auto_rule": None,
        "score_guide": {
            10: "颜值极高或反差极强，拍出来就能停留",
            8:  "视觉效果好，容易出好画面",
            6:  "普通商品，正常拍摄可以",
            4:  "外观普通，需要技巧才能拍好",
            2:  "外观无感，拍出来效果差",
        }
    },
    {
        "key": "s06_low_explain",
        "name": "低解释成本",
        "weight_key": "w06_low_explain",
        "desc": "用户看到商品后，不需要太多解释就能理解它的用途和价值",
        "auto_rule": None,
        "score_guide": {
            10: "看图即懂，0解释（如：有趣的桌面摆件）",
            8:  "1句话就能说清楚",
            6:  "需要2-3句解释",
            4:  "需要较多解释才能理解价值",
            2:  "复杂产品，需要大量解释",
        }
    },
    {
        "key": "s07_low_decision",
        "name": "低决策成本",
        "weight_key": "w07_low_decision",
        "desc": "用户购买时的决策门槛低，容易冲动下单",
        "auto_rule": None,
        "score_guide": {
            10: "看到就想买，不需要考虑（如：9.9送朋友）",
            8:  "几乎不需要考虑，买了不后悔",
            6:  "稍微想一想，但门槛不高",
            4:  "需要比价、研究一下",
            2:  "决策成本高，需要认真想",
        }
    },
    {
        "key": "s08_impulse_price",
        "name": "价格带冲动消费适合度",
        "weight_key": "w08_impulse_price",
        "desc": "价格区间是否落在容易冲动消费的范围内",
        "auto_rule": "by_price",
        "score_guide": {
            10: "9.9-29.9元，几乎无决策成本",
            8:  "30-49元，略微考虑即下单",
            6:  "50-79元，有一点决策门槛",
            4:  "80-99元，需要思考",
            2:  "100元以上，非冲动消费",
        }
    },
    {
        "key": "s09_commission_val",
        "name": "佣金价值",
        "weight_key": "w09_commission_val",
        "desc": "单件佣金金额和佣金比例的综合评估",
        "auto_rule": "by_commission",
        "score_guide": {
            10: "单件佣金≥5元 且 佣金比例≥20%",
            8:  "单件佣金3-5元 或 比例15%+",
            6:  "单件佣金1-3元",
            4:  "单件佣金0.5-1元",
            2:  "单件佣金<0.5元，几乎无利",
        }
    },
    {
        "key": "s10_competition",
        "name": "竞争难度（取反：低竞争=高分）",
        "weight_key": "w10_competition",
        "desc": "抖音上同类内容的竞争程度，竞争越低得分越高",
        "auto_rule": None,
        "score_guide": {
            10: "几乎没有同款内容，蓝海",
            8:  "少量竞争，内容差异化空间大",
            6:  "有一定竞争，但可以差异化",
            4:  "竞争较激烈，内容大量重复",
            2:  "红海，同款内容泛滥",
        }
    },
    {
        "key": "s11_supply_stable",
        "name": "供给稳定性",
        "weight_key": "w11_supply_stable",
        "desc": "商品库存和店铺供给的稳定性",
        "auto_rule": None,
        "score_guide": {
            10: "大店、库存充足、长期在售",
            8:  "供给稳定，店铺信誉好",
            6:  "基本稳定，偶有缺货",
            4:  "库存不稳，有风险",
            2:  "小店、库存少、随时可能下架",
        }
    },
    {
        "key": "s12_compliance_risk",
        "name": "合规风险（取反：低风险=高分）",
        "weight_key": "w12_compliance_risk",
        "desc": "商品内容的合规风险等级，风险越低得分越高",
        "auto_rule": None,
        "score_guide": {
            10: "纯装饰/有趣小物，合规风险极低",
            8:  "日用品，合规要求低",
            6:  "需要注意措辞，但风险可控",
            4:  "容易触碰夸大宣传红线",
            2:  "高风险品类（健康/食品/美容功效等）",
        }
    },
    {
        "key": "s13_refund_risk",
        "name": "退货/售后风险（取反：低风险=高分）",
        "weight_key": "w13_refund_risk",
        "desc": "商品的退货率和售后复杂程度，越低得分越高",
        "auto_rule": None,
        "score_guide": {
            10: "小物件，退货率极低，售后几乎无",
            8:  "退货率低，售后简单",
            6:  "一般退货率",
            4:  "有一定退货率，需注意",
            2:  "高退货品类（尺码/色差/期望差）",
        }
    },
]


class ProductScorer:
    """商品评分器"""

    def __init__(self, db_path: str = None, config: dict = None):
        self.db_path = db_path or str(DB_PATH)
        self.config = config or {}
        self._weights = self._load_weights()

    def _load_weights(self) -> dict:
        """从数据库加载当前生效的权重配置"""
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT * FROM score_weights WHERE is_active=1 ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            conn.close()
            if row:
                cols = [d[0] for d in cur.description] if cur.description else []
                return dict(zip(cols, row))
        except Exception:
            pass
        # 返回默认权重
        return {dim["weight_key"]: 0.077 for dim in SCORE_DIMENSIONS}  # 均等分配

    def score_auto_partial(self, product_data: dict) -> dict:
        """
        对可自动计算的维度进行规则打分
        返回：{维度key: 分数} 字典，未能自动计算的维度不包含
        """
        auto_scores = {}

        price = product_data.get("price", 0)
        sales_30d = product_data.get("sales_30d", 0)
        sales_7d = product_data.get("sales_7d", 0)
        commission_rate = product_data.get("commission_rate", 0)
        commission_amt = product_data.get("commission_amt", 0)

        # s01：拼多多热度（基于月销量）
        if sales_30d > 0:
            if sales_30d >= 100000:
                auto_scores["s01_pdd_heat"] = 10
            elif sales_30d >= 50000:
                auto_scores["s01_pdd_heat"] = 8
            elif sales_30d >= 10000:
                auto_scores["s01_pdd_heat"] = 6
            elif sales_30d >= 5000:
                auto_scores["s01_pdd_heat"] = 4
            else:
                auto_scores["s01_pdd_heat"] = 2

        # s02：近7天增速（7日销量/月均日销 的倍数）
        if sales_30d > 0 and sales_7d > 0:
            avg_daily_30d = sales_30d / 30
            avg_daily_7d = sales_7d / 7
            growth_ratio = avg_daily_7d / avg_daily_30d if avg_daily_30d > 0 else 1
            if growth_ratio >= 1.5:
                auto_scores["s02_growth_7d"] = 10
            elif growth_ratio >= 1.2:
                auto_scores["s02_growth_7d"] = 8
            elif growth_ratio >= 1.05:
                auto_scores["s02_growth_7d"] = 6
            elif growth_ratio >= 0.95:
                auto_scores["s02_growth_7d"] = 4
            else:
                auto_scores["s02_growth_7d"] = 2

        # s08：价格带
        if price > 0:
            if price <= 29.9:
                auto_scores["s08_impulse_price"] = 10
            elif price <= 49:
                auto_scores["s08_impulse_price"] = 8
            elif price <= 79:
                auto_scores["s08_impulse_price"] = 6
            elif price <= 99:
                auto_scores["s08_impulse_price"] = 4
            else:
                auto_scores["s08_impulse_price"] = 2

        # s09：佣金价值
        if commission_amt > 0 or commission_rate > 0:
            # 计算单件佣金
            if commission_amt == 0 and price > 0 and commission_rate > 0:
                commission_amt = price * commission_rate / 100
            if commission_amt >= 5 and commission_rate >= 20:
                auto_scores["s09_commission_val"] = 10
            elif commission_amt >= 3 or commission_rate >= 15:
                auto_scores["s09_commission_val"] = 8
            elif commission_amt >= 1:
                auto_scores["s09_commission_val"] = 6
            elif commission_amt >= 0.5:
                auto_scores["s09_commission_val"] = 4
            else:
                auto_scores["s09_commission_val"] = 2

        return auto_scores

    def calc_total_score(self, scores_dict: dict) -> float:
        """
        计算加权总分（0-100）
        scores_dict：{维度key: 分数(0-10)} 字典
        """
        total = 0.0
        weight_sum = 0.0
        for dim in SCORE_DIMENSIONS:
            key = dim["key"]
            w_key = dim["weight_key"]
            score = scores_dict.get(key, 0)
            weight = self._weights.get(w_key, 1 / len(SCORE_DIMENSIONS))
            total += score * weight * 10  # 0-10分 * 权重 * 10 = 0-100
            weight_sum += weight
        # 归一化（防止权重之和不等于1）
        if weight_sum > 0:
            total = total / weight_sum
        return round(total, 2)

    def score_and_save(self, product_id: int, scores_dict: dict,
                       method: str = "manual", reviewer: str = None,
                       notes: str = None) -> dict:
        """
        计算评分并保存到数据库
        :param product_id: 商品ID
        :param scores_dict: {s01_pdd_heat: 8, s04_douyin_fit: 9, ...}
        :param method: manual / auto
        :param reviewer: 审核人
        :param notes: 备注
        :return: 完整评分结果
        """
        total = self.calc_total_score(scores_dict)
        min_score = self.config.get("scoring", {}).get("min_total_score", 60)
        is_selected = 1 if total >= min_score else 0

        score_date = date.today().strftime("%Y-%m-%d")

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # 插入评分记录
        cur.execute("""
        INSERT INTO product_scores (
            product_id, score_date,
            s01_pdd_heat, s02_growth_7d, s03_trend_30d, s04_douyin_fit,
            s05_visual_strength, s06_low_explain, s07_low_decision,
            s08_impulse_price, s09_commission_val, s10_competition,
            s11_supply_stable, s12_compliance_risk, s13_refund_risk,
            total_score, score_method, reviewer, is_selected, notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            product_id, score_date,
            scores_dict.get("s01_pdd_heat", 0),
            scores_dict.get("s02_growth_7d", 0),
            scores_dict.get("s03_trend_30d", 0),
            scores_dict.get("s04_douyin_fit", 0),
            scores_dict.get("s05_visual_strength", 0),
            scores_dict.get("s06_low_explain", 0),
            scores_dict.get("s07_low_decision", 0),
            scores_dict.get("s08_impulse_price", 0),
            scores_dict.get("s09_commission_val", 0),
            scores_dict.get("s10_competition", 0),
            scores_dict.get("s11_supply_stable", 0),
            scores_dict.get("s12_compliance_risk", 0),
            scores_dict.get("s13_refund_risk", 0),
            total, method, reviewer, is_selected, notes
        ))

        # 更新商品状态
        new_status = "selected" if is_selected else "rejected"
        cur.execute("""
        UPDATE product_pool SET status=?, updated_at=datetime('now','localtime')
        WHERE id=?
        """, (new_status, product_id))

        conn.commit()
        conn.close()

        result = {
            "product_id": product_id,
            "score_date": score_date,
            "total_score": total,
            "is_selected": bool(is_selected),
            "detail": scores_dict,
        }
        return result

    def get_top_products(self, n: int = 10, target_date: str = None) -> list:
        """
        获取指定日期评分最高的Top N商品
        :return: [{product_id, title, total_score, is_selected, ...}]
        """
        if target_date is None:
            target_date = date.today().strftime("%Y-%m-%d")

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
        SELECT
            p.id, p.title, p.price, p.commission_rate, p.commission_amt,
            p.pdd_url, s.total_score, s.is_selected, s.score_date
        FROM product_scores s
        JOIN product_pool p ON p.id = s.product_id
        WHERE s.score_date = ? AND s.is_selected = 1
        ORDER BY s.total_score DESC
        LIMIT ?
        """, (target_date, n))
        rows = cur.fetchall()
        conn.close()

        results = []
        for row in rows:
            results.append({
                "id": row[0],
                "title": row[1],
                "price": row[2],
                "commission_rate": row[3],
                "commission_amt": row[4],
                "pdd_url": row[5],
                "total_score": row[6],
                "is_selected": bool(row[7]),
                "score_date": row[8],
            })
        return results

    @staticmethod
    def get_score_guide() -> str:
        """返回可读的评分参考指南（用于后台展示）"""
        lines = ["# 商品评分参考指南（13维）\n"]
        for i, dim in enumerate(SCORE_DIMENSIONS, 1):
            lines.append(f"\n## {i}. {dim['name']}")
            lines.append(f"说明：{dim['desc']}")
            lines.append("打分参考：")
            for score, desc in sorted(dim["score_guide"].items(), reverse=True):
                lines.append(f"  {score}分：{desc}")
        return "\n".join(lines)


# ─────────────────────────────────────────────
# 快速测试
# ─────────────────────────────────────────────
if __name__ == "__main__":
    scorer = ProductScorer()

    # 测试自动打分（模拟商品数据）
    product_data = {
        "price": 29.9,
        "sales_30d": 15000,
        "sales_7d": 800,
        "commission_rate": 18,
        "commission_amt": 5.4,
    }
    auto_scores = scorer.score_auto_partial(product_data)
    print("自动计算维度：", auto_scores)

    # 补充手动打分维度
    full_scores = {
        **auto_scores,
        "s03_trend_30d": 7,
        "s04_douyin_fit": 9,      # 桌面摆件，强视觉
        "s05_visual_strength": 8,
        "s06_low_explain": 9,
        "s07_low_decision": 9,
        "s10_competition": 7,
        "s11_supply_stable": 8,
        "s12_compliance_risk": 10,  # 纯装饰，合规风险极低
        "s13_refund_risk": 9,
    }

    total = scorer.calc_total_score(full_scores)
    print(f"\n总分：{total}/100")
    print(f"是否入选（≥60分）：{'✅ 是' if total >= 60 else '❌ 否'}")
    print("\n" + scorer.get_score_guide()[:500] + "...")
