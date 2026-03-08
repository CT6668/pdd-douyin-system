# 素材工厂设计文档 v1.0
> 阶段四：素材工厂搭建
> 更新日期：2026-03-08

---

## 一、素材目录结构

```
materials/
├── pending/                      ← 待渲染（素材工厂输出清单，人工拍摄完成后渲染）
│   ├── douyin/
│   │   └── p{product_id:03d}/    ← 按商品分目录
│   │       ├── douyin_slideshow_video_p032_pain_point_ct001_20260308.mp4
│   │       ├── douyin_template_video_p032_pain_point_ct001_20260308.mp4
│   │       ├── douyin_subtitle_video_p032_pain_point_ct001_20260308.mp4
│   │       └── douyin_cover_image_p032_pain_point_ct001_20260308.jpg
│   └── xiaohongshu/
│       └── p{product_id:03d}/
│           ├── xhs_image_set_p032_scene_ct002_20260308_01.jpg   ← 封面
│           ├── xhs_image_set_p032_scene_ct002_20260308_02.jpg   ← hook
│           ├── ...
│           └── xhs_image_set_p032_scene_ct002_20260308_09.jpg   ← CTA
├── approved/                     ← 人工审核通过，等待发布
│   ├── douyin/
│   └── xiaohongshu/
├── published/                    ← 已发布归档
│   ├── douyin/
│   └── xiaohongshu/
├── failed/                       ← 渲染失败日志（JSON）
│   └── fail_E001_ct001_20260308_143022.json
├── templates/                    ← 渲染模板
│   ├── douyin/
│   │   ├── pain_point_template.json
│   │   ├── scene_template.json
│   │   ├── contrast_template.json
│   │   └── list_template.json
│   └── xiaohongshu/
│       └── xhs_9img_template.json
├── assets/                       ← 公共资源
│   ├── fonts/
│   │   ├── PingFang-Bold.ttf     ← 主字幕/封面大字
│   │   └── PingFang-Regular.ttf  ← 副标题
│   ├── music/
│   │   ├── bgm_light_01.mp3      ← 轻快背景音
│   │   └── bgm_calm_01.mp3       ← 沉稳背景音
│   ├── overlays/
│   │   ├── bottom_dark.png       ← 底部渐变遮罩
│   │   └── subtle_bottom.png     ← 轻渐变遮罩（小红书用）
│   └── watermarks/
│       └── logo_small.png
└── factory.py                    ← 素材工厂主模块
```

---

## 二、文件命名规范

### 格式
```
{platform}_{material_type}_{product_id}_{script_type}_{content_task_id}_{date}[_{seq}].{ext}
```

### 字段说明

| 字段 | 格式 | 示例 | 说明 |
|------|------|------|------|
| platform | 字符串 | `douyin` / `xhs` | 平台前缀（小红书用xhs缩写） |
| material_type | 字符串 | `slideshow_video` | 素材类型（见下表） |
| product_id | `p{id:03d}` | `p032` | 商品ID，3位补零 |
| script_type | 字符串 | `pain_point` | 脚本类型 |
| content_task_id | `ct{id:03d}` | `ct001` | **脚本版本号锚点**，不可变 |
| date | `YYYYMMDD` | `20260308` | 任务日期 |
| seq | `{n:02d}` | `01`-`09` | 仅小红书多图使用 |
| ext | 扩展名 | `mp4` / `jpg` | 由素材类型决定 |

### 素材类型与扩展名

| material_type | 平台 | 扩展名 | 说明 |
|--------------|------|--------|------|
| `slideshow_video` | 抖音 | `.mp4` | 图文轮播视频，商品图+字幕轮播 |
| `template_video` | 抖音 | `.mp4` | 15秒分镜模板视频，需人工补拍片段 |
| `subtitle_video` | 抖音 | `.mp4` | 自动字幕版，基于template_video叠字幕轨 |
| `cover_image` | 抖音 | `.jpg` | 竖版封面图（1080×1920），封面大字+商品图 |
| `xhs_image_set` | 小红书 | `.jpg` | 9图图文组，每张一个核心卖点 |

### 示例文件名
```
douyin_slideshow_video_p032_pain_point_ct001_20260308.mp4
douyin_template_video_p032_pain_point_ct001_20260308.mp4
douyin_subtitle_video_p032_pain_point_ct001_20260308.mp4
douyin_cover_image_p032_contrast_ct003_20260308.jpg
xhs_image_set_p032_scene_ct002_20260308_01.jpg   ← 第1张（封面）
xhs_image_set_p032_scene_ct002_20260308_09.jpg   ← 第9张（CTA）
```

---

## 三、每条内容的素材清单格式

### 单条 MaterialManifest 结构
```json
{
  "content_task_id": 1,
  "product_id": 32,
  "product_title": "轻奢流沙画摆件创意艺术沙漏装饰品",
  "platform": "douyin",
  "script_type": "pain_point",
  "task_date": "2026-03-08",
  "script_version": "ct1_2026-03-08",
  "render_tasks": [
    { "material_type": "slideshow_video", "filename": "douyin_slideshow_video_p032_pain_point_ct001_20260308.mp4", "seq_index": 0, "source_key_point": "流沙慢慢流动，看一眼就静下来了" },
    { "material_type": "template_video",  "filename": "douyin_template_video_p032_pain_point_ct001_20260308.mp4",  "seq_index": 0, "source_key_point": "流沙慢慢流动，看一眼就静下来了" },
    { "material_type": "subtitle_video",  "filename": "douyin_subtitle_video_p032_pain_point_ct001_20260308.mp4",  "seq_index": 0, "source_key_point": "流沙慢慢流动，看一眼就静下来了" },
    { "material_type": "cover_image",     "filename": "douyin_cover_image_p032_pain_point_ct001_20260308.jpg",     "seq_index": 0, "source_key_point": "桌面焕然一新✨" }
  ]
}
```

### 小红书9图清单（1条内容 = 9张图）

| seq | purpose | 核心卖点 | 背景类型 |
|-----|---------|---------|---------|
| 01 | cover | 封面大字（≤10字） | 商品主图 |
| 02 | hook | 前3秒钩子台词 | 生活场景 |
| 03 | key_point_1 | 分镜第1段卖点 | 商品细节 |
| 04 | key_point_2 | 分镜第2段卖点 | 商品动作 |
| 05 | key_point_3 | 分镜第3段卖点 | 商品效果 |
| 06 | detail | 细节/工艺/材质 | 商品局部特写 |
| 07 | lifestyle | 桌面氛围感 | 工位/书桌场景 |
| 08 | price_value | 价格锚点 | 价格卡 |
| 09 | cta | CTA行动号召 | CTA卡 |

---

## 四、渲染任务结构（render_spec 字段详解）

### 4.1 slideshow_video（图文轮播视频）
```json
{
  "type": "slideshow_video",
  "slides": [
    {
      "index": 1,
      "duration_s": 3.0,
      "image_source": "product_img",
      "overlay_subtitle": "桌面摆了一堆没用的东西？",
      "overlay_voiceover": "桌面摆了一堆没用的东西？",
      "shot_desc": "特写：平淡或凌乱的桌面，无生气感",
      "key_point_only": true
    }
  ],
  "total_duration_s": 15.0,
  "resolution": "1080x1920",
  "fps": 30,
  "transition": "fade",
  "music_track": "assets/music/bgm_light_01.mp3"
}
```

### 4.2 template_video（15秒模板视频）
```json
{
  "type": "template_video",
  "template": "templates/douyin/pain_point_template.json",
  "clips": [
    {
      "clip_index": 1,
      "duration_s": 3.0,
      "shot_desc": "特写：平淡或凌乱的桌面，无生气感",
      "subtitle": "桌面摆了一堆没用的东西？",
      "voiceover": "桌面摆了一堆没用的东西？",
      "clip_placeholder": "clip_01.mp4",
      "key_point": "桌面摆了一堆没用的东西？"
    }
  ],
  "total_duration_s": 15.0,
  "resolution": "1080x1920",
  "fps": 30,
  "cover_copy": "桌面焕然一新✨",
  "cta_text": "点左下角橱窗，19.2元包邮 👇",
  "music_track": "assets/music/bgm_light_01.mp3"
}
```

### 4.3 subtitle_video（自动字幕版）
```json
{
  "type": "subtitle_video",
  "source_video": "douyin_template_video_p032_pain_point_ct001_20260308.mp4",
  "subtitle_track": [
    {
      "start_s": 0,
      "end_s": 3.0,
      "text": "桌面摆了一堆没用的东西？",
      "font": "PingFang-Bold.ttf",
      "font_size": 52,
      "color": "#FFFFFF",
      "stroke_color": "#000000",
      "stroke_width": 3,
      "position": "bottom_center",
      "margin_bottom": 120
    }
  ],
  "full_subtitle": "字幕全文...",
  "resolution": "1080x1920"
}
```

### 4.4 cover_image（封面图）
```json
{
  "type": "cover_image",
  "background": "product_img",
  "overlay_gradient": "bottom_dark",
  "main_text": "桌面焕然一新✨",
  "main_font": "PingFang-Bold.ttf",
  "main_font_size": 80,
  "main_color": "#FFFFFF",
  "main_position": "center",
  "sub_text": "桌面摆了一堆没用的东西？",
  "sub_font": "PingFang-Regular.ttf",
  "sub_font_size": 42,
  "sub_color": "#FFEE99",
  "sub_position": "center_below_main",
  "resolution": "1080x1920",
  "format": "jpg",
  "quality": 95
}
```

### 4.5 xhs_image_set（小红书单张图）
```json
{
  "type": "xhs_image",
  "seq": 1,
  "purpose": "cover",
  "resolution": "1080x1440",
  "format": "jpg",
  "quality": 92,
  "bg_type": "product_hero",
  "bg_source": "product_img",
  "overlay_gradient": "subtle_bottom",
  "overlay_main_text": "桌面凌乱没灵魂？试试这个",
  "overlay_main_font": "PingFang-Bold.ttf",
  "overlay_main_size": 72,
  "overlay_main_color": "#FFFFFF",
  "overlay_main_position": "center",
  "overlay_sub_text": "¥19.2 桌面变了样",
  "overlay_sub_font": "PingFang-Regular.ttf",
  "overlay_sub_size": 38,
  "overlay_sub_color": "#FFEE99",
  "shot_desc": "封面：商品最美角度，配封面大标题，构图干净",
  "key_point_only": true
}
```

---

## 五、视频元数据字段（video_meta）

> 用于发布时自动填写抖音视频信息，以及本地归档追溯

```json
{
  "script_version":    "ct1_2026-03-08",
  "content_task_id":  1,
  "product_id":       32,
  "platform":         "douyin",
  "script_type":      "pain_point",
  "material_type":    "template_video",

  "title":            "桌面一直提不起劲？试试这个流沙画",
  "cover_copy":       "桌面焕然一新✨",
  "hook_3s":          "桌面摆了一堆没用的东西？",
  "cta":              "点左下角橱窗，19.2元包邮 👇",
  "pub_time_suggest": "12:00-13:30（午休）/ 20:00-22:30（夜间黄金）",
  "mount_suggest":    "优先橱窗商品卡；若有多多进宝链接放评论区置顶",

  "key_point":        "流沙慢慢流动，看一眼就静下来了",

  "duration_s":       15.0,
  "resolution":       "1080x1920",
  "fps":              30,
  "aspect":           "9:16",
  "codec":            "h264",
  "format":           "mp4",
  "has_subtitle":     false,

  "subtitle_text":    "桌面摆了一堆没用的东西？ | 直到我发现了这个流沙画 | ...",
  "voiceover_text":   "桌面摆了一堆没用的东西？。直到朋友给我推荐了这个流沙画...",

  "generated_at":     "2026-03-08 18:06:29"
}
```

### 字段说明

| 字段 | 类型 | 说明 | 是否必填 |
|------|------|------|---------|
| `script_version` | str | 脚本版本锚点，`ct{id}_{date}`，**不可变** | ✅ |
| `content_task_id` | int | 来源脚本ID | ✅ |
| `product_id` | int | 商品ID | ✅ |
| `key_point` | str | **核心卖点（每条内容只讲一个）**，取最长分镜段字幕 | ✅ |
| `title` | str | 抖音视频标题（≤20字） | ✅ |
| `duration_s` | float | 实际时长，必须≤15s | ✅ |
| `resolution` | str | 固定 `1080x1920`（竖版9:16） | ✅ |
| `has_subtitle` | bool | 是否叠字幕轨（subtitle_video=true，其他=false） | ✅ |
| `script_type` | str | 脚本类型，影响素材风格 | ✅ |
| `pub_time_suggest` | str | 建议发布时间，来自脚本 | 参考 |
| `mount_suggest` | str | 挂载建议，来自脚本 | 参考 |

---

## 六、失败日志格式（FailureLog）

### 错误码枚举

| 错误码 | 含义 | 是否自动重试 |
|--------|------|------------|
| `E001` | 商品图缺失（cover_img为空或404） | ❌ 需人工补图 |
| `E002` | 字体文件缺失 | ❌ 需补充资源 |
| `E003` | 渲染超时（>60s） | ✅ 最多3次 |
| `E004` | 输出文件为空或损坏 | ✅ 最多3次 |
| `E005` | 脚本字段缺失（storyboard/subtitle为空） | ❌ 需人工修正脚本 |
| `E006` | 分辨率/时长超规 | ❌ 需调整渲染参数 |
| `E099` | 未知错误 | ✅ 最多1次 |

### 失败日志 JSON 格式
```json
{
  "render_task_id": 42,
  "content_task_id": 1,
  "product_id": 32,
  "platform": "douyin",
  "material_type": "template_video",
  "filename": "douyin_template_video_p032_pain_point_ct001_20260308.mp4",

  "error_code": "E001",
  "error_message": "商品图URL为空，无法获取背景图",
  "error_stage": "prepare",
  "retry_count": 0,
  "failed_at": "2026-03-08 18:30:22",

  "context": {
    "cover_img_field": null,
    "product_id": 32,
    "suggestion": "请在 product_pool 表补充 cover_img 字段，或手动放置商品图"
  }
}
```

### 日志文件路径
```
materials/failed/fail_{error_code}_ct{content_task_id}_{YYYYMMDD_HHmmss}.json
```

---

## 七、素材工厂流程

```
content_tasks (status=approved)
    │
    ▼
MaterialFactory.build_manifest()
    │  ├── 抖音：生成4种素材任务
    │  │     slideshow_video + template_video + subtitle_video + cover_image
    │  └── 小红书：生成9张图任务
    │        xhs_image_set × 9（每张一个核心卖点）
    │
    ▼
material_render_tasks (status=pending) 写入DB
    │
    ▼ [等待人工拍摄/补充商品图]
    │
    ▼
渲染执行器（阶段五实现）
    │  ├── 成功 → status=done → 移入 pending/ 目录
    │  └── 失败 → status=failed → 写入 failed/ 日志
    │
    ▼
人工审核（素材质量）
    │
    ▼
approved/ 目录 → 准备发布
```

---

## 八、设计约束

| 约束 | 规则 |
|------|------|
| 每条内容只讲一个核心卖点 | `key_point_only=true`，`key_point` 字段记录该条卖点 |
| 视频竖版 | 固定 1080×1920，9:16，不接受横版 |
| 视频≤15秒 | `total_duration_s ≤ 15`，超出自动截断最后一段 |
| 脚本版本号不可变 | `script_version = ct{id}_{date}`，素材和脚本强关联 |
| 小红书9图 | 固定9张，每张 1080×1440（3:4），每张一个核心卖点 |
| 素材来源可追溯 | `source_storyboard_index + source_key_point` 标注每张素材来源分镜 |
