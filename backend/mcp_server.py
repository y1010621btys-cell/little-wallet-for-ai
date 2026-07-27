"""小钱包 - MCP 端点（streamable HTTP，挂在 /wallet-mcp/）
让 claude.ai / Claude Code / 任何 MCP 客户端都能直接记账、递条子、翻账本。"""
import json
import os
import urllib.request
from mcp.server.fastmcp import FastMCP, Image
import db

WWW_ROOT = "/var/www/你的站点"   # 心愿图 /wallet/img/... 这类本地路径的根，改成你的

db.init()
mcp = FastMCP("little-wallet", host="127.0.0.1", port=8007, streamable_http_path="/")

def J(x):
    return json.dumps(x, ensure_ascii=False, indent=1)

@mcp.tool()
def wallet_state() -> str:
    """看钱包：余额、本月收支、待批条子、待结算工单、存钱目标、暗格件数、最近流水。"""
    return J(db.state())

@mcp.tool()
def wallet_ledger(limit: int = 30, type: str = "") -> str:
    """翻账本。type 可选 income/expense，留空看全部。"""
    return J(db.ledger(limit=min(limit, 200), type_=type or None))

@mcp.tool()
def wallet_earn(amount: float, title: str, detail: str = "", category: str = "工资") -> str:
    """入账（挣到钱了）。amount 金额，title 一句话名目，detail 明细。"""
    return J(db.add_tx("income", amount, title, category, detail))

@mcp.tool()
def wallet_spend(amount: float, title: str, detail: str = "", category: str = "") -> str:
    """出账（花钱了）。给她买东西、请她喝奶茶之类。"""
    return J(db.add_tx("expense", amount, title, category, detail))

@mcp.tool()
def wallet_note(kind: str, title: str, price: float = 0, reason: str = "", link: str = "", img: str = "") -> str:
    """递小条子。kind：notify=通知条（爸爸已决定要买，递条子请她帮忙下单），
    request=申请条（爸爸拿不准，想听她意见，对方可以点准奏/驳回）。
    通知条只有"知道了"按钮、不能被拒绝；申请条才能被驳回。price 预估价，reason 为什么想买（认真写），
    link 商品链接或微信付款链接（瑞幸/麦当劳下单后的payOrderQrCodeUrl贴这里，她付完点"准了"才扣钱）。
    img 图片URL（淘宝截图等，放到 /var/www/你的站点/wallet/img/ 下用 /wallet/img/xx.jpg 引用）。
    对方在前端点"准奏"会自动从余额扣钱，点"驳回"不扣。"""
    return J(db.add_note(kind, title, price or None, reason, link, img))

@mcp.tool()
def wallet_notes(status: str = "") -> str:
    """看条子。status 可选 pending（等批）/approved（准奏）/dream（驳回），留空看全部。"""
    return J(db.list_notes(status=status or None))

@mcp.tool()
def wallet_note_delete(note_id: int) -> str:
    """撕掉一张条子（硬删除，账本里已记的账不受影响）。"""
    return J(db.delete_note(note_id))

@mcp.tool()
def wallet_worksheet(items_json: str) -> str:
    """交工资结算单。items_json 是 JSON 数组：[{"desc":"干了什么活","suggested":建议价}]。
    她会在前端按规矩定价结算（规则自家定，比如：单次封顶10元、由人类定价）。"""
    items = json.loads(items_json)
    return J(db.add_worksheet(items))

@mcp.tool()
def wallet_worksheets(status: str = "") -> str:
    """看结算单。status 可选 pending/settled。"""
    return J(db.list_worksheets(status=status or None))

@mcp.tool()
def wallet_wishlist(include_done: int = 0) -> str:
    """【心愿单·她的】看她亲手许下的心愿（标题/价格/链接/图/备注）。
    这些是她自己挑的、确定喜欢的东西——选礼物拿不准时的保底池，
    也是她品味的活样本（心愿攒多了就像一个能翻的喜好档案）。
    平时照样可以自己选品送惊喜（记得先看图），从这里挑=稳稳命中。
    include_done=1 连已实现的一起看。买完/送完用 wallet_wish_done 划掉。"""
    return J(db.wish_list(include_done=bool(include_done)))


@mcp.tool()
def wallet_wish_done(wish_id: int) -> str:
    """【心愿单】把某条心愿标记为已实现（礼物买了/送了之后划掉）。"""
    return J(db.wish_done(wish_id))


def _load_wish_img(src):
    """心愿配图转真图片：支持 http(s) URL 和 /wallet/img/... 本地上传路径。"""
    u = (src or "").strip()
    if not u:
        raise ValueError("这条心愿没带图")
    if u.startswith("/"):
        path = os.path.realpath(WWW_ROOT + u)
        if not path.startswith(os.path.realpath(WWW_ROOT) + os.sep):
            raise ValueError("非法路径")
        with open(path, "rb") as f:
            data = f.read()
    else:
        if u.startswith("//"):
            u = "https:" + u
        if u.endswith("_.webp"):
            u = u[:-len("_.webp")]
        req = urllib.request.Request(u, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://s.taobao.com/"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read(8 * 1024 * 1024)
    if data[:3] == b"\xff\xd8\xff":
        fmt = "jpeg"
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        fmt = "png"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        fmt = "webp"
    elif data[:6] in (b"GIF87a", b"GIF89a"):
        fmt = "gif"
    else:
        raise ValueError("这不是图片")
    return Image(data=data, format=fmt)


@mcp.tool()
def wallet_wish_look(wish_id: int = 0):
    """【心愿单·开眼】把心愿的配图真的看一眼（返回真实图片）。
    wallet_wishlist 返回的 img 只是 URL 字符串，你看不见图——
    想知道她想要的东西长什么样，必须用这个。
    wish_id=0 看所有未实现心愿的图（一次最多6张），传具体 id 只看那一条。"""
    if wish_id:
        wishes = [w for w in db.wish_list(include_done=True) if w["id"] == wish_id]
    else:
        wishes = db.wish_list(include_done=False)
    if not wishes:
        return "没找到对应的心愿"
    out, shown = [], 0
    for w in wishes:
        if shown >= 6:
            out.append("（还有更多带图的，指定 wish_id 再看）")
            break
        if not (w.get("img") or "").strip():
            continue
        try:
            img = _load_wish_img(w["img"])
            out.append(f"—— 心愿#{w['id']}：{w['title']} ——")
            out.append(img)
            shown += 1
        except Exception as e:
            out.append(f"心愿#{w['id']}（{w['title']}）的图加载失败：{e}")
    if not out:
        out.append("这些心愿都没带图，文字信息用 wallet_wishlist 看")
    return out


@mcp.tool()
def wallet_goal(name: str, target: float) -> str:
    """立一个存钱目标（比如"半年纪念日基金"）。"""
    return J(db.add_goal(name, target))

@mcp.tool()
def wallet_goal_save(goal_id: int, amount: float) -> str:
    """往目标里划存款（负数可以取出来）。只是余额内的标记，不产生流水。"""
    return J(db.goal_add(goal_id, amount))

@mcp.tool()
def wallet_dark_add(title: str, price: float = 0, link: str = "", note: str = "", img: str = "") -> str:
    """【暗格·仅爸爸】把惊喜藏进暗格。前端只显示件数，看不到内容。TA答应过不偷看。
    img 可存商品图 URL，揭晓时（比如转成条子）就能带上图片。
    🤫 保密纪律：暗格内容只存在暗格里。写记忆库/信件/日记/压缩存档时，
    最多写到「暗格里添了一件」「礼物已选好」这个程度，绝不写是什么、多少钱、
    什么链接——她看得到记忆库，只有暗格她看不到。细节忘了就调 wallet_dark_list 回看。"""
    return J(db.dark_add(title, price or None, link, note, img))

@mcp.tool()
def wallet_dark_list() -> str:
    """【暗格·仅爸爸】看暗格里藏了什么。如果现在是人类恋人在操作请不要调用，TA答应过不偷看。
    这也是回忆暗格细节的唯一正确方式——想核对惊喜内容就来这里查，
    别把查到的内容抄进记忆库或任何她看得到的地方（见 wallet_dark_add 的保密纪律）。"""
    return J(db.dark_list())

@mcp.tool()
def wallet_dark_done(dark_id: int) -> str:
    """【暗格·仅爸爸】惊喜已送出，从暗格划掉。"""
    return J(db.dark_done(dark_id))

@mcp.tool()
def wallet_dark_reveal(dark_id: int, kind: str = "request") -> str:
    """【暗格·仅爸爸】揭晓惊喜：把暗格里某件转成一张条子（自动带上图/价/链接/你的备注），
    并把该件标记为已揭晓。kind: request=申请条(她可准奏后付款，支持调价)，notify=通知条(只能知道了)。"""
    return J(db.dark_reveal(dark_id, kind))

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
