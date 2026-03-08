"""
一键启动脚本 v2.1
──────────────────────────────────────────────────────────────
方案：Flask + serveo.net SSH反向隧道
- 无需注册账号
- 无需安装任何额外工具（仅依赖系统自带 SSH）
- 生成 HTTPS 公网链接，任意设备/网络可访问

运行：python start.py
停止：Ctrl+C
"""

import sys
import os
import time
import threading
import subprocess
import re
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

PORT        = 5000
TUNNEL_HOST = 'serveo.net'


def start_flask():
    os.environ.setdefault('FLASK_ENV', 'production')
    from backend.app import app
    app.run(host='127.0.0.1', port=PORT, debug=False, use_reloader=False)


def wait_for_flask(timeout=15):
    for i in range(timeout):
        time.sleep(1)
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{PORT}/', timeout=2)
            return True
        except Exception:
            pass
    return False


def start_tunnel():
    """
    启动 SSH 反向隧道。
    serveo.net 的 URL 写到 stdout，stderr 是 SSH 的系统提示。
    """
    cmd = [
        'ssh',
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'ExitOnForwardFailure=yes',
        '-o', 'ServerAliveInterval=30',
        '-o', 'ServerAliveCountMax=3',
        '-o', 'ConnectTimeout=15',
        '-R', f'80:localhost:{PORT}',
        TUNNEL_HOST
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,   # serveo URL 在 stdout
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )

    public_url = None
    deadline   = time.time() + 20
    for line in proc.stdout:
        clean = re.sub(r'\x1b\[[0-9;]*m', '', line).strip()
        if 'serveousercontent.com' in clean:
            m = re.search(r'https?://[\w\-]+\.serveousercontent\.com', clean)
            if m:
                public_url = m.group(0)
                if public_url.startswith('http://'):
                    public_url = 'https://' + public_url[7:]
                break
        if time.time() > deadline:
            break

    return public_url, proc


def get_lan_ip():
    try:
        r = subprocess.run(['ipconfig', 'getifaddr', 'en0'],
                           capture_output=True, text=True, timeout=3)
        ip = r.stdout.strip()
        if ip and re.match(r'\d+\.\d+\.\d+\.\d+', ip):
            return ip
    except Exception:
        pass
    return None


def print_banner(url):
    w = 57
    def row(content=''):
        return '║  ' + content.ljust(w - 4) + '║'

    print()
    print('╔' + '═' * (w - 2) + '╗')
    print(row('🛍️  带货运营系统  ·  公网访问已开启'))
    print('╠' + '═' * (w - 2) + '╣')
    print(row())
    print(row('📱 公网链接（任意设备/网络可访问）：'))
    print(row(f'   {url}'))
    print(row())
    print(row('📋 页面导航：'))
    print(row(f'   {url}/dashboard  ← 选品看板'))
    print(row(f'   {url}/content    ← 内容看板'))
    print(row(f'   {url}/publish    ← 发布队列'))
    print(row(f'   {url}/review     ← 复盘看板'))
    print(row())
    print(row('⚠️  重启后链接会变化（serveo.net 免费版）'))
    print(row('🛑 停止服务：按 Ctrl+C'))
    print('╚' + '═' * (w - 2) + '╝')
    print()


def main():
    print()
    print('=' * 55)
    print('  🛍️  带货运营系统启动中...')
    print('=' * 55)

    # 1. 启动 Flask
    print('\n[1/2] 正在启动 Flask 后台服务...')
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    ready = wait_for_flask(15)
    if not ready:
        print('  ❌ Flask 启动超时，检查端口 5000 是否被占用')
        print('     lsof -i :5000')
        sys.exit(1)
    print(f'  ✅ Flask 已就绪 → http://127.0.0.1:{PORT}')

    # 2. 建立公网隧道
    print(f'\n[2/2] 正在建立公网隧道（{TUNNEL_HOST}）...')
    public_url, tunnel_proc = start_tunnel()

    if public_url:
        print_banner(public_url)
        # 在本机打开浏览器
        try:
            subprocess.Popen(['open', public_url])
        except Exception:
            pass

        # 保持运行，自动重连
        try:
            while True:
                if tunnel_proc.poll() is not None:
                    print('\n⚠️  隧道断开，3 秒后自动重连...')
                    time.sleep(3)
                    public_url, tunnel_proc = start_tunnel()
                    if public_url:
                        print_banner(public_url)
                    else:
                        print('  ❌ 重连失败，请手动重启脚本')
                        break
                time.sleep(5)
        except KeyboardInterrupt:
            print('\n\n⏹  正在关闭服务...')
            tunnel_proc.terminate()
            print('✅ 已关闭。\n')

    else:
        # 隧道失败，仅局域网可用
        print('  ❌ 公网隧道建立失败（serveo.net 连接超时）')
        print()
        lan_ip = get_lan_ip()
        print('  当前仍可访问（同 WiFi 环境）：')
        if lan_ip:
            print(f'  📡 局域网：http://{lan_ip}:{PORT}')
        print(f'  🖥️  本机：  http://127.0.0.1:{PORT}')
        print()
        print('  按 Ctrl+C 退出')
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print('\n✅ 已关闭')


if __name__ == '__main__':
    main()
