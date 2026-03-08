"""
素材工厂 v1.0
基于已审核的脚本（content_tasks.status='approved'）生成素材渲染任务

支持的素材类型（第一版）：
  抖音：
    - slideshow_video    图文轮播视频（商品图+字幕轮播，15s内）
    - template_video     15秒模板视频（分镜结构化模板）
    - subtitle_video     自动字幕版（在 template_video 基础上叠加字幕轨）
    - cover_image        封面图（9:16竖版，封面大字）

  小红书：
    - xhs_image_set      9图图文组（每图一个核心卖点，含叠字）

设计原则：
  - 每条内容只讲一个核心卖点（由分镜每段独立卖点保证）
  - 视频竖版 9:16（1080×1920）
  - 视频≤15秒
  - 必须保存脚本版本号（来自 content_tasks.id + task_date）
  - 必须保存素材来源（source_content_id, source_storyboard_index）
"""

import json
import os
import sqlite3
from dataclasses import dataclass, asdict, field
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional, Dict

# ─────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "db" / "main.db"
MATERIALS_DIR = ROOT / "materials"

# 视频规格
VIDEO_SPEC = {
    "width": 1080,
    "height": 1920,
    "fps": 30,
    "max_duration_s": 15,
    "aspect": "9:16",
    "codec": "h264",
    "format": "mp4",
}

# 封面图规格
COVER_SPEC = {
    "width": 1080,
    "height": 1920,
    "format": "jpg",
    "quality": 95,
}

# 小红书图片规格
XHS_IMAGE_SPEC = {
    "width": 1080,
    "height": 1440,   # 3:4 竖版（小红书推荐比例）
    "format": "jpg",
    "quality": 92,
    "img_count": 9,   # 第一版固定9张
}

# 字体资源（相对 assets/fonts/）
FONT_MAIN = "PingFang-Bold.ttf"        # 主字幕/封面大字
FONT_SUB = "PingFang-Regular.ttf"      # 副标题/说明文字

# 素材类型枚举
MATERIAL_TYPES = {
    "douyin": ["slideshow_video", "template_video", "subtitle_video", "cover_image"],
    "xiaohongshu": ["xhs_image_set"],
}


# ─────────────────────────────────────────────
# 文件命名规范
# ─────────────────────────────────────────────

def build_filename(
    platform: str,
    material_type: str,
    product_id: int,
    script_type: str,
    content_task_id: int,
    task_date: str,
    seq: int = 0,
    ext: str = None,
) -> str:
    """
    文件命名规范：
      {platform}_{material_type}_{product_id}_{script_type}_{content_task_id}_{date}[_{seq}].{ext}

    示例：
      douyin_slideshow_video_p032_pain_point_ct001_20260308.mp4
      douyin_cover_image_p032_contrast_ct003_20260308.jpg
      xhs_image_set_p032_scene_ct002_20260308_01.jpg
      xhs_image_set_p032_scene_ct002_20260308_02.jpg

    字段说明：
      platform          : douyin / xhs
      material_type     : slideshow_video / template_video / subtitle_video / cover_image / xhs_image_set
      product_id        : p{id:03d}
      script_type       : pain_point / scene / contrast / list
      content_task_id   : ct{id:03d}（脚本版本号锚点）
      task_date         : YYYYMMDD
      seq               : 序号（xhs多图用，01-09；其他类型=0不加）
    """
    default_exts = {
        "slideshow_video": "mp4",
        "template_video": "mp4",
        "subtitle_video": "mp4",
        "cover_image": "jpg",
        "xhs_image_set": "jpg",
    }
    if ext is None:
        ext = default_exts.get(material_type, "bin")

    plat = "xhs" if platform == "xiaohongshu" else platform
    date_str = task_date.replace("-", "")
    base = f"{plat}_{material_type}_p{product_id:03d}_{script_type}_ct{content_task_id:03d}_{date_str}"
    if seq > 0:
        base += f"_{seq:02d}"
    return f"{base}.{ext}"


def build_filepath(
    status: str,  # pending / approved / published
    platform: str,
    filename: str,
    product_id: int,
) -> Path:
    """
    完整存储路径：
      materials/{status}/{platform}/p{product_id:03d}/{filename}
    """
    plat_dir = "xiaohongshu" if platform == "xiaohongshu" else platform
    return MATERIALS_DIR / status / plat_dir / f"p{product_id:03d}" / filename


# ─────────────────────────────────────────────
# 数据结构：单条素材渲染任务
# ─────────────────────────────────────────────

@dataclass
class RenderTask:
    """单条素材渲染任务（对应 DB material_render_tasks 表的一行）"""

    # 来源追溯
    content_task_id: int              # 关联的内容脚本ID（= 脚本版本号）
    product_id: int
    platform: str                     # douyin / xiaohongshu
    script_type: str                  # pain_point / scene / contrast / list
    task_date: str                    # YYYY-MM-DD

    # 素材类型
    material_type: str                # 见 MATERIAL_TYPES

    # 文件信息
    filename: str                     # 按命名规范生成
    filepath: str                     # 相对 ROOT 的路径
    seq_index: int = 0                # 序号（xhs多图 1-9，其他为0）

    # 渲染规格（JSON存储）
    render_spec: dict = field(default_factory=dict)

    # 视频元数据（仅视频类型，JSON存储）
    video_meta: dict = field(default_factory=dict)

    # 小红书图文来源标注
    source_storyboard_index: int = 0  # 对应分镜第几段的卖点（0=封面/综合）
    source_key_point: str = ""        # 该图的核心卖点文字

    # 状态
    status: str = "pending"           # pending / rendering / done / failed
    error_log: str = ""               # 失败日志（见FailureLog规范）
    retry_count: int = 0
    rendered_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


@dataclass
class MaterialManifest:
    """一条内容任务（content_task）对应的全部素材清单"""

    content_task_id: int
    product_id: int
    product_title: str
    platform: str
    script_type: str
    task_date: str
    script_version: str               # f"ct{content_task_id}_{task_date}"

    render_tasks: List[RenderTask] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.render_tasks)

    def summary(self) -> str:
        types = [t.material_type for t in self.render_tasks]
        return (
            f"[Manifest] ct{self.content_task_id} | {self.platform} | {self.script_type} "
            f"| 商品#{self.product_id} | 素材{self.total}件: {types}"
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────
# 数据结构：失败日志
# ─────────────────────────────────────────────

@dataclass
class FailureLog:
    """素材生成失败日志（写入 DB + 独立 JSON 文件）"""

    render_task_id: int               # DB中的渲染任务ID
    content_task_id: int
    product_id: int
    platform: str
    material_type: str
    filename: str

    error_code: str                   # 错误码，见下方枚举
    error_message: str                # 详细错误信息
    error_stage: str                  # 哪个阶段失败: prepare/render/export/save
    retry_count: int = 0
    failed_at: str = ""
    context: dict = field(default_factory=dict)  # 额外上下文（如缺失资源路径）

    # 错误码枚举（方便统计和自动重试判断）
    # E001: 商品图缺失（cover_img 为空或404）
    # E002: 字体文件缺失
    # E003: 渲染超时（>60s）
    # E004: 输出文件为空或损坏
    # E005: 脚本字段缺失（storyboard/subtitle 为空）
    # E006: 分辨率/时长超规
    # E099: 未知错误

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def save(self, log_dir: Path = None):
        """写入独立 JSON 文件"""
        if log_dir is None:
            log_dir = ROOT / "materials" / "failed"
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"fail_{self.error_code}_ct{self.content_task_id}_{ts}.json"
        with open(log_dir / fname, "w", encoding="utf-8") as f:
            f.write(self.to_json())
        return log_dir / fname


# ─────────────────────────────────────────────
# 视频元数据字段规范
# ─────────────────────────────────────────────

def build_video_meta(
    content_task: dict,
    material_type: str,
    duration_s: float,
    storyboard: list = None,
) -> dict:
    """
    视频元数据字段规范
    用于发布时自动填写抖音视频信息，以及本地归档

    必填字段：
      script_version    脚本版本锚点，格式 "ct{id}_{date}"
      content_task_id   内容任务ID
      product_id        商品ID
      platform          平台
      script_type       脚本类型
      material_type     素材类型
      title             抖音视频标题（来自 content_tasks.title）
      cover_copy        封面大字
      cta               CTA文案
      pub_time_suggest  建议发布时间
      mount_suggest     挂载建议
      duration_s        实际时长（秒）
      resolution        分辨率字符串 "1080x1920"
      fps               帧率
      has_subtitle      是否含字幕轨
      subtitle_text     完整字幕文案
      voiceover_text    口播文案
      key_point         核心卖点（取 storyboard 中最长字幕段）
      generated_at      生成时间
    """
    # 核心卖点 = 分镜中时长最长段的字幕
    key_point = ""
    if storyboard:
        longest = max(storyboard, key=lambda s: s.get("duration_s", 0))
        key_point = longest.get("subtitle", "") or longest.get("voiceover", "")

    return {
        # ── 来源追溯 ──────────────────────────────
        "script_version":   f"ct{content_task['id']}_{content_task['task_date']}",
        "content_task_id":  content_task["id"],
        "product_id":       content_task["product_id"],
        "platform":         content_task.get("platform", "douyin"),
        "script_type":      content_task["script_type"],
        "material_type":    material_type,

        # ── 视频发布信息 ──────────────────────────
        "title":            content_task.get("title", ""),
        "cover_copy":       content_task.get("cover_copy", ""),
        "hook_3s":          content_task.get("hook_3s", ""),
        "cta":              content_task.get("cta", ""),
        "pub_time_suggest": content_task.get("pub_time_suggest", ""),
        "mount_suggest":    content_task.get("mount_suggest", ""),

        # ── 核心卖点（每条内容只讲一个）────────────
        "key_point":        key_point,

        # ── 技术规格 ──────────────────────────────
        "duration_s":       round(duration_s, 1),
        "resolution":       f"{VIDEO_SPEC['width']}x{VIDEO_SPEC['height']}",
        "fps":              VIDEO_SPEC["fps"],
        "aspect":           VIDEO_SPEC["aspect"],
        "codec":            VIDEO_SPEC["codec"],
        "format":           VIDEO_SPEC["format"],
        "has_subtitle":     material_type == "subtitle_video",

        # ── 内容文案 ──────────────────────────────
        "subtitle_text":    content_task.get("subtitle", ""),
        "voiceover_text":   content_task.get("voiceover", ""),

        # ── 时间戳 ────────────────────────────────
        "generated_at":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ─────────────────────────────────────────────
# 素材清单生成器
# ─────────────────────────────────────────────

class MaterialFactory:
    """
    素材工厂主类
    输入：content_tasks.status='approved' 的脚本
    输出：MaterialManifest（素材清单）+ DB写入 material_render_tasks
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path

    def _get_conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def build_manifest(self, content_task: dict) -> MaterialManifest:
        """为单条已审核脚本生成完整素材清单"""
        ct = content_task
        platform = ct.get("platform", "douyin")
        script_type = ct["script_type"]
        product_id = ct["product_id"]
        task_date = ct["task_date"]
        ct_id = ct["id"]
        script_version = f"ct{ct_id}_{task_date}"

        # 解析分镜
        storyboard = []
        try:
            raw = ct.get("storyboard") or "[]"
            storyboard = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            pass

        manifest = MaterialManifest(
            content_task_id=ct_id,
            product_id=product_id,
            product_title=ct.get("product_title", ""),
            platform=platform,
            script_type=script_type,
            task_date=task_date,
            script_version=script_version,
        )

        if platform == "douyin":
            manifest.render_tasks.extend(
                self._build_douyin_tasks(ct, storyboard)
            )
        elif platform == "xiaohongshu":
            manifest.render_tasks.extend(
                self._build_xhs_tasks(ct, storyboard)
            )

        return manifest

    # ──────────────────────────────────────────
    # 抖音素材任务生成
    # ──────────────────────────────────────────

    def _build_douyin_tasks(self, ct: dict, storyboard: list) -> List[RenderTask]:
        tasks = []
        ct_id = ct["id"]
        product_id = ct["product_id"]
        script_type = ct["script_type"]
        task_date = ct["task_date"]
        total_s = sum(s.get("duration_s", 3) for s in storyboard) if storyboard else 15.0
        total_s = min(total_s, VIDEO_SPEC["max_duration_s"])

        # 核心卖点（每条只讲一个：取最长分镜段的卖点）
        key_point = ""
        if storyboard:
            longest = max(storyboard, key=lambda s: s.get("duration_s", 0))
            key_point = longest.get("subtitle", "") or longest.get("voiceover", "")

        # 1. 图文轮播视频
        fn_sw = build_filename("douyin", "slideshow_video", product_id, script_type, ct_id, task_date)
        fp_sw = build_filepath("pending", "douyin", fn_sw, product_id)
        tasks.append(RenderTask(
            content_task_id=ct_id,
            product_id=product_id,
            platform="douyin",
            script_type=script_type,
            task_date=task_date,
            material_type="slideshow_video",
            filename=fn_sw,
            filepath=str(fp_sw.relative_to(ROOT)),
            render_spec={
                "type": "slideshow_video",
                "slides": [
                    {
                        "index": i + 1,
                        "duration_s": s.get("duration_s", 3),
                        "image_source": "product_img",      # 商品图/拍摄图，人工替换
                        "overlay_subtitle": s.get("subtitle", ""),
                        "overlay_voiceover": s.get("voiceover", ""),
                        "shot_desc": s.get("shot_desc", ""),  # 拍摄指引
                        "key_point_only": True,               # 每张只展示一个核心卖点
                    }
                    for i, s in enumerate(storyboard)
                ],
                "total_duration_s": total_s,
                "resolution": f"{VIDEO_SPEC['width']}x{VIDEO_SPEC['height']}",
                "fps": VIDEO_SPEC["fps"],
                "transition": "fade",   # 转场效果
                "music_track": "assets/music/bgm_light_01.mp3",
            },
            video_meta=build_video_meta(ct, "slideshow_video", total_s, storyboard),
            source_key_point=key_point,
        ))

        # 2. 15秒模板视频
        fn_tv = build_filename("douyin", "template_video", product_id, script_type, ct_id, task_date)
        fp_tv = build_filepath("pending", "douyin", fn_tv, product_id)
        tasks.append(RenderTask(
            content_task_id=ct_id,
            product_id=product_id,
            platform="douyin",
            script_type=script_type,
            task_date=task_date,
            material_type="template_video",
            filename=fn_tv,
            filepath=str(fp_tv.relative_to(ROOT)),
            render_spec={
                "type": "template_video",
                "template": f"templates/douyin/{script_type}_template.json",
                "clips": [
                    {
                        "clip_index": i + 1,
                        "duration_s": s.get("duration_s", 3),
                        "shot_desc": s.get("shot_desc", ""),
                        "subtitle": s.get("subtitle", ""),
                        "voiceover": s.get("voiceover", ""),
                        "clip_placeholder": f"clip_{i+1:02d}.mp4",  # 人工拍摄后替换
                        "key_point": s.get("subtitle", ""),          # 该段唯一核心卖点
                    }
                    for i, s in enumerate(storyboard)
                ],
                "total_duration_s": total_s,
                "resolution": f"{VIDEO_SPEC['width']}x{VIDEO_SPEC['height']}",
                "fps": VIDEO_SPEC["fps"],
                "cover_copy": ct.get("cover_copy", ""),
                "cta_text": ct.get("cta", ""),
                "music_track": "assets/music/bgm_light_01.mp3",
            },
            video_meta=build_video_meta(ct, "template_video", total_s, storyboard),
            source_key_point=key_point,
        ))

        # 3. 自动字幕版（基于 template_video 叠字幕轨）
        fn_sub = build_filename("douyin", "subtitle_video", product_id, script_type, ct_id, task_date)
        fp_sub = build_filepath("pending", "douyin", fn_sub, product_id)
        tasks.append(RenderTask(
            content_task_id=ct_id,
            product_id=product_id,
            platform="douyin",
            script_type=script_type,
            task_date=task_date,
            material_type="subtitle_video",
            filename=fn_sub,
            filepath=str(fp_sub.relative_to(ROOT)),
            render_spec={
                "type": "subtitle_video",
                "source_video": fn_tv,       # 基于 template_video 叠字幕
                "subtitle_track": [
                    {
                        "start_s": sum(s.get("duration_s", 3) for s in storyboard[:i]),
                        "end_s": sum(s.get("duration_s", 3) for s in storyboard[:i+1]),
                        "text": s.get("subtitle", ""),
                        "font": FONT_MAIN,
                        "font_size": 52,
                        "color": "#FFFFFF",
                        "stroke_color": "#000000",
                        "stroke_width": 3,
                        "position": "bottom_center",
                        "margin_bottom": 120,
                    }
                    for i, s in enumerate(storyboard)
                ],
                "full_subtitle": ct.get("subtitle", ""),
                "resolution": f"{VIDEO_SPEC['width']}x{VIDEO_SPEC['height']}",
            },
            video_meta=build_video_meta(ct, "subtitle_video", total_s, storyboard),
            source_key_point=key_point,
        ))

        # 4. 封面图
        fn_cov = build_filename("douyin", "cover_image", product_id, script_type, ct_id, task_date)
        fp_cov = build_filepath("pending", "douyin", fn_cov, product_id)
        tasks.append(RenderTask(
            content_task_id=ct_id,
            product_id=product_id,
            platform="douyin",
            script_type=script_type,
            task_date=task_date,
            material_type="cover_image",
            filename=fn_cov,
            filepath=str(fp_cov.relative_to(ROOT)),
            render_spec={
                "type": "cover_image",
                "background": "product_img",       # 商品图铺满背景
                "overlay_gradient": "bottom_dark", # 底部深色渐变（保证文字可读）
                "main_text": ct.get("cover_copy", ""),
                "main_font": FONT_MAIN,
                "main_font_size": 80,
                "main_color": "#FFFFFF",
                "main_position": "center",
                "sub_text": ct.get("hook_3s", ""),
                "sub_font": FONT_SUB,
                "sub_font_size": 42,
                "sub_color": "#FFEE99",
                "sub_position": "center_below_main",
                "resolution": f"{COVER_SPEC['width']}x{COVER_SPEC['height']}",
                "format": COVER_SPEC["format"],
                "quality": COVER_SPEC["quality"],
            },
            video_meta={},  # 封面图无视频元数据
            source_key_point=ct.get("cover_copy", ""),
        ))

        return tasks

    # ──────────────────────────────────────────
    # 小红书素材任务生成（9图图文）
    # ──────────────────────────────────────────

    def _build_xhs_tasks(self, ct: dict, storyboard: list) -> List[RenderTask]:
        """
        小红书 9 图图文：
          图1  封面图（cover）       - 封面大标题 + 副标题
          图2  开场/对比图           - hook_3s / 痛点
          图3  核心卖点1             - 分镜第1-2段
          图4  核心卖点2             - 分镜第3段
          图5  核心卖点3             - 分镜第4段（或附加卖点）
          图6  产品细节              - 商品材质/工艺特写描述
          图7  使用场景              - 桌面/工位生活方式
          图8  价格/价值对比         - 价格锚点，强调超值感
          图9  CTA收尾图             - CTA + 话题标签引导
        """
        tasks = []
        ct_id = ct["id"]
        product_id = ct["product_id"]
        script_type = ct["script_type"]
        task_date = ct["task_date"]

        # 解析小红书图片指引（来自 xhs_img_guide）
        img_guides = []
        try:
            raw = ct.get("xhs_img_guide") or "[]"
            img_guides = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except Exception:
            pass

        # 定义9张图的内容规划
        # 每张图对应一个核心卖点（key_point_only=True）
        xhs_9_plan = [
            {
                "seq": 1, "purpose": "cover",
                "key_point": ct.get("cover_copy") or ct.get("hook_3s", ""),
                "overlay_main": ct.get("cover_copy", ""),
                "overlay_sub": ct.get("subtitle", "")[:20] if ct.get("subtitle") else "",
                "bg_type": "product_hero",       # 商品主图大图
                "shot_desc": "封面：商品最美角度，配封面大标题，构图干净",
            },
            {
                "seq": 2, "purpose": "hook",
                "key_point": ct.get("hook_3s", ""),
                "overlay_main": ct.get("hook_3s", ""),
                "overlay_sub": "",
                "bg_type": "lifestyle_scene",    # 生活场景（桌面/工位）
                "shot_desc": "开场：引发共鸣的场景或痛点画面",
            },
            {
                "seq": 3, "purpose": "key_point_1",
                "key_point": storyboard[0].get("subtitle", "") if len(storyboard) > 0 else "",
                "overlay_main": storyboard[0].get("subtitle", "") if len(storyboard) > 0 else "",
                "overlay_sub": storyboard[0].get("shot_desc", "") if len(storyboard) > 0 else "",
                "bg_type": "product_detail",
                "shot_desc": storyboard[0].get("shot_desc", "商品细节特写") if len(storyboard) > 0 else "商品细节特写",
            },
            {
                "seq": 4, "purpose": "key_point_2",
                "key_point": storyboard[1].get("subtitle", "") if len(storyboard) > 1 else "",
                "overlay_main": storyboard[1].get("subtitle", "") if len(storyboard) > 1 else "",
                "overlay_sub": "",
                "bg_type": "product_action",
                "shot_desc": storyboard[1].get("shot_desc", "商品使用/展示") if len(storyboard) > 1 else "商品使用展示",
            },
            {
                "seq": 5, "purpose": "key_point_3",
                "key_point": storyboard[2].get("subtitle", "") if len(storyboard) > 2 else "",
                "overlay_main": storyboard[2].get("subtitle", "") if len(storyboard) > 2 else "",
                "overlay_sub": "",
                "bg_type": "product_effect",
                "shot_desc": storyboard[2].get("shot_desc", "商品效果展示") if len(storyboard) > 2 else "商品效果展示",
            },
            {
                "seq": 6, "purpose": "detail",
                "key_point": "细节/工艺/材质",
                "overlay_main": "细节有讲究",
                "overlay_sub": "品质才是真的",
                "bg_type": "product_closeup",
                "shot_desc": "商品局部特写：材质/工艺/颜色细节，体现质感",
            },
            {
                "seq": 7, "purpose": "lifestyle",
                "key_point": "桌面氛围感",
                "overlay_main": "摆上去就不一样了",
                "overlay_sub": "生活方式",
                "bg_type": "lifestyle_desk",
                "shot_desc": "桌面整体场景：商品在工位/书桌上的氛围图",
            },
            {
                "seq": 8, "purpose": "price_value",
                "key_point": storyboard[-1].get("subtitle", "") if storyboard else "",
                "overlay_main": storyboard[-1].get("subtitle", "") if storyboard else "",
                "overlay_sub": "性价比拉满",
                "bg_type": "price_card",
                "shot_desc": "价格锚点图：大字显示价格，配最好看的商品图",
            },
            {
                "seq": 9, "purpose": "cta",
                "key_point": ct.get("cta", ""),
                "overlay_main": ct.get("cta", ""),
                "overlay_sub": "评论区扣「1」发你链接",
                "bg_type": "cta_card",
                "shot_desc": "收尾CTA图：行动号召 + 话题标签引导",
            },
        ]

        for plan in xhs_9_plan:
            seq = plan["seq"]
            fn = build_filename("xiaohongshu", "xhs_image_set", product_id,
                                script_type, ct_id, task_date, seq=seq)
            fp = build_filepath("pending", "xiaohongshu", fn, product_id)

            tasks.append(RenderTask(
                content_task_id=ct_id,
                product_id=product_id,
                platform="xiaohongshu",
                script_type=script_type,
                task_date=task_date,
                material_type="xhs_image_set",
                filename=fn,
                filepath=str(fp.relative_to(ROOT)),
                seq_index=seq,
                render_spec={
                    "type": "xhs_image",
                    "seq": seq,
                    "purpose": plan["purpose"],
                    "resolution": f"{XHS_IMAGE_SPEC['width']}x{XHS_IMAGE_SPEC['height']}",
                    "format": XHS_IMAGE_SPEC["format"],
                    "quality": XHS_IMAGE_SPEC["quality"],
                    "bg_type": plan["bg_type"],
                    "bg_source": "product_img",              # 商品图或生活方式图，人工替换
                    "overlay_gradient": "subtle_bottom",     # 轻渐变保证叠字可读
                    "overlay_main_text": plan["overlay_main"],
                    "overlay_main_font": FONT_MAIN,
                    "overlay_main_size": 72,
                    "overlay_main_color": "#FFFFFF",
                    "overlay_main_position": "center",
                    "overlay_sub_text": plan["overlay_sub"],
                    "overlay_sub_font": FONT_SUB,
                    "overlay_sub_size": 38,
                    "overlay_sub_color": "#FFEE99",
                    "shot_desc": plan["shot_desc"],           # 拍摄/制图指引
                    "key_point_only": True,                   # 每张只展示一个核心卖点
                },
                video_meta={},
                source_storyboard_index=seq,
                source_key_point=plan["key_point"],
            ))

        return tasks

    # ──────────────────────────────────────────
    # 批量生成 + DB写入
    # ──────────────────────────────────────────

    def run_for_date(self, task_date: str) -> List[MaterialManifest]:
        """
        对指定日期所有已审核脚本生成素材清单并写入DB
        """
        conn = self._get_conn()
        c = conn.cursor()

        c.execute("""
            SELECT ct.*, pp.title as product_title, pp.price, pp.cover_img
            FROM content_tasks ct
            JOIN product_pool pp ON ct.product_id = pp.id
            WHERE ct.status = 'approved' AND ct.task_date = ?
            ORDER BY ct.product_id, ct.script_type
        """, (task_date,))
        rows = [dict(r) for r in c.fetchall()]

        if not rows:
            print(f"[素材工厂] 无 approved 脚本 ({task_date})")
            conn.close()
            return []

        manifests = []
        for row in rows:
            manifest = self.build_manifest(row)
            manifests.append(manifest)
            self._write_manifest_to_db(conn, manifest)
            # 创建目录
            for rt in manifest.render_tasks:
                fp = ROOT / rt.filepath
                fp.parent.mkdir(parents=True, exist_ok=True)
            print(f"  {manifest.summary()}")

        conn.commit()
        conn.close()
        print(f"\n[素材工厂] 完成 | 脚本:{len(rows)}条 | 清单:{len(manifests)}份")
        return manifests

    def _write_manifest_to_db(self, conn: sqlite3.Connection, manifest: MaterialManifest):
        """将素材清单写入 material_render_tasks 表"""
        c = conn.cursor()
        for rt in manifest.render_tasks:
            c.execute("""
                INSERT OR IGNORE INTO material_render_tasks
                (content_task_id, product_id, platform, script_type, task_date,
                 material_type, filename, filepath, seq_index,
                 render_spec, video_meta,
                 source_storyboard_index, source_key_point,
                 script_version, status, created_at)
                VALUES (?,?,?,?,?, ?,?,?,?, ?,?, ?,?, ?,?,?)
            """, (
                rt.content_task_id, rt.product_id, rt.platform,
                rt.script_type, rt.task_date,
                rt.material_type, rt.filename, rt.filepath, rt.seq_index,
                json.dumps(rt.render_spec, ensure_ascii=False),
                json.dumps(rt.video_meta, ensure_ascii=False),
                rt.source_storyboard_index, rt.source_key_point,
                manifest.script_version,
                "pending",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ))


# ─────────────────────────────────────────────
# 快速验证
# ─────────────────────────────────────────────

if __name__ == "__main__":
    factory = MaterialFactory()

    import sys
    run_date = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime("%Y-%m-%d")
    print(f"[素材工厂] 运行日期: {run_date}")
    print(f"[素材工厂] DB: {DB_PATH}")
    print()

    manifests = factory.run_for_date(run_date)

    if manifests:
        print("\n─── 样例：第一条清单详情 ───")
        m = manifests[0]
        print(f"脚本版本: {m.script_version}")
        print(f"商品: #{m.product_id} 《{m.product_title[:20]}》")
        print(f"平台: {m.platform} | 类型: {m.script_type}")
        print(f"素材数: {m.total}")
        for rt in m.render_tasks:
            print(f"  [{rt.seq_index or '-'}] {rt.material_type:20} → {rt.filename}")
            print(f"       核心卖点: {rt.source_key_point[:30]}")
