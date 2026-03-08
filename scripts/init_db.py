"""
数据库初始化脚本
运行方式：python scripts/init_db.py
数据库位置：data/db/main.db
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "../data/db/main.db")


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # ─────────────────────────────────────────────
    # 表1：类目雷达表
    # 记录近期升温的类目信号
    # ─────────────────────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS category_radar (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        date        TEXT    NOT NULL,              -- 记录日期 YYYY-MM-DD
        category_l1 TEXT    NOT NULL,              -- 一级类目（如：办公居家）
        category_l2 TEXT    NOT NULL,              -- 二级类目（如：桌面摆件）
        keyword     TEXT    NOT NULL,              -- 核心关键词
        heat_score  REAL    DEFAULT 0,             -- 热度评分 0-100
        trend_7d    TEXT    DEFAULT 'stable',      -- 7天趋势: rising/stable/falling
        trend_30d   TEXT    DEFAULT 'stable',      -- 30天趋势
        data_source TEXT    DEFAULT 'manual',      -- 数据来源: manual/pdd_api/crawl
        raw_data    TEXT,                          -- 原始数据JSON（备查）
        notes       TEXT,                          -- 人工备注
        created_at  TEXT    DEFAULT (datetime('now','localtime'))
    )
    """)

    # ─────────────────────────────────────────────
    # 表2：候选商品池
    # 所有进入分析流程的商品
    # ─────────────────────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS product_pool (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        pdd_goods_id    TEXT    UNIQUE,            -- 拼多多商品ID（唯一）
        title           TEXT    NOT NULL,          -- 商品标题
        category_l1     TEXT,                      -- 一级类目
        category_l2     TEXT,                      -- 二级类目
        price           REAL,                      -- 现价（元）
        origin_price    REAL,                      -- 原价（元）
        sales_30d       INTEGER DEFAULT 0,         -- 近30天销量
        sales_7d        INTEGER INTEGER DEFAULT 0, -- 近7天销量
        rating          REAL    DEFAULT 0,         -- 商品评分（满5分）
        review_count    INTEGER DEFAULT 0,         -- 评价数量
        commission_rate REAL    DEFAULT 0,         -- 佣金比例 0-100（%）
        commission_amt  REAL    DEFAULT 0,         -- 单件佣金（元）
        pdd_url         TEXT,                      -- 拼多多商品链接
        cover_img       TEXT,                      -- 封面图URL
        status          TEXT    DEFAULT 'pending', -- 状态: pending/scoring/scored/selected/rejected
        add_date        TEXT,                      -- 加入日期
        source_keyword  TEXT,                      -- 来源关键词
        raw_data        TEXT,                      -- 原始数据JSON
        notes           TEXT,
        created_at      TEXT    DEFAULT (datetime('now','localtime')),
        updated_at      TEXT    DEFAULT (datetime('now','localtime'))
    )
    """)

    # ─────────────────────────────────────────────
    # 表3：商品评分详情
    # 13个维度的评分记录（可追溯）
    # ─────────────────────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS product_scores (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id          INTEGER NOT NULL REFERENCES product_pool(id),
        score_date          TEXT    NOT NULL,
        -- 13维评分（每项0-10分）
        s01_pdd_heat        REAL DEFAULT 0,   -- 拼多多热度
        s02_growth_7d       REAL DEFAULT 0,   -- 近7天增速
        s03_trend_30d       REAL DEFAULT 0,   -- 近30天趋势
        s04_douyin_fit      REAL DEFAULT 0,   -- 抖音传播适配度
        s05_visual_strength REAL DEFAULT 0,   -- 视觉展示强度
        s06_low_explain     REAL DEFAULT 0,   -- 低解释成本（越好越高）
        s07_low_decision    REAL DEFAULT 0,   -- 低决策成本
        s08_impulse_price   REAL DEFAULT 0,   -- 价格带冲动消费适合度
        s09_commission_val  REAL DEFAULT 0,   -- 佣金价值
        s10_competition     REAL DEFAULT 0,   -- 竞争难度（越低越好，此处取反）
        s11_supply_stable   REAL DEFAULT 0,   -- 供给稳定性
        s12_compliance_risk REAL DEFAULT 0,   -- 合规风险（越低越好，此处取反）
        s13_refund_risk     REAL DEFAULT 0,   -- 高退货/售后风险（越低越好，此处取反）
        -- 汇总
        total_score         REAL DEFAULT 0,   -- 加权总分 0-100
        score_version       TEXT DEFAULT 'v1',-- 评分模型版本
        score_method        TEXT DEFAULT 'manual', -- manual/auto
        reviewer            TEXT,             -- 审核人
        is_selected         INTEGER DEFAULT 0,-- 是否入选内容池 0/1
        rejection_reason    TEXT,             -- 拒绝原因
        notes               TEXT,
        created_at          TEXT DEFAULT (datetime('now','localtime'))
    )
    """)

    # ─────────────────────────────────────────────
    # 表4：内容任务表
    # 每个商品的脚本/笔记生成任务（支持抖音 + 小红书双平台）
    # ─────────────────────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS content_tasks (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id      INTEGER NOT NULL REFERENCES product_pool(id),
        task_date       TEXT    NOT NULL,
        platform        TEXT    NOT NULL DEFAULT 'douyin',
                                           -- 平台: douyin / xiaohongshu
        script_type     TEXT    NOT NULL,  -- 脚本/笔记类型: pain_point/scene/contrast/list

        -- ── 抖音专属字段 ──────────────────────────
        title           TEXT,              -- 视频标题（≤20字）
        cover_copy      TEXT,              -- 封面大字（≤10字）
        hook_3s         TEXT,              -- 前3秒钩子台词
        storyboard      TEXT,              -- 分镜脚本（JSON，总≤15s）
        subtitle        TEXT,              -- 完整字幕文案
        voiceover       TEXT,              -- 完整口播稿（可选）

        -- ── 小红书专属字段 ───────────────────────
        cover_title     TEXT,              -- 封面大标题（≤20字，XHS核心点击因子）
        cover_subtitle  TEXT,              -- 封面副标题（≤10字）
        body_text       TEXT,              -- 正文（≤1000字，含emoji分段）
        hashtags        TEXT,              -- 话题标签（JSON数组，5-10个）
        img_count       INTEGER DEFAULT 6, -- 建议图片数量（小红书图文张数）
        images_spec     TEXT,              -- 每张图规格说明（JSON数组）
        link_placement  TEXT,              -- 链接放置方式说明
                                           --   inner_mount = 内挂商品卡（联盟商品，优先）
                                           --   comment     = 评论区置顶推广链接
                                           --   profile     = 个人主页推广链接

        -- ── 通用字段 ──────────────────────────────
        cta             TEXT,              -- 行动号召文案
        pub_time_suggest TEXT,             -- 建议发布时间段
        mount_suggest   TEXT,              -- 抖音橱窗/商品挂载建议
        compliance_check TEXT,             -- 合规检查结果（JSON）
        product_category TEXT,             -- 商品类目标签（由生成器写入）

        -- ── 状态 ──────────────────────────────────
        status          TEXT DEFAULT 'draft',
                                           -- draft/pending_review/approved/rejected/published
        gen_method      TEXT DEFAULT 'ai', -- ai/manual
        reviewer        TEXT,
        review_at       TEXT,
        reject_reason   TEXT,
        notes           TEXT,
        created_at      TEXT DEFAULT (datetime('now','localtime')),
        updated_at      TEXT DEFAULT (datetime('now','localtime'))
    )
    """)

    # ─────────────────────────────────────────────
    # 表5：素材任务表
    # 内容审核通过后，生成的拍摄/制作任务（支持抖音 + 小红书双平台）
    # ─────────────────────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS material_tasks (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        content_task_id INTEGER NOT NULL REFERENCES content_tasks(id),
        product_id      INTEGER NOT NULL REFERENCES product_pool(id),
        task_date       TEXT    NOT NULL,
        platform        TEXT    NOT NULL DEFAULT 'douyin',
                                           -- 平台: douyin / xiaohongshu
        material_type   TEXT    NOT NULL,  -- 素材类型：
                                           --   抖音: video / cover
                                           --   小红书: xhs_image（图文中的单张图）/ xhs_cover
        seq_index       INTEGER DEFAULT 1, -- 素材序号（小红书多图时使用，1-9）
        file_name       TEXT,              -- 文件命名规范（含平台前缀，如 xhs_1_封面）
        file_path       TEXT,              -- 本地存储路径
        shoot_guide     TEXT,              -- 拍摄/制作指引（JSON，来自 images_spec）
        edit_guide      TEXT,              -- 剪辑/修图指引
                                           --   抖音: 剪辑说明（时长/字幕/配乐）
                                           --   小红书: 修图说明（滤镜/叠字/构图）
        overlay_text    TEXT,              -- 图片叠加文字（小红书图文专用）
        img_purpose     TEXT,              -- 图片用途: cover/detail/comparison/cta（XHS专用）
        status          TEXT DEFAULT 'pending',
                                           -- pending/shooting/editing/done/rejected
        assigned_to     TEXT,              -- 负责人
        due_date        TEXT,              -- 截止日期
        notes           TEXT,
        created_at      TEXT DEFAULT (datetime('now','localtime')),
        updated_at      TEXT DEFAULT (datetime('now','localtime'))
    )
    """)

    # ─────────────────────────────────────────────
    # 表6：发布记录表
    # 人工审核通过后，记录发布信息（支持抖音 + 小红书双平台）
    # ─────────────────────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS publish_records (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        content_task_id INTEGER NOT NULL REFERENCES content_tasks(id),
        product_id      INTEGER NOT NULL REFERENCES product_pool(id),
        platform        TEXT    NOT NULL DEFAULT 'douyin',
                                           -- 平台: douyin / xiaohongshu

        pub_time        TEXT,              -- 实际发布时间

        -- ── 抖音专属 ──────────────────────────────
        douyin_video_id TEXT,              -- 抖音视频ID
        douyin_url      TEXT,              -- 抖音视频链接
        mount_product_id TEXT,             -- 挂载商品ID（橱窗商品）
        mount_type      TEXT,              -- 挂载类型: window/product_card

        -- ── 小红书专属 ────────────────────────────
        xhs_note_id     TEXT,              -- 小红书笔记ID
        xhs_note_url    TEXT,              -- 小红书笔记链接
        xhs_link_type   TEXT,              -- 实际链接放置方式:
                                           --   inner_mount = 内挂商品卡（联盟商品）
                                           --   comment     = 评论区推广链接
                                           --   profile     = 个人主页推广链接
        xhs_promo_url   TEXT,              -- 实际挂的推广链接（多多进宝/联盟链接）
        xhs_inner_pid   TEXT,              -- 小红书内挂商品联盟PID（inner_mount时填写）

        -- ── 通用 ──────────────────────────────────
        status          TEXT DEFAULT 'published',
                                           -- published/deleted/banned
        published_by    TEXT,              -- 发布人（手动操作）
        notes           TEXT,
        created_at      TEXT DEFAULT (datetime('now','localtime'))
    )
    """)

    # ─────────────────────────────────────────────
    # 表7：数据回传表
    # 视频/笔记表现数据（支持抖音 + 小红书，手动录入）
    # ─────────────────────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS performance_data (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        publish_id      INTEGER NOT NULL REFERENCES publish_records(id),
        product_id      INTEGER NOT NULL REFERENCES product_pool(id),
        platform        TEXT    NOT NULL DEFAULT 'douyin',
                                           -- 平台: douyin / xiaohongshu
        record_date     TEXT    NOT NULL,  -- 统计日期

        -- ── 曝光/播放（抖音主要指标）─────────────
        impressions     INTEGER DEFAULT 0, -- 曝光量（抖音）/ 笔记浏览量（小红书）
        plays           INTEGER DEFAULT 0, -- 播放量（抖音专用）
        play_rate       REAL    DEFAULT 0, -- 播放率（抖音专用）
        avg_watch_pct   REAL    DEFAULT 0, -- 平均观看比例%（抖音专用）

        -- ── 互动（双平台通用）────────────────────
        likes           INTEGER DEFAULT 0, -- 点赞数
        comments        INTEGER DEFAULT 0, -- 评论数
        shares          INTEGER DEFAULT 0, -- 转发/分享数
        saves           INTEGER DEFAULT 0, -- 收藏数（小红书重要指标，抖音也有）

        -- ── 小红书专属互动 ────────────────────────
        xhs_follows     INTEGER DEFAULT 0, -- 通过此篇笔记新增关注数
        xhs_profile_views INTEGER DEFAULT 0, -- 笔记带来的主页访问数

        -- ── 转化（双平台通用）────────────────────
        product_clicks  INTEGER DEFAULT 0, -- 商品点击数
                                           --   抖音: 橱窗/商品卡点击
                                           --   小红书: 内挂商品卡点击 or 评论区链接点击
        orders          INTEGER DEFAULT 0, -- 成单数
        gmv             REAL    DEFAULT 0, -- 成交金额（元）
        commission      REAL    DEFAULT 0, -- 佣金（元）

        -- ── 衍生指标 ──────────────────────────────
        ctr             REAL    DEFAULT 0, -- 商品点击率（product_clicks/impressions）
        cvr             REAL    DEFAULT 0, -- 转化率（orders/product_clicks）
        roi             REAL    DEFAULT 0, -- ROI（佣金/时间成本估算）

        data_source     TEXT    DEFAULT 'manual', -- manual/api
        notes           TEXT,
        created_at      TEXT DEFAULT (datetime('now','localtime'))
    )
    """)

    # ─────────────────────────────────────────────
    # 表8：每日复盘报告
    # ─────────────────────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_review (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        review_date     TEXT    UNIQUE NOT NULL,
        -- 今日数据摘要
        products_analyzed INTEGER DEFAULT 0,
        products_selected INTEGER DEFAULT 0,
        scripts_generated INTEGER DEFAULT 0,
        scripts_approved  INTEGER DEFAULT 0,
        videos_published  INTEGER DEFAULT 0,
        total_commission  REAL    DEFAULT 0,
        -- 复盘内容
        best_product_id   INTEGER,           -- 今日最佳商品
        worst_product_id  INTEGER,           -- 今日最低效商品
        best_script_type  TEXT,              -- 今日最有效脚本类型
        anomalies         TEXT,              -- 今日异常记录（JSON）
        insights          TEXT,              -- 今日洞察
        tomorrow_suggest  TEXT,              -- 明日建议
        -- 权重调整
        weight_update_suggest TEXT,          -- 权重调整建议（JSON）
        weight_updated    INTEGER DEFAULT 0, -- 是否已更新权重 0/1（人工确认后）
        updated_by        TEXT,
        created_at        TEXT DEFAULT (datetime('now','localtime'))
    )
    """)

    # ─────────────────────────────────────────────
    # 表9：评分权重配置历史
    # 记录每次权重变更（可追溯）
    # ─────────────────────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS score_weights (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        version     TEXT    NOT NULL UNIQUE,   -- 版本号 v1, v2...
        is_active   INTEGER DEFAULT 0,         -- 当前生效版本
        -- 13维权重（合计=1.0）
        w01_pdd_heat        REAL DEFAULT 0.10,
        w02_growth_7d       REAL DEFAULT 0.10,
        w03_trend_30d       REAL DEFAULT 0.05,
        w04_douyin_fit      REAL DEFAULT 0.15,
        w05_visual_strength REAL DEFAULT 0.10,
        w06_low_explain     REAL DEFAULT 0.08,
        w07_low_decision    REAL DEFAULT 0.08,
        w08_impulse_price   REAL DEFAULT 0.08,
        w09_commission_val  REAL DEFAULT 0.10,
        w10_competition     REAL DEFAULT 0.05,
        w11_supply_stable   REAL DEFAULT 0.05,
        w12_compliance_risk REAL DEFAULT 0.04,
        w13_refund_risk     REAL DEFAULT 0.02,
        update_reason       TEXT,              -- 更新原因
        updated_by          TEXT,              -- 人工确认人
        created_at          TEXT DEFAULT (datetime('now','localtime'))
    )
    """)

    # ─────────────────────────────────────────────
    # 表10：素材渲染任务表
    # 基于已审核脚本生成的素材渲染任务（素材工厂输出）
    # ─────────────────────────────────────────────
    cur.execute("""
    CREATE TABLE IF NOT EXISTS material_render_tasks (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        content_task_id     INTEGER NOT NULL REFERENCES content_tasks(id),
        product_id          INTEGER NOT NULL REFERENCES product_pool(id),
        platform            TEXT    NOT NULL DEFAULT 'douyin',
                                               -- douyin / xiaohongshu
        script_type         TEXT    NOT NULL,  -- pain_point / scene / contrast / list
        task_date           TEXT    NOT NULL,

        -- ── 素材类型 ──────────────────────────────
        material_type       TEXT    NOT NULL,
                                               -- 抖音: slideshow_video / template_video /
                                               --       subtitle_video / cover_image
                                               -- 小红书: xhs_image_set

        -- ── 文件信息 ──────────────────────────────
        filename            TEXT    NOT NULL,  -- 按命名规范生成，全局唯一
        filepath            TEXT    NOT NULL,  -- 相对项目根目录的路径
        seq_index           INTEGER DEFAULT 0, -- 序号（xhs多图1-9，其他0）

        -- ── 来源追溯（脚本版本号）────────────────
        script_version      TEXT    NOT NULL,  -- 格式: "ct{id}_{YYYYMMDD}"，不可变
        source_storyboard_index INTEGER DEFAULT 0, -- 对应分镜第几段（0=封面/综合）
        source_key_point    TEXT,              -- 该素材的核心卖点文字（每条只讲一个）

        -- ── 渲染规格（JSON）──────────────────────
        render_spec         TEXT,              -- 完整渲染参数（JSON）
                                               -- 包含: 分辨率/时长/字幕轨/分镜/背景类型
                                               -- 抖音: slides/clips/subtitle_track
                                               -- 小红书: overlay_main_text/shot_desc等

        -- ── 视频元数据（JSON，仅视频类型）────────
        video_meta          TEXT,              -- 视频元数据（JSON）
                                               -- 含: title/cover_copy/cta/pub_time_suggest
                                               --     duration_s/resolution/has_subtitle
                                               --     key_point/voiceover_text/script_version

        -- ── 状态 ──────────────────────────────────
        status              TEXT    DEFAULT 'pending',
                                               -- pending/rendering/done/failed
        retry_count         INTEGER DEFAULT 0,
        error_code          TEXT,              -- E001-E099 错误码
        error_message       TEXT,              -- 详细错误信息
        error_stage         TEXT,              -- prepare/render/export/save
        error_context       TEXT,              -- 额外上下文JSON（如缺失资源路径）

        -- ── 时间戳 ────────────────────────────────
        rendered_at         TEXT,              -- 渲染完成时间
        created_at          TEXT    DEFAULT (datetime('now','localtime')),
        updated_at          TEXT    DEFAULT (datetime('now','localtime')),

        UNIQUE(filename)                       -- 文件名全局唯一
    )
    """)

    # 插入默认权重配置 v1
    cur.execute("""
    INSERT OR IGNORE INTO score_weights (version, is_active, update_reason)
    VALUES ('v1', 1, '初始默认权重配置')
    """)

    conn.commit()
    conn.close()
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ 数据库初始化完成：{os.path.abspath(DB_PATH)}")
    print("已创建表：")
    print("  1. category_radar     - 类目雷达")
    print("  2. product_pool       - 候选商品池")
    print("  3. product_scores     - 商品评分详情（13维）")
    print("  4. content_tasks      - 内容脚本/笔记任务（抖音+小红书双平台）")
    print("  5. material_tasks         - 素材制作任务（抖音视频 + 小红书图文）")
    print("  6. publish_records        - 发布记录（抖音橱窗 + 小红书内挂/推广链接）")
    print("  7. performance_data       - 数据回传表（抖音+小红书指标分离）")
    print("  8. daily_review           - 每日复盘")
    print("  9. score_weights          - 评分权重历史")
    print(" 10. material_render_tasks  - 素材渲染任务（素材工厂输出，含脚本版本锚点）")


if __name__ == "__main__":
    init_db()
