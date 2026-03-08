"""
LLM 内容生成器 v1.0
支持 DeepSeek / 通义千问（兼容 OpenAI SDK 接口）
降级策略：API Key 未配置 / 调用失败 / JSON 解析失败 → 自动回退模板引擎

使用：
    from content.llm_generator import LLMContentGenerator
    gen = LLMContentGenerator(config)
    script = gen.generate_douyin(product_dict, "contrast")
    note   = gen.generate_xhs(product_dict, "scene")
"""

import json
import re
import sys
from datetime import date
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from utils.logger import get_logger

logger = get_logger("llm_generator")


# ─────────────────────────────────────────────
# 脚本类型说明
# ─────────────────────────────────────────────
SCRIPT_TYPE_INFO = {
    "pain_point": (
        "痛点型",
        "结构：桌面/工位的某个痛点 → 发现这个商品解决了问题 → CTA。"
        "前3秒用问句戳痛点，让观众产生共鸣后继续看。",
    ),
    "scene": (
        "场景型",
        "结构：日常生活场景导入（打工人/学生桌面）→ 商品自然融入生活 → 氛围升华 → CTA。"
        "治愈感为主调，让人想要拥有这种生活状态。",
    ),
    "contrast": (
        "反差型",
        "结构：低预期铺垫（就这个价能有多好）→ 开箱/上手意外惊喜 → 全面展示 → CTA。"
        "反差越大越好，视觉冲击强。",
    ),
    "list": (
        "清单型",
        "结构：数字钩子（3个理由买它）→ 依次展示每个卖点 → 价格揭晓 → CTA。"
        "节奏快，信息密度高，适合理性消费者。",
    ),
}

# 合规禁用词（嵌入 Prompt 约束 LLM 输出）
FORBIDDEN_WORDS = [
    "治疗", "治愈", "治好", "功效", "疗效", "包治", "根治",
    "保证", "绝对", "100%", "最好", "第一", "专利", "国家认证",
    "买了不后悔", "无效退款", "假一赔十",
]

# ─────────────────────────────────────────────
# 抖音脚本 Prompt
# ─────────────────────────────────────────────
DOUYIN_PROMPT = """你是一位资深抖音带货脚本创作者，专注桌面摆件/好物种草类商品。

## 商品信息
- 商品名称：{title}
- 售价：¥{price}
- 月销量：约 {sales_30d} 件
- 佣金：{commission_rate}%（单件 ¥{commission_amt}）

## 任务
为上述商品生成一条「{type_cn}」类型的抖音短视频脚本（约15-20秒，4个分镜）。

## 脚本类型说明
{type_desc}

## 输出格式（严格 JSON，不要有 JSON 以外的任何文字）
```json
{{
  "title": "视频标题（≤20字）",
  "cover_copy": "封面大字（≤10字，强吸引力）",
  "hook_3s": "前3秒钩子文案（≤25字，必须让人想继续看）",
  "storyboards": [
    {{"index": 1, "duration_s": 3.0, "shot_desc": "拍摄说明（≤30字）", "subtitle": "字幕（≤15字）", "voiceover": "口播文案（≤30字）"}},
    {{"index": 2, "duration_s": 4.0, "shot_desc": "...", "subtitle": "...", "voiceover": "..."}},
    {{"index": 3, "duration_s": 8.0, "shot_desc": "...", "subtitle": "...", "voiceover": "..."}},
    {{"index": 4, "duration_s": 5.0, "shot_desc": "...", "subtitle": "...", "voiceover": "..."}}
  ],
  "cta": "行动号召（≤20字，引导点击橱窗/评论区）",
  "pub_time_suggest": "建议发布时间段（如：18:00-20:00）"
}}
```

## 合规硬性要求（违反则内容无效）
❌ 绝对禁止使用：{forbidden}
❌ 不要承诺退款、不要宣传功效、不要用绝对化表达
✅ 客观描述外观、材质、使用感受，可用「感觉」「体验」「像」等非绝对词
✅ CTA 引导橱窗购买，语气自然不强迫"""

# ─────────────────────────────────────────────
# 小红书笔记 Prompt
# ─────────────────────────────────────────────
XHS_PROMPT = """你是一位小红书种草达人，专注办公桌面/工位好物分享，文风真实亲切。

## 商品信息
- 商品名称：{title}
- 售价：¥{price}
- 月销量：约 {sales_30d} 件

## 任务
为上述商品生成一篇「{type_cn}」类型的小红书图文笔记（6张图）。

## 脚本类型说明
{type_desc}

## 输出格式（严格 JSON，不要有 JSON 以外的任何文字）
```json
{{
  "cover_title": "封面大标题（≤20字，核心吸引点）",
  "cover_subtitle": "封面副标（≤10字）",
  "body_text": "正文（300-600字，含 emoji 分段，真实种草语气，末尾引导评论区）",
  "hashtags": ["#话题1", "#话题2", "#话题3", "#话题4", "#话题5", "#话题6", "#话题7", "#话题8"],
  "images": [
    {{"index": 1, "shot_desc": "封面图拍摄说明", "overlay_text": "图上叠加的文字（可空）", "purpose": "cover"}},
    {{"index": 2, "shot_desc": "...", "overlay_text": "...", "purpose": "detail"}},
    {{"index": 3, "shot_desc": "...", "overlay_text": "...", "purpose": "detail"}},
    {{"index": 4, "shot_desc": "...", "overlay_text": "...", "purpose": "detail"}},
    {{"index": 5, "shot_desc": "...", "overlay_text": "...", "purpose": "comparison"}},
    {{"index": 6, "shot_desc": "价格信息图", "overlay_text": "¥{price} 直接拍", "purpose": "cta"}}
  ],
  "cta": "引导评论互动（如：喜欢的姐妹扣1）",
  "pub_time_suggest": "建议发布时间段"
}}
```

## 合规硬性要求
❌ 不在正文/图片放外链；不导流其他平台
❌ 禁止使用：{forbidden}
✅ 末尾说"链接在评论区"或"评论区扣1"
✅ 真实分享语气，不要过度营销腔"""


# ─────────────────────────────────────────────
# LLM 客户端初始化
# ─────────────────────────────────────────────

def _make_openai_client(config: dict):
    """
    根据配置创建 OpenAI 兼容客户端
    支持 deepseek / qwen / openai
    """
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("[LLM] openai 库未安装，无法使用 LLM 生成")
        return None

    ai_cfg = config.get("ai", {})
    api_key = ai_cfg.get("api_key", "").strip()

    if not api_key or api_key.startswith("sk-xxx"):
        logger.info("[LLM] API Key 未配置，将使用模板引擎降级")
        return None

    provider = ai_cfg.get("provider", "deepseek").lower()
    base_urls = {
        "deepseek": "https://api.deepseek.com",
        "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    }

    kwargs = {"api_key": api_key}
    if provider in base_urls:
        kwargs["base_url"] = base_urls[provider]

    try:
        return OpenAI(**kwargs)
    except Exception as e:
        logger.warning(f"[LLM] 客户端初始化失败: {e}")
        return None


# ─────────────────────────────────────────────
# 主类
# ─────────────────────────────────────────────

class LLMContentGenerator:
    """
    LLM 内容生成器
    主流程：LLM生成 → JSON解析 → 结构体转换
    降级流程：任何异常 → 回退模板引擎
    """

    def __init__(self, config: dict):
        self.config = config
        ai_cfg = config.get("ai", {})
        self.model = ai_cfg.get("model", "deepseek-chat")
        self.temperature = float(ai_cfg.get("temperature", 0.75))
        self.max_tokens = int(ai_cfg.get("max_tokens", 2000))
        self.client = _make_openai_client(config)
        self._llm_ok = self.client is not None

        # 降级引擎（延迟导入，避免循环依赖）
        self._template_douyin = None
        self._template_xhs = None

        if self._llm_ok:
            logger.info(f"[LLM] ✅ 已初始化 {self.model}，主力模式")
        else:
            logger.info("[LLM] ⚠️ 降级到模板引擎（未配置 API Key）")

    def _get_template_douyin(self):
        if self._template_douyin is None:
            from content.templates import ScriptGenerator
            self._template_douyin = ScriptGenerator()
        return self._template_douyin

    def _get_template_xhs(self):
        if self._template_xhs is None:
            from content.templates import XHSGenerator
            self._template_xhs = XHSGenerator()
        return self._template_xhs

    # ──────────────────────────────────────────
    # 对外接口（与原 ScriptGenerator/XHSGenerator 保持相同返回类型）
    # ──────────────────────────────────────────

    def generate_douyin(self, product: dict, script_type: str):
        """
        生成抖音脚本 → ScriptResult
        成功：LLM 生成，template_version='llm_v1'
        失败：模板引擎降级，template_version='template_fallback'
        """
        if not self._llm_ok:
            result = self._get_template_douyin().generate(product, script_type)
            result.template_version = "template_no_key"
            return result

        try:
            type_cn, type_desc = SCRIPT_TYPE_INFO.get(
                script_type, ("通用型", "结构清晰，突出卖点，引导购买。")
            )
            prompt = DOUYIN_PROMPT.format(
                title=product.get("title", ""),
                price=product.get("price", 0),
                sales_30d=product.get("sales_30d", 0),
                commission_rate=product.get("commission_rate", 0),
                commission_amt=product.get("commission_amt", 0),
                type_cn=type_cn,
                type_desc=type_desc,
                forbidden="、".join(FORBIDDEN_WORDS[:10]),
            )

            raw_text = self._call_llm(prompt)
            data = self._extract_json(raw_text)
            result = self._build_script_result(product, script_type, data)
            result.template_version = "llm_v1"
            logger.info(
                f"[LLM] ✅ 抖音脚本生成 | 商品:{product.get('title','')[:15]} | 类型:{script_type}"
            )
            return result

        except Exception as e:
            logger.warning(
                f"[LLM] ⚠️ 抖音脚本失败，降级模板 | {type(e).__name__}: {str(e)[:80]}"
            )
            result = self._get_template_douyin().generate(product, script_type)
            result.template_version = f"template_fallback({type(e).__name__})"
            return result

    def generate_xhs(self, product: dict, note_type: str):
        """
        生成小红书图文笔记 → XHSNote
        降级策略同 generate_douyin
        """
        if not self._llm_ok:
            result = self._get_template_xhs().generate(product, note_type)
            result.template_version = "template_no_key"
            return result

        try:
            type_cn, type_desc = SCRIPT_TYPE_INFO.get(
                note_type, ("通用型", "结构清晰，突出卖点，引导互动。")
            )
            prompt = XHS_PROMPT.format(
                title=product.get("title", ""),
                price=product.get("price", 0),
                sales_30d=product.get("sales_30d", 0),
                type_cn=type_cn,
                type_desc=type_desc,
                forbidden="、".join(FORBIDDEN_WORDS[:10]),
            )

            raw_text = self._call_llm(prompt)
            data = self._extract_json(raw_text)
            result = self._build_xhs_note(product, note_type, data)
            result.template_version = "llm_v1"
            logger.info(
                f"[LLM] ✅ 小红书笔记生成 | 商品:{product.get('title','')[:15]} | 类型:{note_type}"
            )
            return result

        except Exception as e:
            logger.warning(
                f"[LLM] ⚠️ 小红书笔记失败，降级模板 | {type(e).__name__}: {str(e)[:80]}"
            )
            result = self._get_template_xhs().generate(product, note_type)
            result.template_version = f"template_fallback({type(e).__name__})"
            return result

    # ──────────────────────────────────────────
    # 原有接口兼容（让 daily_runner 可以用同名方法）
    # ──────────────────────────────────────────

    def generate(self, product: dict, script_type: str):
        """兼容 ScriptGenerator.generate() 接口，默认生成抖音"""
        return self.generate_douyin(product, script_type)

    # ──────────────────────────────────────────
    # 内部工具
    # ──────────────────────────────────────────

    def _call_llm(self, prompt: str) -> str:
        """调用 LLM，返回原始文本"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=45,
        )
        return response.choices[0].message.content

    def _extract_json(self, text: str) -> dict:
        """
        从 LLM 输出中提取 JSON
        处理常见的 markdown 代码块包裹：```json ... ```
        """
        # 去掉代码块包裹
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        text = text.strip()

        # 先尝试整体解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取第一个完整 JSON 对象
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"JSON 解析失败: {e}\n原始文本(前300字): {text[:300]}"
                )

        raise ValueError(f"无法从 LLM 响应中提取 JSON:\n{text[:300]}")

    def _build_script_result(self, product: dict, script_type: str, data: dict):
        """JSON dict → ScriptResult 数据结构"""
        from content.templates import ScriptResult, Storyboard, detect_category

        storyboards = []
        for sb in data.get("storyboards", []):
            storyboards.append(
                Storyboard(
                    index=int(sb.get("index", len(storyboards) + 1)),
                    duration_s=float(sb.get("duration_s", 4.0)),
                    shot_desc=str(sb.get("shot_desc", "")),
                    subtitle=str(sb.get("subtitle", "")),
                    voiceover=str(sb.get("voiceover", "")),
                )
            )

        # 如果 LLM 没生成分镜，给个兜底
        if not storyboards:
            storyboards = [
                Storyboard(1, 5.0, "展示商品全貌", "超值好物", "今天给大家分享一个宝藏！"),
                Storyboard(2, 5.0, "细节特写", "品质绝了", ""),
                Storyboard(3, 5.0, "使用演示", "实测效果", ""),
                Storyboard(4, 5.0, "CTA", "链接在评论", "心动的点击下方橱窗！"),
            ]

        full_subtitle = " | ".join(
            sb.subtitle for sb in storyboards if sb.subtitle
        )
        voiceover = "。".join(
            sb.voiceover for sb in storyboards if sb.voiceover
        )

        return ScriptResult(
            product_id=int(product.get("id", 0)),
            script_type=script_type,
            title=str(data.get("title", product.get("title", "")[:20])),
            cover_copy=str(data.get("cover_copy", "")),
            hook_3s=str(data.get("hook_3s", "")),
            storyboards=storyboards,
            full_subtitle=full_subtitle,
            voiceover=voiceover,
            cta=str(data.get("cta", "点击橱窗购买🛒")),
            pub_time_suggest=str(data.get("pub_time_suggest", "18:00-20:00")),
            mount_suggest="优先挂橱窗商品卡",
            compliance_notes="⚠️ AI生成内容，人工必须审核合规性后方可发布",
            product_category=detect_category(product.get("title", "")),
            generated_at=date.today().strftime("%Y-%m-%d"),
        )

    def _build_xhs_note(self, product: dict, note_type: str, data: dict):
        """JSON dict → XHSNote 数据结构"""
        from content.templates import XHSNote, XHSImage, detect_category
        import json as _json

        images = []
        for img in data.get("images", []):
            images.append(
                XHSImage(
                    index=int(img.get("index", len(images) + 1)),
                    shot_desc=str(img.get("shot_desc", "")),
                    overlay_text=str(img.get("overlay_text", "")),
                    purpose=str(img.get("purpose", "detail")),
                )
            )

        # 兜底图片规格
        if not images:
            images = [
                XHSImage(1, "商品全貌封面图", "", "cover"),
                XHSImage(2, "商品细节特写", "", "detail"),
                XHSImage(3, "使用场景", "", "detail"),
                XHSImage(4, "卖点展示", "", "detail"),
                XHSImage(5, "与其他对比", "", "comparison"),
                XHSImage(6, "价格信息图", f"¥{product.get('price',0)}", "cta"),
            ]

        hashtags = data.get("hashtags", [])
        if isinstance(hashtags, list):
            hashtags = [str(h) for h in hashtags]
        else:
            hashtags = []

        return XHSNote(
            product_id=int(product.get("id", 0)),
            note_type=note_type,
            platform="xiaohongshu",
            cover_title=str(data.get("cover_title", product.get("title", "")[:20])),
            cover_subtitle=str(data.get("cover_subtitle", "")),
            body_text=str(data.get("body_text", "")),
            hashtags=hashtags,
            img_count=len(images),
            images=images,
            cta=str(data.get("cta", "喜欢的姐妹评论区扣1💕")),
            pub_time_suggest=str(data.get("pub_time_suggest", "12:00-14:00")),
            link_placement="评论区推广链接",
            compliance_notes="⚠️ AI生成内容，人工必须审核合规性后方可发布",
            product_category=detect_category(product.get("title", "")),
            generated_at=date.today().strftime("%Y-%m-%d"),
        )


# ─────────────────────────────────────────────
# 命令行测试入口
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT))
    from utils.config import load_config

    print("=" * 60)
    print("  LLMContentGenerator 独立测试")
    print("=" * 60)

    config = load_config()
    gen = LLMContentGenerator(config)

    print(f"\nLLM 模式: {'✅ DeepSeek' if gen._llm_ok else '⚠️ 模板引擎降级'}")
    print(f"使用模型: {gen.model}")

    # 测试商品
    mock_product = {
        "id": 1,
        "title": "流沙画 创意桌面摆件 沙漏装饰品",
        "price": 29.9,
        "sales_30d": 15000,
        "commission_rate": 15.0,
        "commission_amt": 4.49,
    }

    print(f"\n[1] 生成抖音「反差型」脚本...")
    script = gen.generate_douyin(mock_product, "contrast")
    print(f"  标题: {script.title}")
    print(f"  封面大字: {script.cover_copy}")
    print(f"  3s钩子: {script.hook_3s}")
    print(f"  分镜数: {len(script.storyboards)}")
    print(f"  生成方式: {script.template_version}")

    print(f"\n[2] 生成小红书「场景型」笔记...")
    note = gen.generate_xhs(mock_product, "scene")
    print(f"  封面标题: {note.cover_title}")
    print(f"  正文字数: {len(note.body_text)}")
    print(f"  话题标签: {note.hashtags[:3]}")
    print(f"  生成方式: {note.template_version}")

    print("\n✅ 测试完成！")
