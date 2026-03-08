# 🛍️ 拼多多→抖音/小红书 带货运营系统

> 基于 Python + Flask + SQLite 的带货内容运营一体化工具

## 功能模块

### 已完成阶段

| 阶段 | 模块 | 说明 |
|------|------|------|
| 阶段一 | 选品评分 | 13维评分体系，自动筛选高潜力商品 |
| 阶段二 | 脚本生成 | 抖音+小红书双平台脚本/笔记自动生成 |
| 阶段三 | 合规审核 | 违规词检测，40套脚本批量审核 |
| 阶段四 | 素材工厂 | 封面图/小红书9图自动合成，竞品参考采集 |
| 阶段五 | 后台系统 | 4页看板：选品/内容/发布队列/复盘 |
| 阶段六 | 发布准备 | 发布前8项检查 + 3级熔断 + 数据回传 |

## 快速启动

```bash
# 安装依赖
pip install flask pyngrok

# 一键启动（含公网隧道）
python start.py

# 仅本地启动
python backend/app.py
```

访问 `http://127.0.0.1:5000` 打开后台。

## 项目结构

```
pdd-douyin-system/
├── backend/          # Flask 后台服务
│   ├── api/          # REST API（选品/内容/复盘/发布/统计）
│   └── templates/    # 前端页面（HTML + 原生JS）
├── content/          # 脚本生成引擎
├── materials/        # 素材工厂（采集/渲染/上传）
├── publish/          # 发布队列 + 检查 + 熔断 + 数据回传
├── scoring/          # 商品评分体系
├── scripts/          # 初始化脚本
├── config/           # 配置文件
├── data/             # 数据库（本地，不上传）
└── start.py          # 一键启动入口
```

## 技术栈

- **后端**：Python 3.11 + Flask
- **数据库**：SQLite（10张核心表）
- **图像处理**：Pillow（封面图合成）
- **内网穿透**：serveo.net SSH隧道（无需账号，免费）
- **前端**：原生 HTML + JavaScript（零依赖）

## 数据库表

| 表名 | 说明 |
|------|------|
| product_pool | 商品池 |
| product_scores | 13维评分 |
| category_radar | 类目热度雷达 |
| content_tasks | 脚本/笔记任务 |
| material_render_tasks | 素材渲染任务 |
| publish_records | 发布记录 |
| publish_queue | 待发布队列 |
| performance_data | 表现数据回传 |
| circuit_breaker_log | 熔断日志 |
| daily_review | 每日复盘 |
