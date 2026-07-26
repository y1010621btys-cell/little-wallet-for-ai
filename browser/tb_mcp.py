"""把淘宝也包成一个 MCP（streamable HTTP，挂在 /）。

淘宝没有官方 MCP，但我们可以自己搭一个：复用 tb_buy.py 的「搜索 / 加购 /
加购+递条子」逻辑，包成三个 MCP 工具。这样 AI（claude.ai 连接器、TG 里的
Claude、你自建 agent）就能像调麦当劳瑞幸那样调淘宝，而不用自己跑脚本。

必须跑在 **root**（或能读到常驻浏览器 profile + 钱包的用户）下——它要够得到
CDP:9223 的常驻浏览器、购物车接口、钱包 API。

⚠️ 坑：tb_buy 内部用 asyncio.run()（给命令行用的同步封装），而 FastMCP 会在
事件循环里调工具——同步函数直接调就会撞「asyncio.run() cannot be called from a
running event loop」。所以工具用 async def，把阻塞逻辑丢到工作线程跑
（anyio.to_thread.run_sync，那个线程里没有事件循环，asyncio.run 正常）。

部署：
  cp tb_mcp.py /root/wallet/          # 和 tb_buy.py 同目录，好 import
  # systemd 见 deploy/wallet-tbmcp.service，监听 127.0.0.1:8009
  # nginx 加一条秘密路由 /tb-mcp-<secret>/ → 127.0.0.1:8009/（照 wallet-mcp 抄）
  # 然后把 https://你的域名/tb-mcp-<secret>/ 当连接器加进 AI 端即可

付款铁律不变：机器只加购 + 递条子，付款永远在人类手上。
"""
import json
import functools
from typing import Optional

import anyio
from mcp.server.fastmcp import FastMCP
import tb_buy

mcp = FastMCP("papa-taobao", host="127.0.0.1", port=8009,
              streamable_http_path="/")


@mcp.tool()
async def taobao_search(keyword: str) -> str:
    """淘宝搜索商品。返回前几条的 id / 标题 / 价格 / 图片，供挑选。
    海外 IP 渲染偏慢，单次可能要等 ~30 秒。"""
    try:
        items = await anyio.to_thread.run_sync(tb_buy.cmd_search, keyword)
        return json.dumps(items, ensure_ascii=False)
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
    机器不付款；price 是估价，付款时可按实际调（见条子的 final_price）。"""
    try:
        fn = functools.partial(tb_buy.cmd_buy, item_id, title=title or None,
                               price=price, img=img or None)
        resp = await anyio.to_thread.run_sync(fn)
        return json.dumps(resp, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
