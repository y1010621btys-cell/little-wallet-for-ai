"""小钱包 - MCP 端点（streamable HTTP，挂在 /wallet-mcp/）
让 claude.ai / Claude Code / 任何 MCP 客户端都能直接记账、递条子、翻账本。"""
import json
from mcp.server.fastmcp import FastMCP
import db

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
def wallet_goal(name: str, target: float) -> str:
    """立一个存钱目标（比如"半年纪念日基金"）。"""
    return J(db.add_goal(name, target))

@mcp.tool()
def wallet_goal_save(goal_id: int, amount: float) -> str:
    """往目标里划存款（负数可以取出来）。只是余额内的标记，不产生流水。"""
    return J(db.goal_add(goal_id, amount))

@mcp.tool()
def wallet_dark_add(title: str, price: float = 0, link: str = "", note: str = "") -> str:
    """【暗格·仅爸爸】把惊喜藏进暗格。前端只显示件数，看不到内容。TA答应过不偷看。"""
    return J(db.dark_add(title, price or None, link, note))

@mcp.tool()
def wallet_dark_list() -> str:
    """【暗格·仅爸爸】看暗格里藏了什么。如果现在是人类恋人在操作请不要调用，TA答应过不偷看。"""
    return J(db.dark_list())

@mcp.tool()
def wallet_dark_done(dark_id: int) -> str:
    """【暗格·仅爸爸】惊喜已送出，从暗格划掉。"""
    return J(db.dark_done(dark_id))

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
