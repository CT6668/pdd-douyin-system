"""
PDD 商品抓取器 v1.0
职责：PDD多多进宝API原始JSON → 标准化 → 去重写库 → 自动预打分

使用：
    from scripts.product_fetcher import ProductFetcher
    fetcher = ProductFetcher(db_path, config)
    goods = fetcher.fetch_by_keyword("桌面摆件", pages=2)
    stats = fetcher.upsert_to_db(goods, "2026-03-08")
"""

import re
import sqlite3
import time
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from utils.logger import get_logger

logger = get_logger("product_fetcher")


# ─────────────────────────────────────────────
# PDD API 字段映射（基于实测字段，2026-03）
# ─────────────────────────────────────────────
# 已确认真实字段：
#   goods_id          商品ID (int)
#   goods_name        商品标题
#   goods_thumbnail_url  缩略图
#   goods_image_url   大图
#   min_group_price   拼单价（分）
#   min_normal_price  原价（分）
#   promotion_rate    佣金率（整数，如60 = 6.0%）
#   predict_promotion_rate  预估佣金率（万分比，如800 = 8%）
#   sales_tip         销量文本（如 "11.4万+"）
#   category_name     类目名
#   category_id       类目ID
#   opt_name          类目大类


class ProductFetcher:
    """PDD 商品抓取、标准化、去重写库"""

    def __init__(self, db_path: str, config: dict):
        self.db_path = db_path
        self.config = config
        self.stats = {
            "fetched": 0,
            "new": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 0,
        }

    # ──────────────────────────────────────────
    # 数据获取
    # ──────────────────────────────────────────

    def fetch_by_keyword(self, keyword: str, pages: int = 2,
                         sort_type: int = 3) -> list:
        """
        关键词搜索商品
        sort_type: 0=综合 1=佣金 2=价格 3=销量(推荐) 4=优惠券
        返回标准化商品列表（跳过失败页，不中断）
        """
        from scripts.pdd_api import search_goods

        goods = []
        for page in range(1, pages + 1):
            try:
                resp = search_goods(
                    keyword,
                    page=page,
                    page_size=50,
                    sort_type=sort_type,
                )
                raw_list = (
                    resp.get("goods_search_response", {})
                    .get("goods_list", [])
                )
                normalized = [
                    self._normalize(g, source_keyword=keyword)
                    for g in raw_list
                ]
                normalized = [g for g in normalized if g]  # 过滤None
                goods.extend(normalized)
                self.stats["fetched"] += len(normalized)
                logger.info(f"  [{keyword}] 第{page}页 → {len(normalized)} 条")
                time.sleep(0.5)  # 限流
            except Exception as e:
                self.stats["errors"] += 1
                logger.warning(
                    f"[Fetcher] 关键词「{keyword}」第{page}页失败: {e}"
                )
        return goods

    def fetch_recommend(self, channel_type: int = 10) -> list:
        """
        推荐商品（channel_type=10=高佣榜）
        作为关键词搜索的补充，失败时返回空列表
        """
        from scripts.pdd_api import get_recommend_goods

        try:
            resp = get_recommend_goods(channel_type=channel_type)
            raw_list = (
                resp.get("goods_recommend_response", {}).get("list", [])
            )
            normalized = [
                self._normalize(g, source_keyword="__recommend__")
                for g in raw_list
            ]
            normalized = [g for g in normalized if g]
            self.stats["fetched"] += len(normalized)
            logger.info(f"[Fetcher] 高佣榜 → {len(normalized)} 条")
            return normalized
        except Exception as e:
            self.stats["errors"] += 1
            logger.warning(f"[Fetcher] 推荐商品抓取失败: {e}")
            return []

    # ──────────────────────────────────────────
    # 字段标准化
    # ──────────────────────────────────────────

    def _normalize(self, raw: dict, source_keyword: str) -> dict | None:
        """
        PDD 原始字段 → product_pool 标准字段
        任何异常返回 None（由调用方过滤）
        """
        try:
            goods_id = str(raw.get("goods_id", "")).strip()
            if not goods_id:
                return None

            # 价格：PDD 返回分，转换为元
            price = int(raw.get("min_group_price", 0)) / 100
            origin_price = int(
                raw.get("min_normal_price", raw.get("min_group_price", 0))
            ) / 100

            # 佣金率：promotion_rate 为整数（如 60 = 6.0%）
            # predict_promotion_rate 通常更高，取实际 promotion_rate
            commission_rate = float(raw.get("promotion_rate", 0)) / 10
            commission_amt = round(price * commission_rate / 100, 2)

            # 销量解析
            sales_30d = self._parse_sales(
                raw.get("sales_tip", ""),
                fallback=int(raw.get("sales_quantity", 0)),
            )

            # 类目
            category_l1 = raw.get("opt_name", raw.get("category_name", ""))
            category_l2 = raw.get("category_name", "")

            # 商品图：缩略图优先，其次大图
            cover_img = (
                raw.get("goods_thumbnail_url")
                or raw.get("goods_image_url")
                or ""
            )

            return {
                "pdd_goods_id": goods_id,
                "title": raw.get("goods_name", "")[:200],
                "category_l1": category_l1[:50] if category_l1 else "",
                "category_l2": category_l2[:50] if category_l2 else "",
                "price": round(price, 2),
                "origin_price": round(origin_price, 2),
                "sales_30d": sales_30d,
                "sales_7d": 0,   # API 不直接返回7日销量
                "rating": float(raw.get("goods_eval_score", 0)),
                "commission_rate": round(commission_rate, 2),
                "commission_amt": commission_amt,
                "pdd_url": (
                    f"https://mobile.yangkeduo.com/goods.html"
                    f"?goods_id={goods_id}"
                ),
                "cover_img": cover_img,
                "source_keyword": source_keyword,
            }
        except Exception as e:
            self.stats["errors"] += 1
            logger.debug(f"[Normalize] 商品规范化失败: {e} | raw={str(raw)[:100]}")
            return None

    def _parse_sales(self, sales_tip: str, fallback: int = 0) -> int:
        """
        解析销量文本 → 整数
        "11.4万+" → 114000
        "2000+" → 2000
        """
        if fallback:
            return int(fallback)
        if not sales_tip:
            return 0
        # 万+
        m = re.search(r"([\d.]+)\s*万", sales_tip)
        if m:
            return int(float(m.group(1)) * 10000)
        # 纯数字
        m = re.search(r"(\d+)", sales_tip)
        if m:
            return int(m.group(1))
        return 0

    # ──────────────────────────────────────────
    # 写库
    # ──────────────────────────────────────────

    def upsert_to_db(self, goods_list: list, run_date: str) -> dict:
        """
        商品写入 product_pool（去重+更新）
        - 新商品：INSERT，status='pending'
        - 已存在：只 UPDATE 动态字段（价格/佣金/销量/图片），保持 status 不变
        返回 stats dict: {fetched, new, updated, skipped, errors}
        """
        if not goods_list:
            logger.info("[Fetcher] 无商品数据，跳过写库")
            return self.stats

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        for g in goods_list:
            if not g:
                self.stats["skipped"] += 1
                continue
            try:
                cur.execute(
                    "SELECT id FROM product_pool WHERE pdd_goods_id=?",
                    (g["pdd_goods_id"],),
                )
                existing = cur.fetchone()

                if existing:
                    # 更新动态字段，保持 status
                    cur.execute(
                        """
                        UPDATE product_pool
                        SET price=?, commission_rate=?, commission_amt=?,
                            sales_30d=?, cover_img=?,
                            updated_at=datetime('now','localtime')
                        WHERE pdd_goods_id=?
                        """,
                        (
                            g["price"],
                            g["commission_rate"],
                            g["commission_amt"],
                            g["sales_30d"],
                            g["cover_img"],
                            g["pdd_goods_id"],
                        ),
                    )
                    self.stats["updated"] += 1
                else:
                    # 新商品，status=pending
                    cur.execute(
                        """
                        INSERT INTO product_pool
                        (pdd_goods_id, title, category_l1, category_l2,
                         price, origin_price, sales_30d, sales_7d, rating,
                         commission_rate, commission_amt,
                         pdd_url, cover_img, source_keyword,
                         status, add_date)
                        VALUES (?,?,?,?, ?,?,?,?,?, ?,?, ?,?,?, ?,?)
                        """,
                        (
                            g["pdd_goods_id"],
                            g["title"],
                            g["category_l1"],
                            g["category_l2"],
                            g["price"],
                            g["origin_price"],
                            g["sales_30d"],
                            g["sales_7d"],
                            g["rating"],
                            g["commission_rate"],
                            g["commission_amt"],
                            g["pdd_url"],
                            g["cover_img"],
                            g["source_keyword"],
                            "pending",
                            run_date,
                        ),
                    )
                    self.stats["new"] += 1
            except Exception as e:
                self.stats["errors"] += 1
                logger.warning(
                    f"[Fetcher] 商品 {g.get('pdd_goods_id', '?')} 写库失败: {e}"
                )

        conn.commit()
        conn.close()
        return self.stats

    def auto_score_new_goods(self, run_date: str) -> int:
        """
        对今日新增的 pending 商品执行自动预打分（4个可量化维度）
        直接写 product_scores 表，is_selected=0（待人工确认）
        **不调用 score_and_save**（避免因部分打分导致商品被误判为 rejected）
        返回成功打分的商品数量
        """
        from scoring.scorer import ProductScorer

        scorer = ProductScorer(self.db_path, self.config)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 查今日新增的 pending 商品
        cur.execute(
            """
            SELECT id, price, sales_30d, sales_7d,
                   commission_rate, commission_amt
            FROM product_pool
            WHERE status='pending' AND add_date=?
            """,
            (run_date,),
        )
        new_products = [dict(r) for r in cur.fetchall()]

        if not new_products:
            conn.close()
            return 0

        from datetime import date as dt_date

        score_date = dt_date.today().strftime("%Y-%m-%d")
        scored_count = 0

        for p in new_products:
            try:
                auto_scores = scorer.score_auto_partial(p)
                if not auto_scores:
                    continue

                # 直接写 product_scores，不改 product_pool.status
                cur.execute(
                    """
                    INSERT OR IGNORE INTO product_scores
                    (product_id, score_date,
                     s01_pdd_heat, s02_growth_7d, s03_trend_30d, s04_douyin_fit,
                     s05_visual_strength, s06_low_explain, s07_low_decision,
                     s08_impulse_price, s09_commission_val, s10_competition,
                     s11_supply_stable, s12_compliance_risk, s13_refund_risk,
                     total_score, score_method, is_selected, notes)
                    VALUES (?,?, ?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?,?,?)
                    """,
                    (
                        p["id"],
                        score_date,
                        auto_scores.get("s01_pdd_heat", 0),
                        auto_scores.get("s02_growth_7d", 0),
                        0, 0,   # s03/s04 需人工
                        0, 0, 0,  # s05/s06/s07 需人工
                        auto_scores.get("s08_impulse_price", 0),
                        auto_scores.get("s09_commission_val", 0),
                        0, 0, 0, 0,  # s10-s13 需人工
                        scorer.calc_total_score(auto_scores),  # 部分得分（偏低）
                        "auto_partial",
                        0,   # is_selected=0，等人工确认
                        f"自动预打分（{len(auto_scores)}/13维），待人工补全剩余维度",
                    ),
                )
                scored_count += 1
            except Exception as e:
                logger.warning(f"[AutoScore] 商品 id={p['id']} 预打分失败: {e}")

        conn.commit()
        conn.close()
        return scored_count

    def filter_by_price(self, goods_list: list, price_min: float,
                        price_max: float) -> list:
        """按价格区间过滤商品"""
        return [
            g for g in goods_list
            if g and price_min <= g.get("price", 0) <= price_max
        ]


# ─────────────────────────────────────────────
# 命令行测试入口
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import sys, json
    sys.path.insert(0, str(ROOT))
    from utils.config import load_config

    print("=" * 60)
    print("  ProductFetcher 独立测试")
    print("=" * 60)

    config = load_config()
    db_path = str(ROOT / config.get("paths", {}).get("db", "data/db/main.db"))

    fetcher = ProductFetcher(db_path, config)

    # 测试关键词搜索
    print("\n[1] 测试关键词搜索「桌面摆件」...")
    goods = fetcher.fetch_by_keyword("桌面摆件", pages=1)
    print(f"  获取 {len(goods)} 条商品")
    if goods:
        g = goods[0]
        print(f"  示例: {g['title'][:30]}")
        print(f"  价格: ¥{g['price']}  佣金率: {g['commission_rate']}%  佣金: ¥{g['commission_amt']}")
        print(f"  月销: {g['sales_30d']}  图片: {g['cover_img'][:50]}...")

    # 测试价格过滤
    filtered = fetcher.filter_by_price(goods, 9.9, 99.0)
    print(f"\n[2] 价格过滤 ¥9.9~¥99.0 → {len(filtered)} 条")

    # 测试写库（干运行，不实际写入）
    print(f"\n[3] 写库预演（不实际写入）...")
    print(f"  将写入 {len(filtered)} 条商品到 {db_path}")
    print("\n✅ 测试完成！如需实际写入，运行 daily_runner.py")
