"""
每日任务流主入口
运行方式：python daily_runner.py [--date YYYY-MM-DD] [--task TASK_ID]
示例：
  python daily_runner.py                    # 运行今天所有任务
  python daily_runner.py --date 2026-03-08  # 运行指定日期
  python daily_runner.py --task scoring     # 只运行评分任务

任务流顺序：
  1. category_radar      → 类目雷达更新
  2. product_pool_refresh→ 候选商品池刷新
  3. product_scoring     → 商品评分（需人工确认）
  4. content_generation  → 脚本生成（需人工审核）
  5. compliance_check    → 合规检查（需人工确认）
  6. daily_review        → 每日复盘报告

⚠️ 高风险动作一律不在此流程中执行：
  - 自动发布
  - 账号操作
  - 资金相关
"""

import argparse
import sys
import os
from datetime import datetime, date
from pathlib import Path

# 确保项目根目录在 sys.path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from utils.logger import get_logger, log_task_start, log_task_end, log_human_required
from utils.config import load_config

logger = get_logger("daily_runner")


# ─────────────────────────────────────────────
# 各任务模块（后续逐步完善）
# ─────────────────────────────────────────────

def task_category_radar(run_date: str, config: dict) -> bool:
    """
    任务1：类目雷达更新
    输入：无（从配置读取聚焦类目）
    输出：category_radar 表更新
    当前阶段：手动录入模式
    """
    log_task_start(logger, "类目雷达", {"date": run_date})
    try:
        # TODO: 阶段2实现自动采集
        # 当前阶段：提示人工录入
        logger.info(f"[类目雷达] 当前模式: manual | 请手动更新 category_radar 表")
        logger.info(f"[类目雷达] 聚焦类目: {[c['name'] for c in config.get('focus', {}).get('categories', [])]}")
        log_task_end(logger, "类目雷达", True, "手动模式，已提示人工录入")
        return True
    except Exception as e:
        from utils.logger import log_exception
        log_exception(logger, "类目雷达任务失败", e)
        return False


def task_product_pool_refresh(run_date: str, config: dict) -> bool:
    """
    任务2：候选商品池刷新（B阶段：接入PDD多多进宝真实API）
    输入：config.focus.categories 中的关键词列表
    输出：product_pool 表新增/更新候选商品 + 自动预打分
    降级：API 失败时记录警告，返回 False 但不 raise（允许后续任务继续）
    """
    import time as _time
    log_task_start(logger, "候选商品池刷新", {"date": run_date})
    try:
        from scripts.product_fetcher import ProductFetcher

        db_path = str(ROOT / config.get("paths", {}).get("db", "data/db/main.db"))
        fetcher = ProductFetcher(db_path, config)

        # ── 关键词列表 ──────────────────────────
        keywords = []
        price_ranges = []
        for cat in config.get("focus", {}).get("categories", []):
            keywords.extend(cat.get("keywords", []))
            pr = cat.get("price_range", {})
            price_ranges.append((
                float(pr.get("min", 9.9)),
                float(pr.get("max", 99.0)),
            ))

        # 全局价格区间：取最宽范围
        price_min = min(p[0] for p in price_ranges) if price_ranges else 9.9
        price_max = max(p[1] for p in price_ranges) if price_ranges else 99.0

        logger.info(
            f"[商品池] 关注关键词 {len(keywords)} 个，价格区间 ¥{price_min}~¥{price_max}"
        )

        # ── 关键词搜索（限前5个，避免 API 超配额）──
        all_goods = []
        fetch_keywords = keywords[:5]
        for kw in fetch_keywords:
            goods = fetcher.fetch_by_keyword(kw, pages=1, sort_type=3)
            all_goods.extend(goods)
            logger.info(f"  关键词「{kw}」→ {len(goods)} 条")
            _time.sleep(1)  # 关键词间限流

        # ── 高佣榜补充 ──────────────────────────
        recommend = fetcher.fetch_recommend(channel_type=10)
        all_goods.extend(recommend)
        logger.info(f"[商品池] 高佣榜补充 → {len(recommend)} 条")

        # ── 价格过滤 ────────────────────────────
        filtered = fetcher.filter_by_price(all_goods, price_min, price_max)
        logger.info(
            f"[商品池] 价格过滤后 {len(filtered)}/{len(all_goods)} 条"
        )

        # ── 写库 ────────────────────────────────
        stats = fetcher.upsert_to_db(filtered, run_date)
        logger.info(
            f"[商品池] 入库完成 | 新增 {stats['new']}  更新 {stats['updated']}"
            f"  错误 {stats['errors']}"
        )

        # ── 自动预打分 ──────────────────────────
        if stats["new"] > 0:
            scored = fetcher.auto_score_new_goods(run_date)
            logger.info(f"[商品池] 自动预打分 {scored} 件（4/13维，待人工补全）")

        # ── 降级提示 ────────────────────────────
        if stats["new"] == 0 and stats["errors"] > 3:
            log_human_required(
                logger,
                "商品抓取异常",
                f"API 错误 {stats['errors']} 次且无新商品入库，"
                "请检查 PDD API 连通性或手动录入 product_pool 表",
            )

        log_task_end(
            logger,
            "候选商品池刷新",
            True,
            f"新增 {stats['new']} 条，更新 {stats['updated']} 条",
        )
        return True

    except Exception as e:
        from utils.logger import log_exception
        log_exception(logger, "商品池刷新失败", e)
        logger.warning("[商品池] API 完全失败，降级为手动模式")
        log_human_required(
            logger, "手动录入商品",
            "自动抓取失败，请手动将候选商品录入 product_pool 表后继续"
        )
        return False  # 返回 False 但不 raise，后续 task 继续执行


def task_product_scoring(run_date: str, config: dict) -> bool:
    """
    任务3：商品评分
    输入：product_pool 中 status='pending' 的商品
    输出：product_scores 表，product_pool.status → 'scored'
    ✅ 人工节点：评分结果需人工审核确认
    """
    log_task_start(logger, "商品评分", {"date": run_date})
    try:
        # TODO: 阶段2接入 scoring/scorer.py
        logger.info(f"[评分] 将对 status=pending 的商品执行13维评分")
        logger.info(f"[评分] 最低总分门槛: {config.get('scoring', {}).get('min_total_score', 60)}")
        log_human_required(logger, "商品评分审核",
                          "评分完成后，请检查每个商品的评分和推荐理由，确认是否进入内容池")
        log_task_end(logger, "商品评分", True, "评分逻辑待阶段2实现，当前为占位")
        return True
    except Exception as e:
        from utils.logger import log_exception
        log_exception(logger, "商品评分失败", e)
        return False


def task_content_generation(run_date: str, config: dict) -> bool:
    """
    任务4：双平台内容生成（抖音脚本 + 小红书图文笔记）
    输入：product_pool 中 status='selected' 的商品
    输出：content_tasks 表（每个商品 × 4类脚本类型 × 2平台 = 8条记录）
    ✅ 人工节点：所有脚本/笔记必须人工审核后才能进入素材阶段

    平台说明：
      - 抖音：竖屏短视频，挂橱窗商品卡
      - 小红书：图文笔记（6张图），支持内挂商品卡（联盟商品）/ 评论区推广链接
    """
    log_task_start(logger, "双平台内容生成", {"date": run_date})
    try:
        import sqlite3

        db_path = ROOT / config.get("paths", {}).get("db", "data/db/main.db")
        if not db_path.exists():
            logger.warning(f"[内容生成] 数据库不存在，请先运行 init_db: {db_path}")
            log_task_end(logger, "双平台内容生成", False, "数据库不存在")
            return False

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 获取入选商品
        cur.execute("""
            SELECT id, title, price, commission_rate
            FROM product_pool
            WHERE status = 'selected'
        """)
        products = cur.fetchall()

        if not products:
            logger.info("[内容生成] 暂无 status='selected' 的商品，跳过")
            conn.close()
            log_task_end(logger, "双平台内容生成", True, "无入选商品，跳过")
            return True

        script_types = config.get("content", {}).get("script_types",
            ["pain_point", "scene", "contrast", "list"])
        platforms = config.get("content", {}).get("platforms", ["douyin", "xiaohongshu"])

        # ── B阶段：使用 LLM 生成器（失败自动降级模板引擎）──
        from content.llm_generator import LLMContentGenerator
        import json as _json

        llm_gen = LLMContentGenerator(config)
        logger.info(
            f"[内容生成] 生成器模式: "
            f"{'LLM（DeepSeek）' if llm_gen._llm_ok else '模板引擎（降级）'}"
        )

        douyin_count = 0
        xhs_count = 0

        for prod in products:
            p = dict(prod)
            logger.info(f"[内容生成] 处理商品 id={p['id']} 《{p['title'][:20]}》")

            # ── 抖音脚本（批量：1次API生成4种类型）──────
            if "douyin" in platforms:
                try:
                    # v2.0 批量接口：1次调用生成全部4种类型
                    all_scripts = llm_gen.generate_all_douyin(p)
                    for stype, script in all_scripts.items():
                        if stype not in script_types:
                            continue
                        storyboard_json = _json.dumps(
                            [s.__dict__ for s in script.storyboards],
                            ensure_ascii=False,
                        )
                        gen_method = (
                            "llm" if script.template_version.startswith("llm")
                            else "template"
                        )
                        cur.execute(
                            """
                            INSERT INTO content_tasks
                            (product_id, task_date, platform, script_type,
                             title, cover_copy, hook_3s, storyboard,
                             subtitle, voiceover, cta,
                             pub_time_suggest, mount_suggest, compliance_check,
                             status, gen_method)
                            VALUES (?,?,?,?, ?,?,?,?, ?,?,?, ?,?,?, ?,?)
                            """,
                            (
                                p["id"], run_date, "douyin", stype,
                                script.title, script.cover_copy,
                                script.hook_3s, storyboard_json,
                                script.full_subtitle, script.voiceover, script.cta,
                                script.pub_time_suggest, script.mount_suggest,
                                script.compliance_notes,
                                "draft", gen_method,
                            ),
                        )
                        douyin_count += 1
                except Exception as e:
                    logger.warning(f"  [抖音] 批量生成失败: {e}")

            # ── 小红书图文笔记（批量：1次API生成4种类型）──
            if "xiaohongshu" in platforms:
                try:
                    all_notes = llm_gen.generate_all_xhs(p)
                    for ntype, note in all_notes.items():
                        if ntype not in script_types:
                            continue
                        hashtags_json = _json.dumps(
                            note.hashtags, ensure_ascii=False
                        )
                        images_json = _json.dumps(
                            [img.__dict__ for img in note.images],
                            ensure_ascii=False,
                        )
                        gen_method = (
                            "llm" if note.template_version.startswith("llm")
                            else "template"
                        )
                        xhs_body = f"【{note.cover_title}】\n\n{note.body_text}"
                        cur.execute(
                            """
                            INSERT INTO content_tasks
                            (product_id, task_date, platform, script_type,
                             title, cover_copy,
                             xhs_body, xhs_hashtags, xhs_img_count, xhs_img_guide,
                             cta, pub_time_suggest, compliance_check,
                             status, gen_method)
                            VALUES (?,?,?,?, ?,?, ?,?,?,?, ?,?,?, ?,?)
                            """,
                            (
                                p["id"], run_date, "xiaohongshu", ntype,
                                note.cover_title, note.cover_subtitle,
                                xhs_body, hashtags_json,
                                note.img_count, images_json,
                                note.cta, note.pub_time_suggest,
                                note.compliance_notes,
                                "draft", gen_method,
                            ),
                        )
                        xhs_count += 1
                except Exception as e:
                    logger.warning(f"  [小红书] 批量生成失败: {e}")

        conn.commit()
        conn.close()

        logger.info(f"[内容生成] 完成 | 商品数:{len(products)} | 抖音:{douyin_count}条 | 小红书:{xhs_count}条")
        log_human_required(logger, "双平台内容审核",
            f"已生成抖音脚本{douyin_count}条 + 小红书图文{xhs_count}条，"
            "请人工检查：①合规词②夸大宣传③小红书正文字数③推广链接类型确认")
        log_task_end(logger, "双平台内容生成", True,
            f"抖音{douyin_count}条 + 小红书{xhs_count}条，等待人工审核")
        return True
    except Exception as e:
        from utils.logger import log_exception
        log_exception(logger, "内容生成失败", e)
        return False


def task_compliance_check(run_date: str, config: dict) -> bool:
    """
    任务5：合规自动检查（B阶段：接入真实关键词扫描）
    输入：content_tasks 中 status='draft' 的脚本
    输出：compliance_check 字段更新（命中词 + 风险等级）
    ✅ 人工节点：自动扫描仅作初筛，人工必须最终确认
    """
    import sqlite3 as _sqlite3
    log_task_start(logger, "合规检查", {"date": run_date})
    try:
        forbidden = config.get("compliance", {}).get("forbidden_keywords", [])
        warning_kws = config.get("compliance", {}).get("warning_keywords", [])

        logger.info(
            f"[合规] 违禁词 {len(forbidden)} 个 | 预警词 {len(warning_kws)} 个"
        )

        db_path = str(ROOT / config.get("paths", {}).get("db", "data/db/main.db"))
        conn = _sqlite3.connect(db_path)
        conn.row_factory = _sqlite3.Row
        cur = conn.cursor()

        # 获取今日 draft 状态的内容
        cur.execute(
            """
            SELECT id, platform, title, cover_copy, hook_3s, subtitle,
                   voiceover, xhs_body
            FROM content_tasks
            WHERE task_date=? AND status='draft'
            """,
            (run_date,),
        )
        tasks = cur.fetchall()
        logger.info(f"[合规] 扫描今日 draft 内容 {len(tasks)} 条")

        blocked_count = 0
        warning_count = 0

        for task in tasks:
            task_id = task["id"]
            # 拼接所有文本字段
            all_text = " ".join(
                str(task[f]) for f in
                ["title", "cover_copy", "hook_3s", "subtitle", "voiceover", "xhs_body"]
                if task[f]
            )

            # 检查违禁词（硬阻断）
            blocked_hits = [kw for kw in forbidden if kw in all_text]
            # 检查预警词（软警告）
            warning_hits = [kw for kw in warning_kws if kw in all_text]

            if blocked_hits:
                note = f"🚫 违禁词命中（阻断）：{blocked_hits}，必须人工修改后方可发布"
                blocked_count += 1
            elif warning_hits:
                note = f"⚠️ 预警词命中：{warning_hits}，建议人工确认"
                warning_count += 1
            else:
                note = "✅ 自动扫描通过（人工最终确认后可发布）"

            cur.execute(
                "UPDATE content_tasks SET compliance_check=? WHERE id=?",
                (note, task_id),
            )

        conn.commit()
        conn.close()

        logger.info(
            f"[合规] 扫描完成 | 违禁词命中 {blocked_count} 条 | 预警词命中 {warning_count} 条"
        )
        log_human_required(
            logger,
            "合规最终审核",
            f"自动扫描完成：{blocked_count} 条违禁词命中需修改，"
            f"{warning_count} 条有预警词，"
            f"请人工逐条审核所有 draft 内容后再进入发布流程",
        )
        log_task_end(logger, "合规检查", True,
                     f"自动扫描 {len(tasks)} 条，违禁 {blocked_count}，预警 {warning_count}")
        return True

    except Exception as e:
        from utils.logger import log_exception
        log_exception(logger, "合规检查失败", e)
        return False


def task_daily_review(run_date: str, config: dict) -> bool:
    """
    任务6：每日复盘报告
    输入：当日所有任务执行结果 + performance_data
    输出：daily_review 表 + reports/daily/YYYY-MM-DD.md
    """
    log_task_start(logger, "每日复盘", {"date": run_date})
    try:
        import sqlite3
        from pathlib import Path
        db_path = ROOT / config.get("paths", {}).get("db", "data/db/main.db")
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        # 统计今日数据
        cur.execute("SELECT COUNT(*) FROM product_pool WHERE add_date=?", (run_date,))
        products_analyzed = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM product_scores WHERE score_date=?", (run_date,))
        scored = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM content_tasks WHERE task_date=? AND platform='douyin'", (run_date,))
        scripts_douyin = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM content_tasks WHERE task_date=? AND platform='xiaohongshu'", (run_date,))
        scripts_xhs = cur.fetchone()[0]

        scripts = scripts_douyin + scripts_xhs

        conn.close()

        # 生成复盘报告（Markdown）
        report_dir = ROOT / "reports" / "daily"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"{run_date}.md"

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"# 每日复盘报告 · {run_date}\n\n")
            f.write(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("## 今日数据摘要\n\n")
            f.write(f"| 指标 | 数值 |\n|------|------|\n")
            f.write(f"| 今日分析商品数 | {products_analyzed} |\n")
            f.write(f"| 完成评分商品数 | {scored} |\n")
            f.write(f"| 生成内容总数 | {scripts} |\n")
            f.write(f"| └ 抖音脚本 | {scripts_douyin} |\n")
            f.write(f"| └ 小红书图文笔记 | {scripts_xhs} |\n\n")
            f.write("## 双平台内容待审核\n\n")
            f.write("- [ ] 抖音脚本合规审核（合规词/夸大宣传）\n")
            f.write("- [ ] 小红书图文正文审核（字数/话题标签）\n")
            f.write("- [ ] 小红书推广链接类型确认（内挂 or 评论区）\n\n")
            f.write("## 今日异常\n\n_请手动填写_\n\n")
            f.write("## 今日洞察\n\n_请手动填写_\n\n")
            f.write("## 明日建议\n\n_请手动填写_\n\n")
            f.write("## 权重调整建议\n\n_待系统自动生成（阶段5）_\n\n")
            f.write("---\n> ⚠️ 权重调整需人工确认后才能生效\n")

        logger.info(f"[复盘] 报告已生成：{report_path}")
        log_task_end(logger, "每日复盘", True, f"报告：{report_path}")
        return True
    except Exception as e:
        from utils.logger import log_exception
        log_exception(logger, "复盘生成失败", e)
        return False


# ─────────────────────────────────────────────
# 任务注册表
# ─────────────────────────────────────────────
TASK_REGISTRY = {
    "category_radar":       task_category_radar,
    "product_pool_refresh": task_product_pool_refresh,
    "product_scoring":      task_product_scoring,
    "content_generation":   task_content_generation,
    "compliance_check":     task_compliance_check,
    "daily_review":         task_daily_review,
}

TASK_ORDER = [
    "category_radar",
    "product_pool_refresh",
    "product_scoring",
    "content_generation",
    "compliance_check",
    "daily_review",
]


# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="每日任务流运行器")
    parser.add_argument("--date", default=date.today().strftime("%Y-%m-%d"),
                        help="运行日期，格式 YYYY-MM-DD")
    parser.add_argument("--task", default=None,
                        choices=list(TASK_REGISTRY.keys()) + ["all"],
                        help="指定运行单个任务，默认运行全部")
    args = parser.parse_args()

    run_date = args.date
    config = load_config()

    logger.info("=" * 60)
    logger.info(f"  拼多多→抖音运营系统 · 每日任务流")
    logger.info(f"  运行日期: {run_date}")
    logger.info(f"  阶段: {config.get('focus', {}).get('phase', 'mvp').upper()}")
    logger.info("=" * 60)

    # 确定要运行的任务
    if args.task and args.task != "all":
        tasks_to_run = [args.task]
    else:
        # 从配置中过滤 enabled=true 的任务
        enabled_tasks = {
            t["id"] for t in config.get("daily_runner", {}).get("tasks", [])
            if t.get("enabled", True)
        }
        tasks_to_run = [t for t in TASK_ORDER if t in enabled_tasks]

    logger.info(f"将执行 {len(tasks_to_run)} 个任务：{tasks_to_run}")

    results = {}
    for task_id in tasks_to_run:
        func = TASK_REGISTRY.get(task_id)
        if func:
            results[task_id] = func(run_date, config)
        else:
            logger.warning(f"未知任务: {task_id}，跳过")

    # 汇总
    logger.info("=" * 60)
    success = sum(1 for v in results.values() if v)
    fail = len(results) - success
    logger.info(f"  任务汇总：成功 {success}/{len(results)}，失败 {fail}")
    for tid, ok in results.items():
        status_icon = "✅" if ok else "❌"
        logger.info(f"  {status_icon} {tid}")
    logger.info("=" * 60)

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
