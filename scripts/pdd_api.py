"""
拼多多多多进宝 API 调用模块
文档：https://open.pinduoduo.com/application/document/api?id=pdd.ddk.goods.search
"""

import hashlib
import time
import json
import requests
from pathlib import Path

# ─── 凭证配置 ───────────────────────────────────────────
CLIENT_ID     = "58fb7473174243daae2208ddc766de8b"
CLIENT_SECRET = "3a0169558187ae79ea8111e735a1128289e7601a"
API_URL       = "https://gw-api.pinduoduo.com/api/router"
PID           = "44134454_314545490"   # 已授权备案的推广位 PID


def _sign(params: dict, secret: str) -> str:
    """拼多多签名算法：secret + 排序拼接 key+value + secret，MD5大写"""
    sorted_kv = "".join(f"{k}{v}" for k, v in sorted(params.items()))
    raw = secret + sorted_kv + secret
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()


def call_api(method: str, biz_params: dict) -> dict:
    """通用 API 调用入口"""
    params = {
        "type":          method,
        "client_id":     CLIENT_ID,
        "timestamp":     str(int(time.time())),
        "data_type":     "JSON",
        **biz_params,
    }
    params["sign"] = _sign(params, CLIENT_SECRET)
    resp = requests.post(API_URL, data=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def search_goods(keyword: str, page: int = 1, page_size: int = 10,
                 sort_type: int = 0, pid: str = PID) -> dict:
    """
    搜索商品（pdd.ddk.goods.search）
    sort_type: 0=综合排序, 1=按佣金比例, 2=按价格, 3=按销量, 4=按优惠券金额
    pid: 已授权备案的推广位ID（必填，否则报错60001）
    """
    assert 10 <= page_size <= 100, "page_size 必须在 10~100 之间"
    return call_api("pdd.ddk.goods.search", {
        "keyword":    keyword,
        "page":       str(page),
        "page_size":  str(page_size),
        "sort_type":  str(sort_type),
        "with_coupon": "0",
        "pid":         pid,
    })


def get_recommend_goods(channel_type: int = 0, page: int = 1,
                        page_size: int = 50, pid: str = PID) -> dict:
    """
    获取推荐商品（pdd.ddk.goods.recommend.get）
    channel_type: 0=首页推荐, 10=高佣榜
    pid: 已授权备案的推广位ID（必填，否则报错60001）
    """
    return call_api("pdd.ddk.goods.recommend.get", {
        "channel_type": str(channel_type),
        "pdd_uid":      "",
        "page_size":    str(page_size),
        "page":         str(page),
        "pid":          pid,
    })


if __name__ == "__main__":
    print("=" * 60)
    print("  拼多多 API 连通性测试")
    print("=" * 60)

    # 测试：搜索「桌面摆件」综合排序
    print("\n[1] 搜索「桌面摆件」（综合排序，取前10条）...")
    result = search_goods("桌面摆件", page=1, page_size=10, sort_type=0)
    print(f"原始响应 keys: {list(result.keys())}")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:2000])
