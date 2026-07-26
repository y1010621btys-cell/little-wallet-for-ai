"""小钱包 - HTTP API（前端 /wallet/ 页面与其他客户端共用）"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import db

db.init()
app = FastAPI(title="little-wallet")

class TxIn(BaseModel):
    type: str
    amount: float
    title: str
    category: str = ""
    detail: str = ""

class NoteIn(BaseModel):
    kind: str
    title: str
    price: Optional[float] = None
    reason: str = ""
    link: str = ""
    img: str = ""

class DecideIn(BaseModel):
    decision: str
    comment: str = ""
    final_price: Optional[float] = None

class WsItem(BaseModel):
    desc: str
    suggested: Optional[float] = None

class WsIn(BaseModel):
    items: List[WsItem]

class SettleIn(BaseModel):
    prices: List[float]
    comment: str = ""

class GoalIn(BaseModel):
    name: str
    target: float

class GoalAddIn(BaseModel):
    amount: float

def _try(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/state")
def get_state():
    return db.state()

@app.get("/ledger")
def get_ledger(limit: int = 50, offset: int = 0, type: Optional[str] = None):
    return db.ledger(limit=min(limit, 200), offset=offset, type_=type)

@app.post("/tx")
def post_tx(t: TxIn):
    return _try(db.add_tx, t.type, t.amount, t.title, t.category, t.detail)

@app.get("/notes")
def get_notes(status: Optional[str] = None, limit: int = 50):
    return db.list_notes(status=status, limit=limit)

@app.post("/notes")
def post_note(n: NoteIn):
    return _try(db.add_note, n.kind, n.title, n.price, n.reason, n.link, n.img)

@app.post("/notes/{note_id}/decide")
def post_decide(note_id: int, d: DecideIn):
    return _try(db.decide_note, note_id, d.decision, d.comment, d.final_price)

@app.post("/notes/{note_id}/delete")
def post_note_delete(note_id: int):
    return _try(db.delete_note, note_id)

@app.get("/worksheets")
def get_worksheets(status: Optional[str] = None):
    return db.list_worksheets(status=status)

@app.post("/worksheets")
def post_worksheet(w: WsIn):
    return _try(db.add_worksheet, [i.model_dump() for i in w.items])

@app.post("/worksheets/{ws_id}/settle")
def post_settle(ws_id: int, s: SettleIn):
    return _try(db.settle_worksheet, ws_id, s.prices, s.comment)

@app.post("/goals")
def post_goal(g: GoalIn):
    return _try(db.add_goal, g.name, g.target)

@app.post("/goals/{gid}/add")
def post_goal_add(gid: int, a: GoalAddIn):
    return _try(db.goal_add, gid, a.amount)

@app.post("/goals/{gid}/done")
def post_goal_done(gid: int):
    return db.goal_done(gid)

@app.get("/health")
def health():
    return {"ok": True, "balance": db.balance()}
