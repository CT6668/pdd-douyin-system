"""
人工上传素材管理模块 v1.0

功能：
  1. 扫描人工上传目录，将新图片注册到 DB
  2. 重新触发渲染（人工图替换自动采集图后可重渲染）
  3. 查看素材状态总览
  4. 标记素材为 approved（可发布）

使用方式：
  python materials/uploader.py scan              # 扫描所有人工上传目录
  python materials/uploader.py status            # 查看素材状态总览
  python materials/uploader.py rerender 2026-03-08  # 重新渲染（人工图替换后）
  python materials/uploader.py approve-all 2026-03-08  # 批量标记为 approved

人工上传目录结构：
  data/raw/product_imgs/p{id:03d}/manual/
    main_01.jpg      ← 商品主图
    main_02.jpg      ← 商品次图（可选）
    scene_01.jpg     ← 桌面/工位场景图
    detail_01.jpg    ← 细节特写（可选）
"""

import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "db" / "main.db"
RAW_IMGS_DIR = ROOT / "data" / "raw" / "product_imgs"
PENDING_DIR = ROOT / "materials" / "pending"
APPROVED_DIR = ROOT / "materials" / "approved"


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────
# 1. 扫描人工上传目录
# ─────────────────────────────────────────────

def scan_manual_uploads() -> dict:
    """
    扫描所有商品的 manual/ 目录，返回有手动上传图片的商品信息
    """
    result = {}
    for product_dir in sorted(RAW_IMGS_DIR.iterdir()):
        if not product_dir.is_dir():
            continue
        manual_dir = product_dir / "manual"
        if not manual_dir.exists():
            continue

        imgs = [
            f for f in sorted(manual_dir.iterdir())
            if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
            and f.stat().st_size > 1000
        ]

        if imgs:
            pid = product_dir.name  # "p032"
            result[pid] = {
                "dir": manual_dir,
                "images": imgs,
                "count": len(imgs),
            }
            print(f"  [{pid}] 发现 {len(imgs)} 张手动上传图: {[i.name for i in imgs]}")

    if not result:
        print("  暂无手动上传图片")
    return result


# ─────────────────────────────────────────────
# 2. 素材状态总览
# ─────────────────────────────────────────────

def show_status(task_date: str = None):
    """打印素材任务状态总览"""
    conn = get_conn()
    c = conn.cursor()

    where = f"WHERE task_date = '{task_date}'" if task_date else ""

    c.execute(f"""
        SELECT platform, material_type, status, COUNT(*) as cnt
        FROM material_render_tasks
        {where}
        GROUP BY platform, material_type, status
        ORDER BY platform, material_type, status
    """)
    rows = c.fetchall()

    print(f"\n{'='*60}")
    print(f"素材渲染任务状态总览{' · ' + task_date if task_date else ''}")
    print(f"{'='*60}")
    print(f"{'平台':<14} {'类型':<22} {'状态':<12} {'数量':>4}")
    print(f"{'-'*60}")
    for r in rows:
        status_icon = {"done": "✅", "pending": "⏳", "failed": "❌", "rendering": "🔄"}.get(r["status"], "?")
        print(f"  {r['platform']:<12} {r['material_type']:<22} {status_icon} {r['status']:<10} {r['cnt']:>4}")

    # 文件实际存在统计
    c.execute(f"SELECT filepath, status FROM material_render_tasks {where}")
    all_tasks = c.fetchall()
    conn.close()

    existing = sum(1 for t in all_tasks if (ROOT / t["filepath"]).exists())
    done_in_db = sum(1 for t in all_tasks if t["status"] == "done")

    print(f"{'-'*60}")
    print(f"  DB标记done: {done_in_db} | 文件实际存在: {existing} | 总计: {len(all_tasks)}")
    print(f"{'='*60}\n")


# ─────────────────────────────────────────────
# 3. 重新触发渲染（人工图替换后）
# ─────────────────────────────────────────────

def rerender(task_date: str, material_types: list = None):
    """
    重置任务状态为pending，然后重新渲染
    适用于：人工上传了新图片，想重新生成封面图/XHS图
    """
    if material_types is None:
        material_types = ["cover_image", "xhs_image_set"]

    conn = get_conn()
    c = conn.cursor()

    placeholders = ",".join("?" * len(material_types))
    c.execute(f"""
        UPDATE material_render_tasks
        SET status='pending', error_message='', rendered_at=NULL
        WHERE task_date=? AND material_type IN ({placeholders})
    """, [task_date] + material_types)
    reset_count = c.rowcount
    conn.commit()
    conn.close()

    print(f"[重渲染] 重置 {reset_count} 条任务 → pending")

    # 触发渲染器
    from materials.renderer import MaterialRenderer
    renderer = MaterialRenderer()
    stats = renderer.render_for_date(task_date)
    return stats


# ─────────────────────────────────────────────
# 4. 批量标记 approved（可发布）
# ─────────────────────────────────────────────

def approve_materials(task_date: str, material_type: str = None) -> int:
    """
    将 pending/ 中的 done 素材移动到 approved/，并更新DB状态
    这是发布前的最后一步人工确认
    """
    conn = get_conn()
    c = conn.cursor()

    where_extra = f"AND material_type='{material_type}'" if material_type else ""
    c.execute(f"""
        SELECT id, platform, material_type, filename, filepath
        FROM material_render_tasks
        WHERE task_date=? AND status='done' {where_extra}
    """, (task_date,))
    tasks = [dict(r) for r in c.fetchall()]

    moved = 0
    for task in tasks:
        src = ROOT / task["filepath"]
        if not src.exists():
            print(f"  ✗ 文件不存在: {src.name}")
            continue

        # 目标：approved/
        plat = "xiaohongshu" if task["platform"] == "xiaohongshu" else task["platform"]
        product_dir = src.parent.name  # p032
        dst_dir = APPROVED_DIR / plat / product_dir
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / task["filename"]

        shutil.copy2(src, dst)
        new_path = str(dst.relative_to(ROOT))

        c.execute("""
            UPDATE material_render_tasks
            SET status='approved', filepath=?, updated_at=?
            WHERE id=?
        """, (new_path, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), task["id"]))
        moved += 1
        print(f"  ✓ {task['filename']}")

    conn.commit()
    conn.close()
    print(f"\n[Approve完成] 共 {moved}/{len(tasks)} 件素材移入 approved/")
    return moved


# ─────────────────────────────────────────────
# 5. 人工上传入口说明
# ─────────────────────────────────────────────

def show_upload_guide():
    """打印人工上传指南"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT DISTINCT pp.id, pp.title, pp.price
        FROM content_tasks ct JOIN product_pool pp ON ct.product_id=pp.id
        WHERE ct.status='approved'
        ORDER BY pp.id
    """)
    products = c.fetchall()
    conn.close()

    print("\n" + "="*60)
    print("📷 人工上传素材指南")
    print("="*60)
    print("将拍摄好的商品图放入对应商品目录：")
    print()
    for p in products:
        upload_dir = RAW_IMGS_DIR / f"p{p['id']:03d}" / "manual"
        upload_dir.mkdir(parents=True, exist_ok=True)
        print(f"  #{p['id']:03d} 《{p['title'][:20]}》 ¥{p['price']}")
        print(f"       目录: {upload_dir}")
    print()
    print("文件命名规范：")
    print("  main_01.jpg    ← 商品主图（必传）")
    print("  main_02.jpg    ← 商品多角度图（可选）")
    print("  scene_01.jpg   ← 工位/桌面场景图（可选，XHS效果更好）")
    print("  detail_01.jpg  ← 细节/工艺特写（可选）")
    print()
    print("上传完成后执行重渲染：")
    print("  python materials/uploader.py rerender 2026-03-08")
    print("="*60)


# ─────────────────────────────────────────────
# 命令行入口
# ─────────────────────────────────────────────

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    date_arg = sys.argv[2] if len(sys.argv) > 2 else "2026-03-08"

    if cmd == "scan":
        print("[扫描人工上传目录]")
        scan_manual_uploads()

    elif cmd == "status":
        show_status(date_arg if len(sys.argv) > 2 else None)

    elif cmd == "rerender":
        print(f"[重新渲染] 日期: {date_arg}")
        rerender(date_arg)

    elif cmd == "approve-all":
        print(f"[批量Approve] 日期: {date_arg}")
        approve_materials(date_arg)

    elif cmd == "guide":
        show_upload_guide()

    else:
        print(f"用法: python materials/uploader.py [scan|status|rerender|approve-all|guide] [date]")
