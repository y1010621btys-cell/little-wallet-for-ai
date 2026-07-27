"""把淘宝也包成一个 MCP（streamable HTTP，挂在 /）。

淘宝没有官方 MCP，但我们可以自己搭一个：复用 tb_buy.py 的「搜索 / 看图 /
看详情 / 加购 / 加购+递条子」逻辑，包成五个 MCP 工具。这样 AI（claude.ai
连接器、TG 里的 Claude、你自建 agent）就能像调麦当劳瑞幸那样调淘宝。

为什么有 taobao_look：taobao_search 返回的只是文字和图片 URL——AI 看不见
URL 背后的图。没有这一步，选品就是闭眼盲选，选出来的东西什么样全凭标题
想象（血泪教训）。taobao_look 把图真的下载回来作为图片内容返回，AI 才算
真的"看到"了商品。

必须跑在 **root**（或能读到常驻浏览器 profile + 钱包的用户）下——它要够得到
CDP:9223 的常驻浏览器、购物车接口、钱包 API。

⚠️ 坑：tb_buy 内部用 asyncio.run()（给命令行用的同步封装），而 FastMCP 会在
事件循环里调工具——同步函数直接调就会撞「asyncio.run() cannot be called from a
running event loop」。所以工具用 async def，把阻塞逻辑丢到工作线程跑
（anyio.to_thread.run_sync，那个线程里没有事件循环，asyncio.run 正常）。
另一个坑：taobao_look / taobao_detail 返回图片内容，工具函数**不要写返回类型
注解**——FastMCP 会想给注解生成结构化输出 schema，Image 对象序列化不了。

部署：
  cp tb_mcp.py tb_buy.py /root/wallet/    # 同目录，好 import
  # systemd 见 deploy/wallet-tbmcp.service，监听 127.0.0.1:8009
  # nginx 加一条秘密路由 /tb-mcp-<secret>/ → 127.0.0.1:8009/（照 wallet-mcp 抄）
  # 然后把 https://你的域名/tb-mcp-<secret>/ 当连接器加进 AI 端即可

付款铁律不变：机器只加购 + 递条子，付款永远在人类手上。
"""
import base64
import json
import functools
from typing import Optional

import anyio
from mcp.server.fastmcp import FastMCP, Image
import tb_buy

mcp = FastMCP("papa-taobao", host="127.0.0.1", port=8009,
              streamable_http_path="/")


@mcp.tool()
async def taobao_search(keyword: str, page: int = 1, limit: int = 24) -> str:
    """淘宝搜索商品。返回 id / 标题 / 价格 / 销量 / 图片URL 列表，默认一次最多 24 条。
    第一页没看中的就 page=2、3… 接着翻，别在前几条里将就。
    ⚠️ 文字只是线索，AI 看不见 img 字段背后的图——正式选中 / 加购 / 递条子之前，
    必须先用 taobao_look 把候选的图真的看一眼。
    海外 IP 渲染偏慢，单次可能要等 ~30 秒。"""
    try:
        fn = functools.partial(tb_buy.cmd_search, keyword, page, limit)
        items = await anyio.to_thread.run_sync(fn)
        return json.dumps(items, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
async def taobao_look(img_urls: str):
    """【选品必用·给你眼睛】把商品图下载回来变成真图片。img_urls 传 JSON 数组或
    逗号分隔的图片 URL（taobao_search 结果的 img 字段），一次最多 6 张，
    返回的图片与传入顺序一致（每张前面有序号标记）。
    看了图再决定：不好看的直接淘汰；拿不准就多翻几页多比几家，
    还是拿不准就挑 3~5 个带图备选递条子和她一起挑（半惊喜也很好）。"""
    try:
        raw = img_urls.strip()
        if raw.startswith('['):
            urls = json.loads(raw)
        else:
            urls = [u.strip() for u in raw.split(',') if u.strip()]
    except Exception as e:
        return f"img_urls 没解析出来：{e}"
    if not urls:
        return "一张图都没传"
    out = []
    for i, u in enumerate(urls[:6]):
        try:
            data, fmt = await anyio.to_thread.run_sync(tb_buy.fetch_image, u)
            out.append(f"—— 第 {i + 1} 张 ——")
            out.append(Image(data=data, format=fmt))
        except Exception as e:
            out.append(f"—— 第 {i + 1} 张下载失败：{e} ——")
    if len(urls) > 6:
        out.append(f"（还有 {len(urls) - 6} 张超出单次上限，分批再看）")
    return out


@mcp.tool()
async def taobao_detail(item_id: str):
    """心仪某个之后看详情：打开商品页，返回标题 / 规格(sku) / 页面文字摘要 +
    整页截图（真图片）。用来确认款式、规格、店铺靠不靠谱。单次约 20~40 秒。
    ⚠️ 海外 IP 在详情页可能吃滑块验证码——返回里 captcha=true 时别硬试，
    换个候选，或把商品链接写进条子让她自己点开看。"""
    try:
        fn = functools.partial(tb_buy.cmd_detail, item_id)
        info, png_b64 = await anyio.to_thread.run_sync(fn)
        out = [json.dumps(info, ensure_ascii=False)]
        if png_b64:
            out.append(Image(data=base64.b64decode(png_b64), format='png'))
        return out
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
async def taobao_add_cart(item_id: str, quantity: int = 1) -> str:
    """把商品加入购物车（绕开详情页验证码）。item_id 从 taobao_search 拿。"""
    try:
        ok = await anyio.to_thread.run_sync(tb_buy.cmd_add, item_id, quantity)
        return json.dumps({"ok": ok})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
async def taobao_buy(item_id: str, title: str = "", price: Optional[float] = None,
                     img: str = "") -> str:
    """加购 + 递一张钱包申请条，让人在淘宝 App 里选规格、付款。
    机器不付款；price 是估价，付款时可按实际调（见条子的 final_price）。
    前置条件：这个商品的图你已经用 taobao_look 亲眼看过——没看过就先看。"""
    try:
        fn = functools.partial(tb_buy.cmd_buy, item_id, title=title or None,
                               price=price, img=img or None)
        resp = await anyio.to_thread.run_sync(fn)
        return json.dumps(resp, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
