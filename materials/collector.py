"""
素材采集引擎 v1.0
负责为每个商品自动获取素材图片，包括：
  1. 商品主图（从拼多多 cover_img 直接下载）
  2. 竞品参考图（从互联网搜索同类商品截图）
  3. 生活场景参考图（工位/桌面场景参考）

设计原则：
  - 优先用商品自有主图
  - 用搜索引擎图片搜索补充多角度参考图
  - 所有图片本地缓存，不重复下载
  - 人工上传优先级最高（可覆盖自动采集结果）
"""

import json
import os
import re
import time
import hashlib
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict
import httpx

ROOT = Path(__file__).parent.parent
ASSETS_DIR = ROOT / "materials" / "assets"
RAW_IMGS_DIR = ROOT / "data" / "raw" / "product_imgs"
REF_IMGS_DIR = ROOT / "data" / "raw" / "reference_imgs"

# 确保目录存在
for d in [RAW_IMGS_DIR, REF_IMGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


# ─────────────────────────────────────────────
# 图片下载工具
# ─────────────────────────────────────────────

def download_image(url: str, save_path: Path, timeout: int = 15) -> bool:
    """下载图片到本地，返回是否成功"""
    if save_path.exists() and save_path.stat().st_size > 1000:
        return True  # 已缓存，跳过
    try:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        r = httpx.get(url, headers=HEADERS, timeout=timeout, follow_redirects=True)
        if r.status_code == 200 and len(r.content) > 500:
            with open(save_path, "wb") as f:
                f.write(r.content)
            return True
        return False
    except Exception as e:
        print(f"  ✗ 下载失败 {url[:60]}: {e}")
        return False


def url_to_filename(url: str, product_id: int, suffix: str = "") -> str:
    """URL → 唯一文件名"""
    h = hashlib.md5(url.encode()).hexdigest()[:8]
    ext = url.split(".")[-1].split("?")[0][:4] or "jpg"
    return f"p{product_id:03d}{suffix}_{h}.{ext}"


# ─────────────────────────────────────────────
# 1. 商品主图采集
# ─────────────────────────────────────────────

def collect_product_images(product: dict) -> Dict[str, Path]:
    """
    下载商品主图（cover_img）
    返回：{ "cover": Path, ... }
    """
    product_id = product["id"]
    result = {}

    cover_url = product.get("cover_img", "")
    if cover_url:
        fname = f"p{product_id:03d}_cover.jpg"
        save_path = RAW_IMGS_DIR / f"p{product_id:03d}" / fname
        ok = download_image(cover_url, save_path)
        if ok:
            result["cover"] = save_path
            print(f"  ✓ 商品主图: {fname}")
        else:
            print(f"  ✗ 商品主图下载失败: {cover_url[:60]}")

    return result


# ─────────────────────────────────────────────
# 2. 竞品/同类参考图搜索采集
# ─────────────────────────────────────────────

def _extract_search_keyword(product_title: str) -> str:
    """从商品标题提取最有效的搜索关键词"""
    title = product_title
    # 优先提取核心物品词
    patterns = [
        r"(流沙画|沙漏|山水流沙|流沙摆件)",
        r"(水晶发财树|发财树|水晶树)",
        r"(解压骰子|解压玩具|捏捏乐|解压魔方)",
        r"(永生花|干花|浮游花|满天星)",
        r"(招财猫|招财摆件)",
        r"(仿真多肉|多肉摆件)",
        r"(小夜灯|桌面夜灯|氛围灯)",
        r"(盲盒|手办|公仔)",
        r"(桌面摆件|桌面好物|工位摆件)",
    ]
    for pat in patterns:
        m = re.search(pat, title)
        if m:
            return m.group(1)
    # 取前8个字
    return title[:8]


def search_bing_images(keyword: str, count: int = 6) -> List[str]:
    """
    从必应图片搜索获取参考图URL列表
    搜索词加上「桌面摆件 小红书」提升相关性
    """
    query = f"{keyword} 桌面摆件 工位 小红书"
    search_url = (
        f"https://www.bing.com/images/search"
        f"?q={httpx.URL(query).__str__().replace('https://','')}"
        f"&form=HDRSC2&first=1&tsc=ImageHoverTitle"
    )
    # 实际用 bing image search API 格式
    api_url = "https://www.bing.com/images/search"
    params = {
        "q": query,
        "form": "HDRSC2",
        "first": "1",
        "count": str(count * 3),  # 多取一些，过滤掉不可用的
    }
    headers = {
        **HEADERS,
        "Accept": "text/html,application/xhtml+xml",
        "Referer": "https://www.bing.com/",
    }

    img_urls = []
    try:
        r = httpx.get(api_url, params=params, headers=headers, timeout=15, follow_redirects=True)
        if r.status_code == 200:
            # 从 HTML 中提取图片URL（murl参数）
            murls = re.findall(r'"murl":"(https?://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"', r.text)
            img_urls = murls[:count]
    except Exception as e:
        print(f"  搜索请求失败: {e}")

    return img_urls


def collect_reference_images(product: dict, count: int = 4) -> List[Path]:
    """
    搜索并下载同类竞品/场景参考图
    返回成功下载的图片路径列表
    """
    product_id = product["id"]
    keyword = _extract_search_keyword(product.get("title", ""))
    ref_dir = REF_IMGS_DIR / f"p{product_id:03d}"
    ref_dir.mkdir(parents=True, exist_ok=True)

    print(f"  搜索关键词: 「{keyword}」")

    # 场景1：产品展示参考
    urls_product = search_bing_images(f"{keyword} 桌面摆件", count=count)
    # 场景2：工位/生活方式场景参考
    urls_lifestyle = search_bing_images(f"{keyword} 工位 打工人", count=2)

    all_urls = urls_product + urls_lifestyle
    saved = []

    for i, url in enumerate(all_urls[:count + 2]):
        suffix = f"_ref{i+1:02d}"
        fname = url_to_filename(url, product_id, suffix)
        save_path = ref_dir / fname
        ok = download_image(url, save_path)
        if ok:
            saved.append(save_path)
            print(f"  ✓ 参考图 {i+1}: {fname}")
        time.sleep(0.3)  # 礼貌性延迟

    return saved


# ─────────────────────────────────────────────
# 3. 素材采集主入口
# ─────────────────────────────────────────────

class MaterialCollector:
    """素材采集主类"""

    def __init__(self):
        import sqlite3
        from pathlib import Path
        self.db_path = ROOT / "data" / "db" / "main.db"

    def _get_conn(self):
        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def collect_for_product(
        self,
        product: dict,
        fetch_reference: bool = True,
    ) -> dict:
        """
        为单个商品采集全部素材图
        返回：{
            "product_id": int,
            "cover": Path or None,
            "references": [Path, ...],
            "manual_dir": Path,   ← 人工上传目录
        }
        """
        product_id = product["id"]
        print(f"\n[采集] 商品#{product_id} 《{product.get('title','')[:20]}》")

        result = {
            "product_id": product_id,
            "cover": None,
            "references": [],
            "manual_dir": RAW_IMGS_DIR / f"p{product_id:03d}" / "manual",
        }

        # 创建人工上传目录（预留入口）
        result["manual_dir"].mkdir(parents=True, exist_ok=True)
        readme = result["manual_dir"] / "README.txt"
        if not readme.exists():
            with open(readme, "w", encoding="utf-8") as f:
                f.write(
                    f"商品#{product_id}  {product.get('title','')}\n\n"
                    "【人工上传素材目录】\n"
                    "将拍摄好的商品图/生活场景图放在此目录中。\n"
                    "系统优先使用此目录中的图片（人工图 > 自动采集图）。\n\n"
                    "命名建议：\n"
                    "  main_01.jpg   ← 商品主图\n"
                    "  main_02.jpg   ← 商品次图\n"
                    "  scene_01.jpg  ← 桌面/工位场景图\n"
                    "  detail_01.jpg ← 细节特写\n"
                )

        # 下载商品主图
        product_imgs = collect_product_images(product)
        result["cover"] = product_imgs.get("cover")

        # 搜索竞品参考图
        if fetch_reference:
            refs = collect_reference_images(product, count=4)
            result["references"] = refs

        # 更新DB中的图片状态
        self._update_image_status(product_id, result)

        return result

    def collect_for_date(self, task_date: str, fetch_reference: bool = True) -> List[dict]:
        """批量采集：处理指定日期所有approved脚本关联的商品"""
        conn = self._get_conn()
        c = conn.cursor()

        c.execute("""
            SELECT DISTINCT pp.id, pp.title, pp.price, pp.cover_img, pp.pdd_url
            FROM content_tasks ct
            JOIN product_pool pp ON ct.product_id = pp.id
            WHERE ct.status = 'approved' AND ct.task_date = ?
        """, (task_date,))
        products = [dict(r) for r in c.fetchall()]
        conn.close()

        print(f"[素材采集] 共 {len(products)} 款商品需要采集")
        results = []
        for prod in products:
            r = self.collect_for_product(prod, fetch_reference=fetch_reference)
            results.append(r)
            time.sleep(0.5)  # 限速

        # 汇总报告
        ok_cover = sum(1 for r in results if r["cover"])
        ok_refs = sum(len(r["references"]) for r in results)
        print(f"\n[采集完成] 商品数:{len(results)} | 主图成功:{ok_cover} | 参考图:{ok_refs}张")
        return results

    def _update_image_status(self, product_id: int, result: dict):
        """将采集到的图片信息写入 product_pool.notes"""
        import sqlite3
        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()
        imgs_info = {
            "cover_local": str(result["cover"]) if result["cover"] else None,
            "ref_count": len(result["references"]),
            "manual_dir": str(result["manual_dir"]),
            "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        c.execute(
            "UPDATE product_pool SET notes = ? WHERE id = ?",
            (json.dumps(imgs_info, ensure_ascii=False), product_id)
        )
        conn.commit()
        conn.close()

    def get_best_image(self, product_id: int) -> Optional[Path]:
        """
        获取商品最佳图片（优先级：人工上传 > 商品主图 > 参考图）
        """
        base = RAW_IMGS_DIR / f"p{product_id:03d}"

        # 优先级1：人工上传
        manual_dir = base / "manual"
        if manual_dir.exists():
            for img in sorted(manual_dir.glob("*.jpg")) + sorted(manual_dir.glob("*.png")):
                if img.name != "README.txt" and img.stat().st_size > 1000:
                    return img

        # 优先级2：商品主图
        cover = base / f"p{product_id:03d}_cover.jpg"
        if cover.exists() and cover.stat().st_size > 1000:
            return cover

        # 优先级3：第一张参考图
        ref_dir = REF_IMGS_DIR / f"p{product_id:03d}"
        if ref_dir.exists():
            refs = sorted(ref_dir.glob("*.jpg")) + sorted(ref_dir.glob("*.png"))
            if refs:
                return refs[0]

        return None


# ─────────────────────────────────────────────
# 快速运行
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from datetime import date

    collector = MaterialCollector()
    run_date = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime("%Y-%m-%d")

    # 默认只下商品主图，不做网络搜索（节省时间）
    fetch_ref = "--ref" in sys.argv
    print(f"[素材采集] 日期: {run_date} | 参考图搜索: {'开启' if fetch_ref else '关闭（加 --ref 参数开启）'}")

    results = collector.collect_for_date(run_date, fetch_reference=fetch_ref)
