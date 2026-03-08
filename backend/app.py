"""
后台管理系统入口
运行：python backend/app.py
访问：http://127.0.0.1:5000
"""

import sys
import os

# 添加项目根目录到 path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from flask import Flask, render_template, jsonify, request, redirect, url_for
from backend.api.products import products_bp
from backend.api.content import content_bp
from backend.api.review import review_bp
from backend.api.stats import stats_bp
from backend.api.publish import publish_bp

app = Flask(__name__,
            template_folder='templates',
            static_folder='static')

# 注册蓝图
app.register_blueprint(products_bp, url_prefix='/api/v1')
app.register_blueprint(content_bp,  url_prefix='/api/v1')
app.register_blueprint(review_bp,   url_prefix='/api/v1')
app.register_blueprint(stats_bp,    url_prefix='/api/v1')
app.register_blueprint(publish_bp,  url_prefix='/api/v1')


# ── 页面路由 ──────────────────────────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('page_dashboard'))


@app.route('/dashboard')
def page_dashboard():
    """第一页：选品看板"""
    return render_template('dashboard.html', active='dashboard')


@app.route('/content')
def page_content():
    """第二页：内容看板"""
    return render_template('content.html', active='content')


@app.route('/review')
def page_review():
    """第三页：复盘看板"""
    return render_template('review.html', active='review')


@app.route('/publish')
def page_publish():
    """第四页：发布队列"""
    return render_template('publish.html', active='publish')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0',  help='监听地址（默认0.0.0.0对外开放）')
    parser.add_argument('--port', default=5000, type=int, help='端口（默认5000）')
    parser.add_argument('--debug', action='store_true', default=False)
    args = parser.parse_args()

    print("=" * 50)
    print("🚀 后台管理系统已启动")
    print(f"📌 本机访问：http://127.0.0.1:{args.port}")
    print(f"📡 局域网访问：http://0.0.0.0:{args.port}")
    print("=" * 50)
    app.run(debug=args.debug, host=args.host, port=args.port)
