"""
素材渲染引擎 v1.0
基于商品图片 + 脚本文案，自动合成：
  1. 抖音封面图     (1080×1920, 9:16竖版)
  2. 小红书9图图文  (1080×1440, 3:4竖版，每张一个核心卖点)

依赖：Pillow（已内置）
字体：系统自带 / 内置字体回退
"""

import json
import os
import sqlite3
from io import BytesIO
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db" / "main.db"
RAW_IMGS_DIR = ROOT / "data" / "raw" / "product_imgs"
REF_IMGS_DIR = ROOT / "data" / "raw" / "reference_imgs"
PENDING_DIR = ROOT / "materials" / "pending"
FONT_DIR = ROOT / "materials" / "assets" / "fonts"

# 视频/图片规格
DOUYIN_SIZE = (1080, 1920)    # 9:16
XHS_SIZE = (1080, 1440)       # 3:4

# 品牌色彩方案
COLORS = {
    "white":       "#FFFFFF",
    "black":       "#000000",
    "warm_yellow": "#FFE066",
    "coral":       "#FF6B6B",
    "dark_overlay":"rgba(0,0,0,0.55)",
    "card_bg":     "#1A1A2E",
    "accent":      "#FFD700",
    "text_sub":    "#CCCCCC",
}


# ─────────────────────────────────────────────
# 字体加载（多级回退）
# ─────────────────────────────────────────────

def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """加载字体，优先内置，回退系统字体"""
    # macOS 中文字体路径
    macos_fonts = [
        "/System/Library/Fonts/PingFang.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    # 内置字体
    custom_fonts = [
        str(FONT_DIR / ("PingFang-Bold.ttf" if bold else "PingFang-Regular.ttf")),
    ]

    for path in custom_fonts + macos_fonts:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue

    # 最终回退：默认字体（不含中文，仅做占位）
    return ImageFont.load_default()


# ─────────────────────────────────────────────
# 图像处理工具
# ─────────────────────────────────────────────

def load_and_resize(img_path: Path, target_size: Tuple[int, int], mode: str = "fill") -> Image.Image:
    """
    加载图片并调整尺寸
    mode: fill=裁剪填充(保持比例), fit=等比缩放留白
    """
    img = Image.open(img_path).convert("RGB")
    tw, th = target_size
    iw, ih = img.size

    if mode == "fill":
        # 等比缩放到覆盖目标尺寸，然后中心裁剪
        scale = max(tw / iw, th / ih)
        new_w = int(iw * scale)
        new_h = int(ih * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        x = (new_w - tw) // 2
        y = (new_h - th) // 2
        img = img.crop((x, y, x + tw, y + th))
    else:
        img.thumbnail(target_size, Image.LANCZOS)

    return img


def add_gradient_overlay(img: Image.Image, direction: str = "bottom", alpha: int = 160) -> Image.Image:
    """添加渐变遮罩（增强文字可读性）"""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = img.size

    if direction == "bottom":
        for y in range(h // 2, h):
            a = int(alpha * (y - h // 2) / (h // 2))
            draw.line([(0, y), (w, y)], fill=(0, 0, 0, a))
    elif direction == "top":
        for y in range(0, h // 2):
            a = int(alpha * (1 - y / (h // 2)))
            draw.line([(0, y), (w, y)], fill=(0, 0, 0, a))
    elif direction == "full":
        overlay = Image.new("RGBA", img.size, (0, 0, 0, alpha))

    result = img.convert("RGBA")
    result = Image.alpha_composite(result, overlay)
    return result.convert("RGB")


def draw_text_with_shadow(
    draw: ImageDraw.Draw,
    text: str,
    position: Tuple[int, int],
    font: ImageFont.FreeTypeFont,
    fill: str = "#FFFFFF",
    shadow_offset: int = 3,
    shadow_alpha: int = 180,
    align: str = "center",
    img_width: int = 1080,
    max_width: int = None,
) -> int:
    """绘制带阴影的文字，返回文字高度"""
    if not text:
        return 0

    # 自动换行
    max_w = max_width or (img_width - 80)
    lines = _wrap_text(text, font, max_w)

    x, y = position
    line_h = font.size + 12
    total_h = len(lines) * line_h

    for line in lines:
        bbox = font.getbbox(line)
        line_w = bbox[2] - bbox[0]

        # 对齐调整
        if align == "center":
            lx = (img_width - line_w) // 2
        elif align == "left":
            lx = x
        else:
            lx = x

        # 阴影
        draw.text((lx + shadow_offset, y + shadow_offset),
                  line, font=font, fill=(0, 0, 0, shadow_alpha))
        # 主体
        draw.text((lx, y), line, font=font, fill=fill)
        y += line_h

    return total_h


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    """中文文本自动换行"""
    lines = []
    current = ""
    for char in text:
        test = current + char
        bbox = font.getbbox(test)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines or [text]


def add_price_badge(img: Image.Image, price: float, position: str = "top_right") -> Image.Image:
    """在图片上添加价格角标"""
    img = img.copy()
    draw = ImageDraw.Draw(img)
    w, h = img.size

    price_text = f"¥{int(price) if price == int(price) else f'{price:.1f}'}"
    font = _load_font(48, bold=True)

    # 红色价格标签
    bbox = font.getbbox(price_text)
    pw = bbox[2] - bbox[0] + 24
    ph = bbox[3] - bbox[1] + 16

    if position == "top_right":
        x, y = w - pw - 20, 20
    elif position == "bottom_right":
        x, y = w - pw - 20, h - ph - 20
    else:
        x, y = 20, 20

    # 绘制圆角矩形背景
    draw.rounded_rectangle([x, y, x + pw, y + ph], radius=8, fill="#FF3B30")
    draw.text((x + 12, y + 8), price_text, font=font, fill="#FFFFFF")

    return img


# ─────────────────────────────────────────────
# 占位图生成（无商品图时的备用）
# ─────────────────────────────────────────────

def make_placeholder_image(size: Tuple[int, int], product_title: str, color_idx: int = 0) -> Image.Image:
    """生成品牌色占位图（无商品图时使用）"""
    palettes = [
        ("#2C3E50", "#3498DB"),  # 深蓝 + 蓝
        ("#1A1A2E", "#E94560"),  # 深紫 + 红
        ("#0F3460", "#16213E"),  # 深蓝渐变
        ("#2D4739", "#4CAF50"),  # 深绿 + 绿
        ("#3D2B1F", "#C8860A"),  # 棕 + 金
    ]
    bg_color, accent = palettes[color_idx % len(palettes)]

    img = Image.new("RGB", size, bg_color)
    draw = ImageDraw.Draw(img)
    w, h = size

    # 渐变效果（用水平条模拟）
    for i in range(h):
        ratio = i / h
        r1, g1, b1 = _hex_to_rgb(bg_color)
        r2, g2, b2 = _hex_to_rgb(accent)
        r = int(r1 + (r2 - r1) * ratio * 0.3)
        g = int(g1 + (g2 - g1) * ratio * 0.3)
        b = int(b1 + (b2 - b1) * ratio * 0.3)
        draw.line([(0, i), (w, i)], fill=(r, g, b))

    # 产品名
    font = _load_font(56, bold=True)
    draw_text_with_shadow(draw, product_title[:10], (w // 2, h // 2 - 60),
                          font, fill="#FFFFFF", img_width=w)
    font_sub = _load_font(36)
    draw_text_with_shadow(draw, "桌面摆件好物推荐", (w // 2, h // 2 + 40),
                          font_sub, fill="#CCCCCC", img_width=w)
    return img


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


# ─────────────────────────────────────────────
# 渲染器核心类
# ─────────────────────────────────────────────

class MaterialRenderer:
    """素材渲染主类"""

    def __init__(self):
        self.db_path = DB_PATH
        # 确保输出目录存在
        for sub in ["douyin", "xiaohongshu"]:
            (PENDING_DIR / sub).mkdir(parents=True, exist_ok=True)

    def _get_product_image(self, product_id: int, product_title: str = "") -> Optional[Image.Image]:
        """获取商品图（优先级：人工上传 > 主图 > 参考图 > 占位图）"""
        import sys
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from materials.collector import MaterialCollector
        collector = MaterialCollector()
        best = collector.get_best_image(product_id)
        if best:
            return Image.open(best).convert("RGB")
        # 生成占位图
        return None

    # ──────────────────────────────────────────
    # 抖音封面图渲染
    # ──────────────────────────────────────────

    def render_cover_image(
        self,
        render_spec: dict,
        product_id: int,
        product_title: str,
        price: float,
        output_path: Path,
    ) -> bool:
        """渲染抖音封面图（1080×1920）"""
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # 获取背景图
            bg_img = self._get_product_image(product_id, product_title)
            if bg_img is None:
                # 用占位图
                bg_img = make_placeholder_image(DOUYIN_SIZE, product_title, product_id % 5)
            else:
                # bg_img 已是 Image 对象，直接 resize
                tw, th = DOUYIN_SIZE
                iw, ih = bg_img.size
                scale = max(tw / iw, th / ih)
                bg_img = bg_img.resize((int(iw * scale), int(ih * scale)), Image.LANCZOS)
                x = (bg_img.width - tw) // 2
                y = (bg_img.height - th) // 2
                bg_img = bg_img.crop((x, y, x + tw, y + th))

            # 底部渐变遮罩
            bg_img = add_gradient_overlay(bg_img, direction="bottom", alpha=180)

            # 顶部轻遮罩（保护标题区域）
            bg_img = add_gradient_overlay(bg_img, direction="top", alpha=60)

            draw = ImageDraw.Draw(bg_img)
            w, h = DOUYIN_SIZE

            # 主封面大字（cover_copy，≤10字）
            main_text = render_spec.get("main_text", "")
            if main_text:
                font_main = _load_font(88, bold=True)
                y_main = int(h * 0.62)
                draw_text_with_shadow(draw, main_text, (w // 2, y_main),
                                      font_main, fill="#FFFFFF", img_width=w)

            # 副标题（hook_3s）
            sub_text = render_spec.get("sub_text", "")
            if sub_text:
                font_sub = _load_font(46)
                y_sub = int(h * 0.62) + 120
                draw_text_with_shadow(draw, sub_text[:20], (w // 2, y_sub),
                                      font_sub, fill="#FFE066", img_width=w,
                                      max_width=900)

            # 价格角标
            if price:
                bg_img = add_price_badge(bg_img, price, position="top_right")
                draw = ImageDraw.Draw(bg_img)

            # 底部CTA提示条
            font_cta = _load_font(38)
            cta_y = int(h * 0.90)
            draw.rounded_rectangle(
                [w // 2 - 280, cta_y - 8, w // 2 + 280, cta_y + 58],
                radius=30, fill=(255, 59, 48, 220)
            )
            draw.text((w // 2 - 240, cta_y), "👇 点左下角橱窗直接买",
                      font=font_cta, fill="#FFFFFF")

            bg_img.save(str(output_path), "JPEG", quality=95)
            return True

        except Exception as e:
            print(f"  ✗ 封面图渲染失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    # ──────────────────────────────────────────
    # 小红书9图渲染
    # ──────────────────────────────────────────

    def render_xhs_image(
        self,
        render_spec: dict,
        product_id: int,
        product_title: str,
        price: float,
        output_path: Path,
    ) -> bool:
        """渲染小红书单张图（1080×1440）"""
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)

            seq = render_spec.get("seq", 1)
            purpose = render_spec.get("purpose", "detail")
            main_text = render_spec.get("overlay_main_text", "")
            sub_text = render_spec.get("overlay_sub_text", "")
            bg_type = render_spec.get("bg_type", "product_hero")

            # 获取背景图
            bg_img = self._get_product_image(product_id, product_title)
            if bg_img is None:
                bg_img = make_placeholder_image(XHS_SIZE, product_title, (product_id + seq) % 5)
            else:
                # bg_img 已是 Image 对象，直接 resize
                tw, th = XHS_SIZE
                iw, ih = bg_img.size
                scale = max(tw / iw, th / ih)
                bg_img = bg_img.resize((int(iw * scale), int(ih * scale)), Image.LANCZOS)
                x = (bg_img.width - tw) // 2
                y = (bg_img.height - th) // 2
                bg_img = bg_img.crop((x, y, x + tw, y + th))

            # CTA图和价格图用特殊样式
            if purpose in ("cta", "price_value"):
                bg_img = self._render_card_style(bg_img, purpose, main_text, sub_text,
                                                  product_title, price)
            else:
                # 常规内容图：渐变 + 叠字
                bg_img = add_gradient_overlay(
                    bg_img,
                    direction="bottom" if seq > 1 else "full",
                    alpha=150 if purpose == "cover" else 120
                )
                draw = ImageDraw.Draw(bg_img)
                w, h = XHS_SIZE

                # 封面图：大标题居中
                if purpose == "cover":
                    font_main = _load_font(80, bold=True)
                    y_pos = int(h * 0.55)
                    draw_text_with_shadow(draw, main_text, (w // 2, y_pos),
                                          font_main, fill="#FFFFFF", img_width=w)
                    if sub_text:
                        font_sub = _load_font(42)
                        draw_text_with_shadow(draw, sub_text[:18], (w // 2, y_pos + 110),
                                              font_sub, fill="#FFE066", img_width=w)
                    # 封面底部：商品名
                    font_name = _load_font(34)
                    draw_text_with_shadow(draw, product_title[:15], (w // 2, h - 100),
                                          font_name, fill="#CCCCCC", img_width=w)

                else:
                    # 内容图：底部卡片式叠字
                    if main_text:
                        card_h = 180 if not sub_text else 220
                        card_y = h - card_h - 40
                        draw.rounded_rectangle(
                            [40, card_y, w - 40, h - 40],
                            radius=16,
                            fill=(0, 0, 0, 160)
                        )
                        font_main = _load_font(58, bold=True)
                        draw_text_with_shadow(draw, main_text[:16], (w // 2, card_y + 28),
                                              font_main, fill="#FFFFFF", img_width=w - 100)
                        if sub_text:
                            font_sub = _load_font(36)
                            draw_text_with_shadow(draw, sub_text[:20], (w // 2, card_y + 110),
                                                  font_sub, fill="#FFE066", img_width=w - 100)

                # 图片序号标记（小角标）
                font_seq = _load_font(30, bold=True)
                draw.ellipse([w - 72, 20, w - 20, 72], fill=(255, 59, 48))
                draw.text((w - 57, 28), str(seq), font=font_seq, fill="#FFFFFF")

            bg_img.save(str(output_path), "JPEG", quality=92)
            return True

        except Exception as e:
            print(f"  ✗ XHS图渲染失败 (seq={render_spec.get('seq')}): {e}")
            return False

    def _render_card_style(
        self,
        bg_img: Image.Image,
        purpose: str,
        main_text: str,
        sub_text: str,
        product_title: str,
        price: float,
    ) -> Image.Image:
        """渲染价格卡/CTA卡样式"""
        bg_img = add_gradient_overlay(bg_img, direction="full", alpha=140)
        draw = ImageDraw.Draw(bg_img)
        w, h = XHS_SIZE

        if purpose == "price_value":
            # 价格大字居中
            price_str = f"¥{int(price) if price == int(price) else f'{price:.1f}'}"
            font_price = _load_font(120, bold=True)
            draw_text_with_shadow(draw, price_str, (w // 2, int(h * 0.38)),
                                  font_price, fill="#FFD700", img_width=w)
            font_label = _load_font(48)
            draw_text_with_shadow(draw, "超值入手！", (w // 2, int(h * 0.58)),
                                  font_label, fill="#FFFFFF", img_width=w)
            if main_text:
                font_sub = _load_font(40)
                draw_text_with_shadow(draw, main_text[:18], (w // 2, int(h * 0.70)),
                                      font_sub, fill="#CCCCCC", img_width=w)

        elif purpose == "cta":
            # CTA引导
            font_cta = _load_font(64, bold=True)
            draw_text_with_shadow(draw, "感兴趣的宝子👇", (w // 2, int(h * 0.35)),
                                  font_cta, fill="#FFFFFF", img_width=w)
            font_action = _load_font(52)
            draw_text_with_shadow(draw, "评论区扣「1」发你链接", (w // 2, int(h * 0.50)),
                                  font_action, fill="#FFE066", img_width=w)
            if main_text:
                font_cta2 = _load_font(40)
                draw_text_with_shadow(draw, main_text[:20], (w // 2, int(h * 0.65)),
                                      font_cta2, fill="#CCCCCC", img_width=w)
            # 底部品牌名
            font_brand = _load_font(34)
            draw_text_with_shadow(draw, "📦 拼多多好物 | 性价比之选", (w // 2, h - 80),
                                  font_brand, fill="#AAAAAA", img_width=w)

        return bg_img

    # ──────────────────────────────────────────
    # 批量渲染主入口
    # ──────────────────────────────────────────

    def render_for_date(self, task_date: str) -> dict:
        """批量渲染指定日期的所有pending素材任务"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # 查询待渲染任务（只处理 cover_image 和 xhs_image_set，slideshow/template需人工拍摄）
        c.execute("""
            SELECT mrt.*, pp.title as product_title, pp.price
            FROM material_render_tasks mrt
            JOIN product_pool pp ON mrt.product_id = pp.id
            WHERE mrt.status = 'pending'
              AND mrt.task_date = ?
              AND mrt.material_type IN ('cover_image', 'xhs_image_set')
            ORDER BY mrt.product_id, mrt.material_type, mrt.seq_index
        """, (task_date,))
        tasks = [dict(r) for r in c.fetchall()]
        conn.close()

        print(f"[渲染引擎] 待渲染任务: {len(tasks)} 件")
        stats = {"done": 0, "failed": 0, "skipped": 0}

        for task in tasks:
            output_path = PENDING_DIR / task["platform"] / f"p{task['product_id']:03d}" / task["filename"]
            output_path.parent.mkdir(parents=True, exist_ok=True)

            render_spec = {}
            try:
                render_spec = json.loads(task.get("render_spec") or "{}")
            except Exception:
                pass

            ok = False
            if task["material_type"] == "cover_image":
                print(f"  [封面图] {task['filename']}")
                ok = self.render_cover_image(
                    render_spec,
                    product_id=task["product_id"],
                    product_title=task["product_title"],
                    price=task["price"],
                    output_path=output_path,
                )
            elif task["material_type"] == "xhs_image_set":
                print(f"  [XHS图{task['seq_index']:02d}] {task['filename']}")
                ok = self.render_xhs_image(
                    render_spec,
                    product_id=task["product_id"],
                    product_title=task["product_title"],
                    price=task["price"],
                    output_path=output_path,
                )

            # 更新DB状态
            new_status = "done" if ok else "failed"
            stats["done" if ok else "failed"] += 1
            self._update_task_status(task["id"], new_status,
                                     error_message="" if ok else "渲染失败，详见日志")

        total = stats["done"] + stats["failed"]
        print(f"\n[渲染完成] 总计:{total} | ✅成功:{stats['done']} | ✗失败:{stats['failed']}")
        return stats

    def _update_task_status(self, task_id: int, status: str, error_message: str = ""):
        conn = sqlite3.connect(str(self.db_path))
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("""
            UPDATE material_render_tasks
            SET status=?, error_message=?, rendered_at=?, updated_at=?
            WHERE id=?
        """, (status, error_message, now if status == "done" else None, now, task_id))
        conn.commit()
        conn.close()


# ─────────────────────────────────────────────
# 快速运行
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from datetime import date

    renderer = MaterialRenderer()
    run_date = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime("%Y-%m-%d")
    print(f"[渲染引擎] 日期: {run_date}")
    stats = renderer.render_for_date(run_date)
