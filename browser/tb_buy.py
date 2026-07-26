"""淘宝购物助手 · 连常驻浏览器搜索 + 用购物车 API 加购 + 递条子。

为什么这么绕：淘宝详情页（item.taobao.com）对海外 VPS 的 IP 会弹滑块验证码，
自动化过不去；但**加入购物车的接口 cart.taobao.com/add_cart_item.htm 不验证**。
所以流程是「搜索拿商品 ID → 直接调加购接口 → 递条子 → 你在 App 里选规格付款」，
全程不碰详情页那道验证码。

前提：
  - 常驻 headed 浏览器开着并已登录淘宝（见 04 教程 / taobao-browser.service），
    CDP 调试端口在 127.0.0.1:9223
  - 钱包 API 在 127.0.0.1:8006（教程 1）
  - pip install websockets

用法：
    python3 tb_buy.py search "猫条"
    python3 tb_buy.py add <item_id> [数量]
    python3 tb_buy.py buy <item_id> [--title 标题] [--price 估价] [--img 图片URL]
"""
import json
import os
import sys
import time
import asyncio
import urllib.request

WALLET_API = "http://127.0.0.1:8006"     # 钱包后端
CDP_URL = "http://127.0.0.1:9223"        # 常驻浏览器的 CDP 调试端口
COOKIE_CACHE = "/root/browser/.tb_cookies_cache"
COOKIE_MAX_AGE = 600                      # cookie 缓存 10 分钟


def get_cookies_from_browser():
    """通过 CDP 从常驻浏览器里拿淘宝 cookie（含 _tb_token_）。"""
    import websockets

    async def _get():
        targets = json.loads(urllib.request.urlopen(f'{CDP_URL}/json').read())
        page = next((t for t in targets if t.get('type') == 'page'), None)
        if not page:
            raise RuntimeError("常驻浏览器没有 page 目标，先确认它开着")
        async with websockets.connect(page['webSocketDebuggerUrl'],
                                      max_size=5 * 1024 * 1024) as ws:
            await ws.send(json.dumps({
                'id': 1, 'method': 'Network.getCookies',
                'params': {'urls': ['https://www.taobao.com',
                                    'https://cart.taobao.com',
                                    'https://s.taobao.com']}}))
            while True:
                resp = json.loads(await ws.recv())
                if resp.get('id') == 1:
                    cookies = resp['result']['cookies']
                    return '; '.join(f"{c['name']}={c['value']}" for c in cookies)

    cookie_str = asyncio.run(_get())
    os.makedirs(os.path.dirname(COOKIE_CACHE), exist_ok=True)
    with open(COOKIE_CACHE, 'w') as f:
        f.write(cookie_str)
    return cookie_str


def get_cookies():
    if os.path.exists(COOKIE_CACHE):
        if time.time() - os.path.getmtime(COOKIE_CACHE) < COOKIE_MAX_AGE:
            return open(COOKIE_CACHE).read()
    return get_cookies_from_browser()


def get_tb_token(cookies):
    for part in cookies.split('; '):
        if part.startswith('_tb_token_='):
            return part.split('=', 1)[1]
    return ''


def tb_request(url, cookies, data=None):
    headers = {
        'Cookie': cookies,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://s.taobao.com/',
    }
    if data is not None:
        body = '&'.join(f'{k}={v}' for k, v in data.items()).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
        req = urllib.request.Request(url, data=body, headers=headers)
    else:
        req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode('utf-8', errors='replace')


def cmd_search(query):
    """连常驻浏览器搜淘宝，抓前几条结果（ID / 标题 / 价格 / 图）。"""
    import websockets

    async def _search():
        targets = json.loads(urllib.request.urlopen(f'{CDP_URL}/json').read())
        page = next((t for t in targets if t.get('type') == 'page'), None)
        async with websockets.connect(page['webSocketDebuggerUrl'],
                                      max_size=10 * 1024 * 1024) as ws:
            mid = 1

            async def send(method, params=None):
                nonlocal mid
                m = {'id': mid, 'method': method}
                if params:
                    m['params'] = params
                await ws.send(json.dumps(m))
                while True:
                    resp = json.loads(await ws.recv())
                    if resp.get('id') == mid:
                        mid += 1
                        return resp

            encoded = urllib.request.quote(query)
            await send('Page.navigate',
                       {'url': f'https://s.taobao.com/search?q={encoded}'})
            await asyncio.sleep(8)   # 等结果异步渲染

            js = r'''(() => {
                const links = document.querySelectorAll('a[href*="id="]');
                const seen = new Set(), items = [];
                for (const a of links) {
                    const m = a.href.match(/id=(\d+)/);
                    if (!m || m[1] === '0' || seen.has(m[1])) continue;
                    seen.add(m[1]);
                    let box = a.closest('[class*="Card"], [class*="card"], [class*="item"]')
                              || a.parentElement.parentElement.parentElement;
                    let text = box ? box.innerText : a.innerText;
                    let img = box ? box.querySelector('img[src*="alicdn"]') : null;
                    const title = text.split('\n').find(
                        l => l.length > 10 && !l.startsWith('¥') && !/^\d/.test(l)) || '';
                    const price = text.match(/¥\s*(\d+\.?\d*)/);
                    items.push({id: m[1], title: title.trim().slice(0, 80),
                                price: price ? price[1] : null,
                                img: img ? img.src : null});
                    if (items.length >= 8) break;
                }
                return JSON.stringify(items);
            })()'''
            r = await send('Runtime.evaluate',
                           {'expression': js, 'returnByValue': True})
            return json.loads(r['result']['result']['value'])

    items = asyncio.run(_search())
    for it in items:
        print(f"  id={it['id']}  ¥{it.get('price','?')}  {it.get('title','')[:60]}")
        if it.get('img'):
            print(f"    img: {it['img'][:100]}")
    return items


def cmd_add(item_id, quantity=1):
    """加入购物车（绕开详情页验证码）。"""
    cookies = get_cookies()
    token = get_tb_token(cookies)
    if not token:
        print("没拿到 _tb_token_，登录可能过期了，先去常驻浏览器重登")
        return False
    resp = tb_request("https://cart.taobao.com/add_cart_item.htm", cookies,
                      {'item_id': item_id, 'quantity': quantity,
                       '_tb_token_': token})
    if 'cartQuantity' in resp:
        import re
        m = re.search(r'"cartQuantity":\s*"(\d+)"', resp)
        print(f"加购成功，购物车共 {m.group(1) if m else '?'} 件")
        return True
    print(f"加购失败：{resp[:200]}")
    return False


def cmd_buy(item_id, title=None, price=None, img=None):
    """加购 + 递一张申请条（估价可写，她付款时按实际调）。"""
    if not cmd_add(item_id):
        return None
    note = {
        "kind": "request",
        "title": title or f"淘宝商品 {item_id}",
        "price": float(price) if price else None,
        "reason": "已加入购物车，请打开淘宝 App → 购物车 → 选规格 → 付款。",
        "link": f"https://item.taobao.com/item.htm?id={item_id}",
        "img": img or "",
    }
    body = json.dumps(note, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(f"{WALLET_API}/notes", data=body,
                                 headers={"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
    print(f"条子已递：id={resp.get('id')}")
    return resp


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == 'search':
        cmd_search(sys.argv[2] if len(sys.argv) > 2 else '铅笔')
    elif cmd == 'add':
        cmd_add(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 1)
    elif cmd == 'buy':
        kw, args, i = {}, sys.argv[3:], 0
        while i < len(args):
            if args[i] in ('--title', '--price', '--img') and i + 1 < len(args):
                kw[args[i][2:]] = args[i + 1]
                i += 2
            else:
                i += 1
        cmd_buy(sys.argv[2], **kw)
    else:
        print(f"未知命令：{cmd}")
        print(__doc__)
