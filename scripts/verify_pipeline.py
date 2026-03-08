"""
B阶段验证脚本：端到端测试真实数据流
运行：python scripts/verify_pipeline.py

测试4个关键节点：
  1. PDD API 连通
  2. 商品标准化（normalize）
  3. LLM API 连通（DeepSeek/降级模板均可）
  4. Flask 数据回传 API
"""

import sys
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from utils.config import load_config

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"

results = []


def check(label: str, passed: bool, detail: str = "", is_warning: bool = False):
    icon = PASS if passed else (WARN if is_warning else FAIL)
    line = f"  {icon} {label}"
    if detail:
        line += f" | {detail}"
    print(line)
    results.append(passed or is_warning)


def main():
    print("\n" + "=" * 65)
    print("  B阶段验证：真实数据流 end-to-end 测试")
    print("=" * 65)

    config = load_config()
    db_path = str(ROOT / config.get("paths", {}).get("db", "data/db/main.db"))

    # ─────────────────────────────────────────────────────────────
    # [1] PDD API 连通性
    # ─────────────────────────────────────────────────────────────
    print("\n[1/4] PDD 多多进宝 API 连通性")
    try:
        from scripts.pdd_api import search_goods
        resp = search_goods("桌面摆件", page=1, page_size=10, sort_type=3)
        goods_list = resp.get("goods_search_response", {}).get("goods_list", [])
        if goods_list:
            g = goods_list[0]
            check(
                "API 正常",
                True,
                f"返回 {len(goods_list)} 条 | 示例: {g.get('goods_name','')[:20]}",
            )
        else:
            check("API 返回空", False, "返回了响应但 goods_list 为空")
    except Exception as e:
        check("API 连接失败", False, str(e)[:80])

    # ─────────────────────────────────────────────────────────────
    # [2] 商品标准化（字段映射）
    # ─────────────────────────────────────────────────────────────
    print("\n[2/4] 商品标准化（PDD字段 → DB字段映射）")
    try:
        from scripts.pdd_api import search_goods
        from scripts.product_fetcher import ProductFetcher

        fetcher = ProductFetcher(db_path, config)
        resp = search_goods("流沙画", page=1, page_size=10, sort_type=3)
        raw_list = resp.get("goods_search_response", {}).get("goods_list", [])

        if raw_list:
            norm = fetcher._normalize(raw_list[0], source_keyword="流沙画")
            if norm:
                required_fields = [
                    "pdd_goods_id", "title", "price",
                    "commission_rate", "pdd_url", "cover_img",
                ]
                missing = [f for f in required_fields if not norm.get(f)]
                if not missing:
                    check(
                        "字段映射完整",
                        True,
                        f"价格¥{norm['price']} 佣金{norm['commission_rate']}%"
                        f" 月销{norm['sales_30d']}",
                    )
                else:
                    check("字段映射缺失", False, f"缺失: {missing}")
            else:
                check("normalize 返回 None", False, "原始数据可能缺少 goods_id")
        else:
            check("无商品数据", False, "搜索「流沙画」无结果", is_warning=True)
    except Exception as e:
        check("标准化失败", False, str(e)[:80])

    # ─────────────────────────────────────────────────────────────
    # [3] LLM / 模板引擎 内容生成
    # ─────────────────────────────────────────────────────────────
    print("\n[3/4] 内容生成（LLM 优先，降级模板）")
    try:
        from content.llm_generator import LLMContentGenerator

        gen = LLMContentGenerator(config)

        mock_product = {
            "id": 999,
            "title": "流沙画 创意桌面摆件 沙漏装饰品",
            "price": 29.9,
            "sales_30d": 15000,
            "commission_rate": 15.0,
            "commission_amt": 4.49,
        }

        # 抖音脚本
        script = gen.generate_douyin(mock_product, "contrast")
        is_llm = script.template_version.startswith("llm")
        check(
            f"抖音脚本 | {'LLM' if is_llm else '模板引擎'}",
            True,
            f"标题: {script.title[:25]} | 分镜: {len(script.storyboards)}个",
        )

        # 小红书笔记
        note = gen.generate_xhs(mock_product, "scene")
        is_llm_xhs = note.template_version.startswith("llm")
        check(
            f"小红书笔记 | {'LLM' if is_llm_xhs else '模板引擎'}",
            True,
            f"标题: {note.cover_title[:20]} | 正文: {len(note.body_text)}字",
        )

        if not gen._llm_ok:
            print(
                f"    {WARN} DeepSeek API Key 未配置，已降级到模板引擎。"
                "配置 Key 后可升级为 AI 生成"
            )
    except Exception as e:
        check("内容生成失败", False, str(e)[:100])

    # ─────────────────────────────────────────────────────────────
    # [4] Flask API 可访问
    # ─────────────────────────────────────────────────────────────
    print("\n[4/4] Flask 后台 API 可访问性")
    try:
        import requests as _req
        endpoints = [
            ("选品看板API", "http://127.0.0.1:5000/api/v1/products/top10"),
            ("内容看板API", "http://127.0.0.1:5000/api/v1/content"),
            ("数据回传API", "http://127.0.0.1:5000/api/v1/tracker/daily"),
        ]
        for name, url in endpoints:
            try:
                r = _req.get(url, timeout=3)
                check(name, r.status_code == 200, f"HTTP {r.status_code}")
            except _req.exceptions.ConnectionError:
                check(name, False, "Flask 服务未启动，运行 python start.py",
                      is_warning=True)
            except Exception as e:
                check(name, False, str(e)[:60])
    except ImportError:
        check("requests 库", False, "requests 未安装")

    # ─────────────────────────────────────────────────────────────
    # 汇总
    # ─────────────────────────────────────────────────────────────
    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 65)
    print(f"  验证结果: {passed}/{total} 通过")
    if passed == total:
        print("  🎉 全部通过！B阶段真实数据流已就绪")
    else:
        print("  ⚠️  有项目未通过，查看上方详情")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
