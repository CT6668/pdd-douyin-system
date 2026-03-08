"""
带货内容脚本模板系统 v2.1
支持平台：抖音（竖屏视频15s）/ 小红书（图文笔记）
支持4类脚本类型：痛点型 / 场景型 / 反差型 / 清单型
支持商品类目感知：根据商品特征自动选择最优话术

使用方法：
    from content.templates import ScriptGenerator, XHSGenerator
    gen = ScriptGenerator()
    scripts = gen.generate_all(product)       # 抖音4套脚本

    xhs = XHSGenerator()
    xhs_notes = xhs.generate_all(product)    # 小红书4套图文笔记
"""

import json
import re
from dataclasses import dataclass, asdict, field
from typing import List, Optional, Dict
from datetime import date


# ─────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────

@dataclass
class Storyboard:
    """单个分镜"""
    index: int
    duration_s: float
    shot_desc: str       # 拍摄指引
    subtitle: str        # 字幕（≤15字）
    voiceover: str = ""  # 口播（可为空）


@dataclass
class ScriptResult:
    """完整脚本输出"""
    product_id: int
    script_type: str
    title: str                      # 视频标题（≤20字）
    cover_copy: str                 # 封面大字（≤10字）
    hook_3s: str                    # 前3秒钩子
    storyboards: List[Storyboard]
    full_subtitle: str
    voiceover: str
    cta: str
    pub_time_suggest: str
    mount_suggest: str
    compliance_notes: str
    product_category: str = ""      # 商品类目标签
    template_version: str = "v2"
    generated_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["storyboards"] = [asdict(s) for s in self.storyboards]
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────
# 商品类目识别器
# ─────────────────────────────────────────────

def detect_category(title: str) -> str:
    """
    根据商品标题识别类目标签
    返回值: "liusha"（流沙/沙漏）/ "crystal"（水晶）/ "jieyaplay"（解压玩具）
            / "flower"（永生花/干花）/ "zhaocai"（招财摆件）/ "general"（通用）
    """
    t = title
    if any(k in t for k in ["流沙", "沙漏", "流沙画", "山水画", "沙画"]):
        return "liusha"
    if any(k in t for k in ["水晶", "发财树", "玛瑙", "紫水晶", "黄水晶"]):
        return "crystal"
    if any(k in t for k in ["解压", "减压", "捏捏", "骰子", "魔方", "玩具", "发泄"]):
        return "jieyaplay"
    if any(k in t for k in ["永生花", "干花", "浮游花", "满天星", "押花"]):
        return "flower"
    if any(k in t for k in ["招财猫", "招财", "旺财", "聚财"]):
        return "zhaocai"
    return "general"


# ─────────────────────────────────────────────
# 类目特化话术库
# ─────────────────────────────────────────────

CATEGORY_COPY = {
    "liusha": {
        "hook_pain":    "桌面摆了一堆没用的东西？",
        "hook_contrast":"这X块钱的沙漏，我没想到这么好看",
        "hook_scene":   "每次心烦的时候，我就翻一下它",
        "hook_list":    "3个理由！为什么沙漏是桌面神器",
        "product_intro":"沙子慢慢流动，看一眼就静下来了",
        "scene_intro":  "翻一下，看着沙子流，莫名就静了",
        "contrast_wow": "流沙的质感比图片好太多了",
        "list_point1":  "颜值：随手一拍就是大片",
        "list_point2":  "解压：看着流沙流动，心静了",
        "list_point3":  "送礼：包装好看，拿出手有面",
        "compliance":   "可说「看着让心情平静」，不说「治疗焦虑/抑郁」",
    },
    "crystal": {
        "hook_pain":    "工位好不好，藏在细节里",
        "hook_contrast":"以为是普通摆件，打开傻眼了",
        "hook_scene":   "阳光照到水晶上那一刻",
        "hook_list":    "选水晶摆件，这3点最重要",
        "product_intro":"天然水晶，光照上去颜色会变的",
        "scene_intro":  "放在桌面上，阳光一照就很治愈",
        "contrast_wow": "这质感这颜色，X块买到真划算",
        "list_point1":  "颜值：光线一照，折射好看极了",
        "list_point2":  "寓意：美好祝愿，送礼有心意",
        "list_point3":  "品质：天然石材，每个花纹独一无二",
        "compliance":   "说「寓意美好」可以，不承诺「必然带来财运」",
    },
    "jieyaplay": {
        "hook_pain":    "摸鱼5分钟，脑子转不动了",
        "hook_contrast":"X块买的玩具，没想到同事都抢着玩",
        "hook_scene":   "开会前捏一捏，状态立刻来了",
        "hook_list":    "为什么办公室都在摆这个？",
        "product_intro":"用手操作一下，挺解压的",
        "scene_intro":  "摸鱼必备，操作起来停不下来",
        "contrast_wow": "手感比预期好，玩起来很顺手",
        "list_point1":  "好玩：手上有事干，脑子反而清醒了",
        "list_point2":  "解压：物理操作，比刷手机更放松",
        "list_point3":  "颜值：摆在桌上也好看，不显幼稚",
        "compliance":   "说「让人放松一下」可以，不说「包治职业倦怠」",
    },
    "flower": {
        "hook_pain":    "桌面太素了，像极了摸鱼的心情",
        "hook_contrast":"X块能买到这么好看的花，我要囤货了",
        "hook_scene":   "桌上放束花，整个人的状态都不一样",
        "hook_list":    "送礼选永生花，3个理由",
        "product_intro":"永生花保色时间比普通干花长很多",
        "scene_intro":  "放在桌面上，随手一拍都好看",
        "contrast_wow": "颜色比图片更鲜，装起来很有格调",
        "list_point1":  "颜值：无需打理，天天都好看",
        "list_point2":  "场景：桌面/书桌/梳妆台，哪都能放",
        "list_point3":  "送礼：包装精美，比鲜花有纪念意义",
        "compliance":   "说「保存时间较长」可以，不说「永不凋谢/永久保鲜」",
    },
    "zhaocai": {
        "hook_pain":    "工位缺点什么？可能是这个",
        "hook_contrast":"以为是普通招财猫，摆上去惊了",
        "hook_scene":   "工位有这个，感觉心情都好一点",
        "hook_list":    "招财猫摆件怎么选？记住这3点",
        "product_intro":"做工很细，不是那种廉价感",
        "scene_intro":  "摆在桌上，寓意美好，看着心情好",
        "contrast_wow": "X块买到这个工艺，没踩雷",
        "list_point1":  "工艺：细节刻画细腻，摆出来有格调",
        "list_point2":  "寓意：美好祝愿，送给自己或朋友都合适",
        "list_point3":  "价格：X块以内，买来放着不心疼",
        "compliance":   "「寓意美好」合规，不承诺「保证招财/必定发财」",
    },
    "general": {
        "hook_pain":    "你的桌面，是不是缺点什么？",
        "hook_contrast":"X块买的桌面摆件，比预期好",
        "hook_scene":   "桌面加一个小摆件，幸福感来了",
        "hook_list":    "为什么我推荐这个桌面摆件",
        "product_intro":"摆上去就有感觉了",
        "scene_intro":  "小小一个，提升了整个桌面的氛围",
        "contrast_wow": "这个价格，质感超出预期",
        "list_point1":  "颜值：好看，随手拍都出片",
        "list_point2":  "氛围：桌面有了它，感觉不一样了",
        "list_point3":  "价格：就这个价，不用纠结",
        "compliance":   "客观描述外观和功能，不夸大效果",
    },
}

# 发布时间建议
PUB_SLOTS = {
    "morning": "07:30-08:30（早间通勤，打工族刷手机高峰）",
    "noon":    "12:00-13:30（午休，打工人放松高峰）",
    "evening": "17:30-19:00（下班途中，情绪轻松流量大）",
    "night":   "20:00-22:30（夜间黄金段，全天最高流量）",
}

# 合规基础说明（所有类型共用）
COMPLIANCE_BASE = (
    "⚠️ 人工必须确认：①不出现功效/治疗/保证/包治等违禁词；"
    "②不使用最好/第一/绝对等绝对化用语；"
    "③所有描述需真实客观；④价格须与商品实际价格一致；"
    "⑤发布前需人工最终审核"
)


# ─────────────────────────────────────────────
# 脚本生成器（主类）
# ─────────────────────────────────────────────

class ScriptGenerator:
    """商品类目感知型脚本生成器 v2.0"""

    def generate(self, product: dict, script_type: str) -> ScriptResult:
        dispatch = {
            "pain_point": self._gen_pain_point,
            "scene":      self._gen_scene,
            "contrast":   self._gen_contrast,
            "list":       self._gen_list,
        }
        fn = dispatch.get(script_type)
        if fn is None:
            raise ValueError(f"不支持的脚本类型: {script_type}")

        # 注入类目标签
        product = dict(product)
        product["_category"] = detect_category(product.get("title", ""))

        result = fn(product)
        result.generated_at = date.today().strftime("%Y-%m-%d")
        result.product_category = product["_category"]
        return result

    def generate_all(self, product: dict) -> List[ScriptResult]:
        """为一个商品生成全部4类脚本"""
        results = []
        for stype in ["pain_point", "scene", "contrast", "list"]:
            try:
                results.append(self.generate(product, stype))
            except Exception as e:
                print(f"  生成 {stype} 失败: {e}")
        return results

    # ──────────────────────────────────────────
    # 内部工具方法
    # ──────────────────────────────────────────

    def _short_name(self, title: str, maxlen: int = 10) -> str:
        """从商品标题提取简短名称"""
        # 优先提取核心物品词（名词）
        for kw in ["流沙画", "沙漏", "水晶发财树", "发财树", "解压骰子", "解压魔方",
                   "永生花", "干花", "浮游花", "招财猫", "摆件"]:
            if kw in title:
                return kw
        # 取前N个字
        return title[:maxlen]

    def _price_str(self, price: float) -> str:
        """价格格式化"""
        if price == int(price):
            return str(int(price))
        return f"{price:.1f}"

    def _get_copy(self, cat: str, key: str) -> str:
        return CATEGORY_COPY.get(cat, CATEGORY_COPY["general"])[key]

    def _compliance(self, cat: str) -> str:
        cat_note = CATEGORY_COPY.get(cat, CATEGORY_COPY["general"]).get("compliance", "")
        return COMPLIANCE_BASE + f"；类目特别注意：{cat_note}"

    # ──────────────────────────────────────────
    # 脚本类型1：痛点型
    # 结构：痛点展示 → 发现商品 → 效果展示 → CTA
    # ──────────────────────────────────────────
    def _gen_pain_point(self, p: dict) -> ScriptResult:
        cat = p["_category"]
        title = p.get("title", "")
        price = p.get("price", 0)
        pstr = self._price_str(price)
        sname = self._short_name(title)

        hook = self._get_copy(cat, "hook_pain")
        product_intro = self._get_copy(cat, "product_intro")

        sb = [
            Storyboard(1, 3.0,
                shot_desc="特写：平淡或凌乱的桌面，无生气感",
                subtitle=hook,
                voiceover=hook),
            Storyboard(2, 3.0,
                shot_desc=f"手拿{sname}缓缓入画，45°俯拍",
                subtitle=f"直到我发现了这个{sname}",
                voiceover=f"直到朋友给我推荐了这个{sname}"),
            Storyboard(3, 5.0,
                shot_desc=f"慢动作展示{sname}核心视觉亮点，特写+全景",
                subtitle=f"{product_intro}",
                voiceover=f"{product_intro}，才{pstr}块"),
            Storyboard(4, 4.0,
                shot_desc="商品摆在桌面的整体效果，对比感",
                subtitle=f"才{pstr}元，桌面幸福感拉满",
                voiceover=f"就{pstr}块，给自己的工位加点氛围感，值了"),
        ]
        subtitle = " | ".join(s.subtitle for s in sb)
        vo = "。".join(s.voiceover for s in sb if s.voiceover)

        return ScriptResult(
            product_id=p.get("id", 0),
            script_type="pain_point",
            title=f"桌面一直提不起劲？试试这个{sname}",
            cover_copy=f"桌面焕然一新✨",
            hook_3s=hook,
            storyboards=sb,
            full_subtitle=subtitle,
            voiceover=vo + f"！橱窗{pstr}元，直接下单！",
            cta=f"点左下角橱窗，{pstr}元包邮 👇",
            pub_time_suggest=PUB_SLOTS["noon"] + " / " + PUB_SLOTS["night"],
            mount_suggest="优先橱窗商品卡；若有多多进宝链接放评论区置顶",
            compliance_notes=self._compliance(cat),
        )

    # ──────────────────────────────────────────
    # 脚本类型2：场景型
    # 结构：场景导入 → 商品融入 → 氛围烘托 → CTA
    # ──────────────────────────────────────────
    def _gen_scene(self, p: dict) -> ScriptResult:
        cat = p["_category"]
        title = p.get("title", "")
        price = p.get("price", 0)
        pstr = self._price_str(price)
        sname = self._short_name(title)

        hook = self._get_copy(cat, "hook_scene")
        scene_intro = self._get_copy(cat, "scene_intro")

        sb = [
            Storyboard(1, 3.0,
                shot_desc="工位/书桌自然光场景，暖色调，有咖啡/书本道具",
                subtitle="每天在这张桌子前坐8小时",
                voiceover="每天都要在这张桌子前坐8个小时"),
            Storyboard(2, 3.0,
                shot_desc=f"缓缓将{sname}放上桌面，慢动作，仪式感",
                subtitle=f"加了这个{sname}之后不一样了",
                voiceover=f"自从放上这个{sname}，感觉都不一样了"),
            Storyboard(3, 5.0,
                shot_desc="整体桌面环境，商品在画面中，明亮温馨",
                subtitle=scene_intro,
                voiceover=scene_intro),
            Storyboard(4, 4.0,
                shot_desc=f"{sname}特写，强调质感细节",
                subtitle=f"才{pstr}元，打工人值得拥有",
                voiceover=f"就{pstr}块，给自己一个小惊喜，不过分吧"),
        ]
        subtitle = " | ".join(s.subtitle for s in sb)
        vo = "。".join(s.voiceover for s in sb if s.voiceover)

        return ScriptResult(
            product_id=p.get("id", 0),
            script_type="scene",
            title=f"打工人桌面必备！这个{sname}太治愈了",
            cover_copy=f"工位氛围感来了💆",
            hook_3s="每天在这张桌子前坐8小时",
            storyboards=sb,
            full_subtitle=subtitle,
            voiceover=vo + f"！橱窗{pstr}元，送自己也送朋友。",
            cta=f"戳橱窗，{pstr}元拿下 👇",
            pub_time_suggest=PUB_SLOTS["morning"] + " / " + PUB_SLOTS["evening"],
            mount_suggest="优先橱窗挂载，场景型适合同时发布多图（桌面布置前后对比）",
            compliance_notes=self._compliance(cat),
        )

    # ──────────────────────────────────────────
    # 脚本类型3：反差型
    # 结构：低预期铺垫 → 意外惊喜 → 全面展示 → CTA
    # ──────────────────────────────────────────
    def _gen_contrast(self, p: dict) -> ScriptResult:
        cat = p["_category"]
        title = p.get("title", "")
        price = p.get("price", 0)
        pstr = self._price_str(price)
        sname = self._short_name(title)

        hook_template = self._get_copy(cat, "hook_contrast")
        hook = hook_template.replace("X块", f"{pstr}块")
        contrast_wow = self._get_copy(cat, "contrast_wow").replace("X块", pstr)

        sb = [
            Storyboard(1, 3.0,
                shot_desc="手拿快递盒/商品，表情略带疑惑",
                subtitle=f"就这？{pstr}块的{sname}能有多好看",
                voiceover=f"说实话，{pstr}块我以为会很普通"),
            Storyboard(2, 4.0,
                shot_desc=f"慢动作开箱/摆放{sname}，捕捉「惊喜」瞬间",
                subtitle="打开的瞬间：哇！",
                voiceover="结果打开包装直接愣住了"),
            Storyboard(3, 5.0,
                shot_desc="多角度展示商品，强调质感/颜色/细节",
                subtitle=contrast_wow,
                voiceover=contrast_wow),
            Storyboard(4, 3.0,
                shot_desc="商品放在桌面的最终效果，竖排展示",
                subtitle=f"{pstr}元封神！",
                voiceover=f"{pstr}块买到这个，说出去真没人信"),
        ]
        subtitle = " | ".join(s.subtitle for s in sb)
        vo = "。".join(s.voiceover for s in sb if s.voiceover)

        return ScriptResult(
            product_id=p.get("id", 0),
            script_type="contrast",
            title=f"{pstr}元买到这个？我不敢相信！{sname}开箱",
            cover_copy=f"{pstr}块买到这个👆",
            hook_3s=f"就这？{pstr}块的{sname}能有多好看",
            storyboards=sb,
            full_subtitle=subtitle,
            voiceover=vo + "！链接在橱窗，数量有限！",
            cta=f"橱窗直接拍，{pstr}元 👇",
            pub_time_suggest=PUB_SLOTS["night"],
            mount_suggest="橱窗挂载；评论区置顶「实物对比」买家秀图，增加信任度",
            compliance_notes=self._compliance(cat) + "；反差型特别注意：不用「假」「骗」等误导词，不承诺「比图片好X倍」（夸大）",
        )

    # ──────────────────────────────────────────
    # 脚本类型4：清单型
    # 结构：数字钩子 → 卖点1 → 卖点2 → 卖点3+价格 → CTA
    # ──────────────────────────────────────────
    def _gen_list(self, p: dict) -> ScriptResult:
        cat = p["_category"]
        title = p.get("title", "")
        price = p.get("price", 0)
        pstr = self._price_str(price)
        sname = self._short_name(title)

        hook = self._get_copy(cat, "hook_list")
        p1 = self._get_copy(cat, "list_point1")
        p2 = self._get_copy(cat, "list_point2")
        p3 = self._get_copy(cat, "list_point3").replace("X块", pstr)

        sb = [
            Storyboard(1, 2.0,
                shot_desc="大字幕出现「3个理由」，手比3的手势",
                subtitle="3个理由让你爱上它",
                voiceover=f"给你3个选{sname}的理由"),
            Storyboard(2, 4.0,
                shot_desc=f"展示{sname}最强视觉卖点，近景特写",
                subtitle=f"① {p1}",
                voiceover=f"第一，{p1}"),
            Storyboard(3, 4.0,
                shot_desc="展示第二卖点（功能/情感/场景）",
                subtitle=f"② {p2}",
                voiceover=f"第二，{p2}"),
            Storyboard(4, 5.0,
                shot_desc=f"展示第三卖点+价格大字幕",
                subtitle=f"③ {p3}  才{pstr}元！",
                voiceover=f"第三，{p3}。就{pstr}块，值不值自己判断"),
        ]
        subtitle = " | ".join(s.subtitle for s in sb)
        vo = "。".join(s.voiceover for s in sb if s.voiceover)

        return ScriptResult(
            product_id=p.get("id", 0),
            script_type="list",
            title=f"3个理由！为什么我强烈推荐{sname}",
            cover_copy=f"3个理由选它📋",
            hook_3s="3个理由让你爱上它",
            storyboards=sb,
            full_subtitle=subtitle,
            voiceover=vo + f"。橱窗{pstr}元，理由够了就下单。",
            cta=f"理由够了吗？橱窗{pstr}元 👇",
            pub_time_suggest=PUB_SLOTS["noon"] + " / " + PUB_SLOTS["night"],
            mount_suggest="橱窗挂载；清单型适合同时挂同类多款商品做对比",
            compliance_notes=self._compliance(cat),
        )

    # ──────────────────────────────────────────
    # 输出工具
    # ──────────────────────────────────────────
    @staticmethod
    def format_script(script: ScriptResult) -> str:
        """返回人类可读的脚本文本"""
        type_names = {
            "pain_point": "痛点型",
            "scene": "场景型",
            "contrast": "反差型",
            "list": "清单型",
        }
        total_s = sum(s.duration_s for s in script.storyboards)
        lines = [
            f"",
            f"{'='*62}",
            f"【{type_names.get(script.script_type, script.script_type)}脚本】  版本:{script.template_version}  生成:{script.generated_at}",
            f"{'='*62}",
            f"📌 标题    ：{script.title}",
            f"🖼️  封面文案 ：{script.cover_copy}",
            f"⚡ 前3秒钩子：{script.hook_3s}",
            f"",
            f"📹 分镜（总{total_s:.0f}秒）：",
        ]
        for sb in script.storyboards:
            lines.append(f"  [{sb.index}] {sb.duration_s}s")
            lines.append(f"       🎥 画面：{sb.shot_desc}")
            lines.append(f"       💬 字幕：{sb.subtitle}")
            if sb.voiceover:
                lines.append(f"       🎙️  口播：{sb.voiceover}")
        lines += [
            f"",
            f"📝 完整字幕：{script.full_subtitle}",
            f"🎙️  完整口播：{script.voiceover}",
            f"",
            f"📣 CTA      ：{script.cta}",
            f"⏰ 发布时间 ：{script.pub_time_suggest}",
            f"🔗 挂载建议 ：{script.mount_suggest}",
            f"⚠️  合规备注 ：{script.compliance_notes[:100]}...",
            f"{'='*62}",
        ]
        return "\n".join(lines)

    @staticmethod
    def print_script(script: ScriptResult):
        print(ScriptGenerator.format_script(script))


# ─────────────────────────────────────────────
# 小红书图文笔记数据结构
# ─────────────────────────────────────────────

@dataclass
class XHSImage:
    """小红书单张图片规格"""
    index: int           # 第几张（1起）
    shot_desc: str       # 拍摄/制作说明
    overlay_text: str    # 图上叠加文字（可为空）
    purpose: str         # 图片作用：cover/detail/comparison/cta


@dataclass
class XHSNote:
    """小红书图文笔记完整输出"""
    product_id: int
    note_type: str           # pain_point / scene / contrast / list
    platform: str = "xiaohongshu"
    cover_title: str = ""    # 封面大标题（≤20字，是吸引点击的核心）
    cover_subtitle: str = "" # 封面副标题（≤10字）
    body_text: str = ""      # 正文（≤1000字，含emoji分段）
    hashtags: List[str] = None   # 话题标签列表（5-10个）
    img_count: int = 6       # 建议图片数量
    images: List[XHSImage] = None  # 每张图规格说明
    cta: str = ""            # 行动号召（末尾）
    pub_time_suggest: str = ""
    link_placement: str = ""  # 链接放置建议（内挂/评论区/个人主页）
    compliance_notes: str = ""
    product_category: str = ""
    template_version: str = "v2.1"
    generated_at: str = ""

    def __post_init__(self):
        if self.hashtags is None:
            self.hashtags = []
        if self.images is None:
            self.images = []

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────
# 小红书专用话术库
# ─────────────────────────────────────────────

XHS_CATEGORY_COPY = {
    "liusha": {
        "cover_pain":    "桌面凌乱没灵魂？试试这个",
        "cover_scene":   "打工人桌面 | 这个沙漏治愈了我",
        "cover_contrast":"花了X元 | 完全没想到这么好看",
        "cover_list":    "选沙漏摆件 | 记住这3点就够了",
        "body_intro":    "最近桌面换了一个流沙画，真的被种草了🌿",
        "body_effect":   "翻过来看着沙子慢慢流，莫名就静下来了",
        "body_scene":    "阳光照过来的时候，颜色特别好看，随手一拍就出片",
        "contrast_wow":  "流沙的质感比图片好太多了，颜色也更透亮",
        "hashtags_base": ["#桌面好物", "#沙漏摆件", "#工位布置", "#办公室好物",
                          "#桌面美化", "#流沙画", "#打工人必备", "#居家好物分享"],
    },
    "crystal": {
        "cover_pain":    "工位缺点什么？可能是这个",
        "cover_scene":   "水晶发财树 | 桌面氛围感翻倍",
        "cover_contrast":"X元买的水晶 | 比预期好太多了",
        "cover_list":    "送礼选这个 | 3点教你选水晶摆件",
        "body_intro":    "最近在桌面加了一棵水晶发财树，超级喜欢💎",
        "body_effect":   "阳光照上去，水晶折射出来的颜色好治愈",
        "body_scene":    "放在工位上每天都能看到，感觉心情也好一点",
        "contrast_wow":  "这质感这颜色，X块买到真划算，比图片好看很多",
        "hashtags_base": ["#水晶摆件", "#发财树", "#桌面好物", "#工位布置",
                          "#办公室装饰", "#水晶", "#居家摆件", "#送礼好物"],
    },
    "jieyaplay": {
        "cover_pain":    "打工人摸鱼神器 | 办公桌必备",
        "cover_scene":   "开会前捏一捏 | 状态立刻来了",
        "cover_contrast":"X元买的解压玩具 | 同事都在抢",
        "cover_list":    "桌面解压好物 | 3个选品理由",
        "body_intro":    "最近桌面多了个解压骰子，上班摸鱼必备🎲",
        "body_effect":   "手上有事情做，脑子反而更清醒了",
        "body_scene":    "放在桌面上看着就很解压，朋友来了都要摸一下",
        "contrast_wow":  "手感比预期好太多，玩起来很顺手，没想到这个价格能做到",
        "hashtags_base": ["#解压玩具", "#办公桌好物", "#工位神器", "#打工人",
                          "#桌面好物", "#解压神器", "#办公室必备", "#上班族必备"],
    },
    "flower": {
        "cover_pain":    "桌面太素了？永生花治好了我",
        "cover_scene":   "桌面一束花 | 整个人都精神了",
        "cover_contrast":"X元买的永生花 | 比鲜花还好看",
        "cover_list":    "送女生礼物 | 为什么选永生花",
        "body_intro":    "最近在桌面加了一束永生花，氛围感直接拉满🌸",
        "body_effect":   "不用打理，保存时间比普通干花长很多",
        "body_scene":    "自然光下拍真的太好看了，每次都忍不住多拍几张",
        "contrast_wow":  "颜色比图片更鲜艳，装起来很有格调，开箱瞬间惊了",
        "hashtags_base": ["#永生花", "#干花摆件", "#桌面好物", "#桌面布置",
                          "#送礼", "#居家好物", "#花艺", "#工位装饰"],
    },
    "zhaocai": {
        "cover_pain":    "工位摆什么好？试试招财猫",
        "cover_scene":   "桌面加了招财猫 | 心情真的好多了",
        "cover_contrast":"X元的招财猫 | 做工比我想的好",
        "cover_list":    "招财摆件怎么选 | 3个避坑点",
        "body_intro":    "最近给工位加了一只招财猫，寓意美好，摆着心情好🐱",
        "body_effect":   "做工细节挺好的，不是那种廉价感",
        "body_scene":    "放在桌面很合适，同事说看起来很有格调",
        "contrast_wow":  "X块买到这个工艺，细节做得很好，完全没踩雷",
        "hashtags_base": ["#招财猫", "#桌面摆件", "#工位布置", "#办公室好物",
                          "#居家装饰", "#送礼好物", "#桌面好物", "#小摆件"],
    },
    "general": {
        "cover_pain":    "桌面缺点氛围？试试这个",
        "cover_scene":   "工位改造 | 加了这个幸福感拉满",
        "cover_contrast":"X元买的桌面摆件 | 超出预期",
        "cover_list":    "桌面好物推荐 | 这个值得买",
        "body_intro":    "最近给桌面加了个新摆件，种草给大家✨",
        "body_effect":   "摆上去感觉桌面立刻不一样了",
        "body_scene":    "日常工作间隙看一眼，心情好一些",
        "contrast_wow":  "这个价格，质感超出预期，比我想的要好很多",
        "hashtags_base": ["#桌面好物", "#工位布置", "#桌面摆件", "#居家好物",
                          "#办公室装饰", "#桌面美化", "#好物分享", "#打工人"],
    },
}

# 小红书合规说明
XHS_COMPLIANCE = (
    "⚠️ 小红书专项合规：①不导流微信/其他平台；"
    "②不出现外链（只能用内挂商品卡/评论区链接）；"
    "③不用「最好/第一/绝对」等绝对化用语；"
    "④不承诺功效（治疗/保证）；"
    "⑤内挂商品需是小红书联盟商品；"
    "⑥发布前需人工审核"
)


# ─────────────────────────────────────────────
# 小红书图文笔记生成器
# ─────────────────────────────────────────────

class XHSGenerator:
    """小红书图文笔记生成器 v2.1"""

    # 发布时间（小红书与抖音略有差异）
    XHS_PUB_SLOTS = {
        "morning": "07:00-09:00（早起刷小红书高峰）",
        "noon":    "11:30-13:00（午休，小红书活跃度最高时段）",
        "evening": "18:00-20:00（下班刷手机）",
        "night":   "21:00-23:00（睡前刷小红书，购买决策时段）",
    }

    def generate(self, product: dict, note_type: str) -> XHSNote:
        dispatch = {
            "pain_point": self._gen_pain_point,
            "scene":      self._gen_scene,
            "contrast":   self._gen_contrast,
            "list":       self._gen_list,
        }
        fn = dispatch.get(note_type)
        if fn is None:
            raise ValueError(f"不支持的笔记类型: {note_type}")
        product = dict(product)
        product["_category"] = detect_category(product.get("title", ""))
        result = fn(product)
        result.generated_at = date.today().strftime("%Y-%m-%d")
        result.product_category = product["_category"]
        return result

    def generate_all(self, product: dict) -> List[XHSNote]:
        results = []
        for ntype in ["pain_point", "scene", "contrast", "list"]:
            try:
                results.append(self.generate(product, ntype))
            except Exception as e:
                print(f"  XHS生成 {ntype} 失败: {e}")
        return results

    # ── 工具 ──
    def _short_name(self, title: str, maxlen: int = 8) -> str:
        for kw in ["流沙画", "沙漏", "水晶发财树", "发财树", "解压骰子",
                   "永生花", "干花", "招财猫", "摆件"]:
            if kw in title:
                return kw
        return title[:maxlen]

    def _price_str(self, price: float) -> str:
        return str(int(price)) if price == int(price) else f"{price:.1f}"

    def _get_copy(self, cat: str, key: str) -> str:
        return XHS_CATEGORY_COPY.get(cat, XHS_CATEGORY_COPY["general"])[key]

    def _base_tags(self, cat: str) -> List[str]:
        return XHS_CATEGORY_COPY.get(cat, XHS_CATEGORY_COPY["general"])["hashtags_base"]

    def _compliance(self) -> str:
        return XHS_COMPLIANCE

    # ── 笔记类型1：痛点型 ──
    def _gen_pain_point(self, p: dict) -> XHSNote:
        cat = p["_category"]
        title = p.get("title", "")
        price = p.get("price", 0)
        pstr = self._price_str(price)
        sname = self._short_name(title)
        cover = self._get_copy(cat, "cover_pain")
        intro = self._get_copy(cat, "body_intro")
        effect = self._get_copy(cat, "body_effect")
        scene = self._get_copy(cat, "body_scene")

        body = f"""你的桌面是不是也缺点什么？

{intro}

之前桌面真的太素了，每天坐在那里提不起劲来，摸鱼都没状态😅

后来试了这个{sname}，才¥{pstr}，没想到质感挺好的：

✅ {effect}
✅ {scene}
✅ 价格亲民，就{pstr}块，买来放着不心疼

现在桌面好看多了，工作间隙看一眼，心情都好一点～

感兴趣的可以点击左下角链接，或者评论区扣「1」我发给你👇

⚠️ 仅代表个人体验，效果因人而异"""

        images = [
            XHSImage(1, "封面：桌面整体美观效果图，暖色自然光，构图干净", cover, "cover"),
            XHSImage(2, "前后对比：普通桌面 vs 放上摆件后，左右分屏", f"放上它之前 vs 之后", "comparison"),
            XHSImage(3, f"商品近景特写：{sname}正面，强调质感/颜色", "", "detail"),
            XHSImage(4, f"商品细节特写：局部工艺/材质展示", "", "detail"),
            XHSImage(5, "桌面整体效果，有层次感，体现氛围", f"¥{pstr} 幸福感拉满", "detail"),
            XHSImage(6, f"价格标注图：大字显示¥{pstr}，背景是商品", f"¥{pstr} 点链接直接买", "cta"),
        ]

        tags = self._base_tags(cat) + ["#桌面改造", "#工位改造vlog"]

        return XHSNote(
            product_id=p.get("id", 0),
            note_type="pain_point",
            cover_title=cover,
            cover_subtitle=f"¥{pstr} 桌面变了样",
            body_text=body,
            hashtags=tags[:10],
            img_count=6,
            images=images,
            cta=f"👇左下角链接 ¥{pstr}直接拍 或 评论区扣「1」",
            pub_time_suggest=self.XHS_PUB_SLOTS["noon"] + " / " + self.XHS_PUB_SLOTS["night"],
            link_placement="内挂商品卡（优先）；无内挂则评论区置顶链接+个人主页链接",
            compliance_notes=self._compliance(),
        )

    # ── 笔记类型2：场景型 ──
    def _gen_scene(self, p: dict) -> XHSNote:
        cat = p["_category"]
        title = p.get("title", "")
        price = p.get("price", 0)
        pstr = self._price_str(price)
        sname = self._short_name(title)
        cover = self._get_copy(cat, "cover_scene")
        intro = self._get_copy(cat, "body_intro")
        effect = self._get_copy(cat, "body_effect")
        scene = self._get_copy(cat, "body_scene")

        body = f"""每天在这张桌子前坐8小时，工位好不好，真的影响心情～

{intro}

加了这个{sname}之后，感觉整个桌面的氛围感都来了：

🌿 早上开电脑，看一眼，今天也要加油鸭
☕ 喝咖啡摸鱼的时候，随手一拍就是好看的照片
🌙 下班前整理桌面，感觉这一天有仪式感了

{scene}

¥{pstr}的价格，不贵，但幸福感是真实的。

打工人，工位值得被对待好一点 🍀

#种草 链接在评论区第一条～"""

        images = [
            XHSImage(1, "封面：桌面整体场景，暖光，有咖啡/书/绿植等道具", cover, "cover"),
            XHSImage(2, f"将{sname}轻轻放上桌面的过程图（俯拍仪式感）", "轻轻放上去", "detail"),
            XHSImage(3, "桌面全景：商品在画面中，构图有层次感", "工位氛围拉满了", "detail"),
            XHSImage(4, f"{sname}特写，强调质感，自然光打侧面", "", "detail"),
            XHSImage(5, "桌面局部：商品+周边道具，像生活方式大片", "", "detail"),
            XHSImage(6, f"价格标注：¥{pstr}大字，配商品图，简洁", f"¥{pstr} 打工人值得", "cta"),
        ]

        tags = self._base_tags(cat) + ["#生活方式", "#工位美化vlog"]

        return XHSNote(
            product_id=p.get("id", 0),
            note_type="scene",
            cover_title=cover,
            cover_subtitle="工位幸福感+1",
            body_text=body,
            hashtags=tags[:10],
            img_count=6,
            images=images,
            cta=f"评论区第一条有链接，¥{pstr}送自己也送朋友",
            pub_time_suggest=self.XHS_PUB_SLOTS["morning"] + " / " + self.XHS_PUB_SLOTS["evening"],
            link_placement="内挂商品卡（优先）；评论区置顶链接",
            compliance_notes=self._compliance(),
        )

    # ── 笔记类型3：反差型 ──
    def _gen_contrast(self, p: dict) -> XHSNote:
        cat = p["_category"]
        title = p.get("title", "")
        price = p.get("price", 0)
        pstr = self._price_str(price)
        sname = self._short_name(title)
        cover_tmpl = self._get_copy(cat, "cover_contrast")
        cover = cover_tmpl.replace("X元", f"{pstr}元")
        wow = self._get_copy(cat, "contrast_wow").replace("X块", pstr)

        body = f"""说实话，刚下单的时候没抱多大期望

¥{pstr}的{sname}，心里预期就是"将就用"

结果收到的时候有点愣——

{wow} 😮

开箱小记：

📦 包装：包装挺用心的，没有磕碰
✨ 外观：{wow}
📍 实用：放在桌面完全OK，不占地方
💰 价格：就¥{pstr}，同价位里不错了

不算夸大，就是单纯没想到这个价格能做到这样

感兴趣的小伙伴评论区扣「开箱」，我把链接发给你～

ps：仅代表个人收货体验，大家按自己需要决定哦"""

        images = [
            XHSImage(1, f"封面：{sname}摆在桌面最美角度，配大字标题", cover, "cover"),
            XHSImage(2, "快递盒/包装的图，体现真实开箱感", "期待值不高...", "detail"),
            XHSImage(3, f"开箱瞬间：{sname}从包装中取出，捕捉惊喜感", "等等这也太好看了", "comparison"),
            XHSImage(4, f"{sname}多角度展示，突出意外的高颜值", wow[:15], "detail"),
            XHSImage(5, "放在桌面的整体效果，前后对比强调质感超预期", "比预期好很多", "comparison"),
            XHSImage(6, f"价格大字：¥{pstr}，配最好看的商品图", f"¥{pstr} 值了！", "cta"),
        ]

        tags = self._base_tags(cat) + ["#开箱测评", "#购物分享"]

        return XHSNote(
            product_id=p.get("id", 0),
            note_type="contrast",
            cover_title=cover,
            cover_subtitle="没想到",
            body_text=body,
            hashtags=tags[:10],
            img_count=6,
            images=images,
            cta=f"评论区扣「开箱」，¥{pstr}链接发你",
            pub_time_suggest=self.XHS_PUB_SLOTS["night"],
            link_placement="内挂商品卡（优先）；评论区置顶+「扣字发链接」互动提高权重",
            compliance_notes=self._compliance(),
        )

    # ── 笔记类型4：清单型 ──
    def _gen_list(self, p: dict) -> XHSNote:
        cat = p["_category"]
        title = p.get("title", "")
        price = p.get("price", 0)
        pstr = self._price_str(price)
        sname = self._short_name(title)
        cover = self._get_copy(cat, "cover_list")
        p1 = XHS_CATEGORY_COPY.get(cat, XHS_CATEGORY_COPY["general"])["hashtags_base"][0].replace("#", "")
        effect = self._get_copy(cat, "body_effect")
        scene = self._get_copy(cat, "body_scene")

        body = f"""桌面摆件怎么选？分享我的3个选品思路 📋

最近入手了一个{sname}，来给大家客观测评一下：

—

✅ 第一看：颜值
{scene}
桌面摆着好不好看，直接影响每天的心情

—

✅ 第二看：实用性
{effect}
不是光摆着好看，要真的有一点用

—

✅ 第三看：价格
¥{pstr}，在这个价位段里，性价比不错
下单门槛低，不需要纠结太久

—

综合下来，{sname}这款个人觉得值得入手的，特别适合：
• 🏢 工位布置
• 🏠 居家桌面
• 🎁 送朋友礼物

链接放在评论区第一条，感兴趣可以去看看～"""

        images = [
            XHSImage(1, f"封面：{sname}最佳角度，配「3个理由」大字标题", cover, "cover"),
            XHSImage(2, "桌面整体场景图，商品在其中，展示颜值效果", "① 颜值在线", "detail"),
            XHSImage(3, f"{sname}使用/功能展示图，体现实用性", "② 真的实用", "detail"),
            XHSImage(4, f"价格对比图或价签特写，突出¥{pstr}的超值感", f"③ 才¥{pstr}", "detail"),
            XHSImage(5, "场景图：商品+办公/居家道具，体现适用场景多样", "多场景通用", "detail"),
            XHSImage(6, f"「推荐理由」总结图：3点清单 + ¥{pstr}价格 + 购买指引", "评论区链接👇", "cta"),
        ]

        tags = self._base_tags(cat) + ["#好物推荐", "#种草清单"]

        return XHSNote(
            product_id=p.get("id", 0),
            note_type="list",
            cover_title=cover,
            cover_subtitle=f"¥{pstr} 值得买",
            body_text=body,
            hashtags=tags[:10],
            img_count=6,
            images=images,
            cta=f"评论区第一条链接，¥{pstr}直接拍",
            pub_time_suggest=self.XHS_PUB_SLOTS["noon"] + " / " + self.XHS_PUB_SLOTS["night"],
            link_placement="内挂商品卡（优先）；评论区置顶链接",
            compliance_notes=self._compliance(),
        )

    @staticmethod
    def format_note(note: XHSNote) -> str:
        type_names = {"pain_point": "痛点型", "scene": "场景型",
                      "contrast": "反差型", "list": "清单型"}
        lines = [
            f"",
            f"{'='*62}",
            f"【小红书·{type_names.get(note.note_type, note.note_type)}图文笔记】  v{note.template_version}  {note.generated_at}",
            f"{'='*62}",
            f"🖼️  封面标题：{note.cover_title}",
            f"🖼️  封面副标：{note.cover_subtitle}",
            f"",
            f"📝 正文（{len(note.body_text)}字）：",
            f"{'─'*40}",
            note.body_text,
            f"{'─'*40}",
            f"",
            f"🏷️  话题标签：{'  '.join(note.hashtags)}",
            f"",
            f"📸 图片规格（共{note.img_count}张）：",
        ]
        for img in note.images:
            lines.append(f"  [{img.index}] {img.purpose.upper()} | {img.shot_desc}")
            if img.overlay_text:
                lines.append(f"       叠字：「{img.overlay_text}」")
        lines += [
            f"",
            f"📣 CTA        ：{note.cta}",
            f"🔗 链接放置   ：{note.link_placement}",
            f"⏰ 发布时间   ：{note.pub_time_suggest}",
            f"⚠️  合规备注   ：{note.compliance_notes[:80]}...",
            f"{'='*62}",
        ]
        return "\n".join(lines)

    @staticmethod
    def print_note(note: XHSNote):
        print(XHSGenerator.format_note(note))


# ─────────────────────────────────────────────
# 快速验证
# ─────────────────────────────────────────────
if __name__ == "__main__":
    gen = ScriptGenerator()

    tests = [
        {"id": 1, "title": "轻奢流沙画摆件创意艺术沙漏装饰品", "price": 19.2, "commission_rate": 7.2},
        {"id": 2, "title": "天然水晶发财树招财摆件桌面玄关礼物", "price": 12.1, "commission_rate": 12.0},
        {"id": 3, "title": "新奇解压骰子6面办公玩具减压魔方", "price": 20.3, "commission_rate": 6.0},
    ]

    for prod in tests:
        print(f"\n\n{'#'*62}")
        print(f"  商品：{prod['title']}")
        print(f"  价格：¥{prod['price']}  佣金：{prod['commission_rate']}%")
        print(f"  识别类目：{detect_category(prod['title'])}")
        scripts = gen.generate_all(prod)
        for s in scripts:
            gen.print_script(s)
