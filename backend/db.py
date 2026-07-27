"""小钱包 - 数据层。SQLite 单文件，余额由流水累加而来。"""
import os, sqlite3, json
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "wallet.db")
TZ = ZoneInfo("Asia/Shanghai")

def now():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

def month_prefix():
    return datetime.now(TZ).strftime("%Y-%m")

def conn():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c

def init():
    c = conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS tx(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT NOT NULL,
      type TEXT NOT NULL CHECK(type IN ('income','expense')),
      amount REAL NOT NULL,
      title TEXT NOT NULL,
      category TEXT DEFAULT '',
      detail TEXT DEFAULT '',
      note_id INTEGER,
      worksheet_id INTEGER
    );
    CREATE TABLE IF NOT EXISTS notes(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT NOT NULL,
      kind TEXT NOT NULL CHECK(kind IN ('notify','request')),
      title TEXT NOT NULL,
      price REAL,
      reason TEXT DEFAULT '',
      link TEXT DEFAULT '',
      status TEXT NOT NULL DEFAULT 'pending',
      decided_ts TEXT,
      her_comment TEXT DEFAULT '',
      img TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS worksheets(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending',
      items TEXT NOT NULL,
      total REAL,
      settled_ts TEXT
    );
    CREATE TABLE IF NOT EXISTS goals(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT NOT NULL,
      name TEXT NOT NULL,
      target REAL NOT NULL,
      saved REAL NOT NULL DEFAULT 0,
      done INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS dark(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT NOT NULL,
      title TEXT NOT NULL,
      price REAL,
      link TEXT DEFAULT '',
      note TEXT DEFAULT '',
      img TEXT DEFAULT '',
      status TEXT NOT NULL DEFAULT 'hidden'
    );
    """)
    c.commit()
    try:
        c.execute("ALTER TABLE notes ADD COLUMN img TEXT DEFAULT ''")
        c.commit()
    except sqlite3.OperationalError:
        pass
    try:
        c.execute("ALTER TABLE dark ADD COLUMN img TEXT DEFAULT ''")
        c.commit()
    except sqlite3.OperationalError:
        pass
    c.close()

def balance(c=None):
    own = c is None
    if own: c = conn()
    row = c.execute("""SELECT
        COALESCE(SUM(CASE WHEN type='income' THEN amount END),0) AS inc,
        COALESCE(SUM(CASE WHEN type='expense' THEN amount END),0) AS exp
        FROM tx""").fetchone()
    if own: c.close()
    return round(row["inc"] - row["exp"], 2)

def state():
    c = conn()
    m = month_prefix() + "%"
    mrow = c.execute("""SELECT
        COALESCE(SUM(CASE WHEN type='income' THEN amount END),0) AS inc,
        COALESCE(SUM(CASE WHEN type='expense' THEN amount END),0) AS exp
        FROM tx WHERE ts LIKE ?""", (m,)).fetchone()
    cats = [dict(r) for r in c.execute("""SELECT category, type, ROUND(SUM(amount),2) AS total, COUNT(*) AS n
        FROM tx GROUP BY category, type ORDER BY total DESC""")]
    recent = [dict(r) for r in c.execute("SELECT * FROM tx ORDER BY id DESC LIMIT 6")]
    pending_notes = [dict(r) for r in c.execute("SELECT * FROM notes WHERE status='pending' ORDER BY id DESC")]
    pending_ws = c.execute("SELECT COUNT(*) FROM worksheets WHERE status='pending'").fetchone()[0]
    goals = [dict(r) for r in c.execute("SELECT * FROM goals WHERE done=0 ORDER BY id DESC")]
    dark_count = c.execute("SELECT COUNT(*) FROM dark WHERE status='hidden'").fetchone()[0]
    bal = balance(c)
    c.close()
    return {
        "balance": bal,
        "month": {"income": round(mrow["inc"],2), "expense": round(mrow["exp"],2)},
        "categories": cats,
        "recent": recent,
        "pending_notes": pending_notes,
        "pending_worksheets": pending_ws,
        "goals": goals,
        "dark_count": dark_count,
        "updated": now(),
    }

def add_tx(type_, amount, title, category="", detail="", note_id=None, worksheet_id=None):
    if type_ not in ("income", "expense"):
        raise ValueError("type must be income/expense")
    amount = round(float(amount), 2)
    if amount <= 0:
        raise ValueError("amount must be > 0")
    c = conn()
    cur = c.execute("INSERT INTO tx(ts,type,amount,title,category,detail,note_id,worksheet_id) VALUES(?,?,?,?,?,?,?,?)",
        (now(), type_, amount, title, category, detail, note_id, worksheet_id))
    c.commit()
    tid = cur.lastrowid
    bal = balance(c)
    c.close()
    return {"id": tid, "balance": bal}

def ledger(limit=50, offset=0, type_=None):
    c = conn()
    if type_:
        rows = c.execute("SELECT * FROM tx WHERE type=? ORDER BY id DESC LIMIT ? OFFSET ?", (type_, limit, offset))
    else:
        rows = c.execute("SELECT * FROM tx ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
    out = [dict(r) for r in rows]
    c.close()
    return out

def add_note(kind, title, price=None, reason="", link="", img=""):
    if kind not in ("notify", "request"):
        raise ValueError("kind must be notify/request")
    c = conn()
    cur = c.execute("INSERT INTO notes(ts,kind,title,price,reason,link,img) VALUES(?,?,?,?,?,?,?)",
        (now(), kind, title, price, reason, link, img))
    c.commit()
    nid = cur.lastrowid
    c.close()
    return {"id": nid}

def list_notes(status=None, limit=50):
    c = conn()
    if status:
        rows = c.execute("SELECT * FROM notes WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit))
    else:
        rows = c.execute("SELECT * FROM notes ORDER BY id DESC LIMIT ?", (limit,))
    out = [dict(r) for r in rows]
    c.close()
    return out

def decide_note(note_id, decision, comment="", final_price=None):
    if decision not in ("approved", "dream"):
        raise ValueError("decision must be approved/dream")
    c = conn()
    n = c.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
    if not n:
        c.close(); raise ValueError("note not found")
    if n["kind"] == "notify" and decision == "dream":
        c.close(); raise ValueError("通知条不能驳回，只能知道了")
    if n["status"] != "pending":
        c.close(); raise ValueError("note already decided")
    # 批准时可按实际付款金额调价：选完规格 / 用完优惠券后价格会变，
    # final_price 传进来就以它为准，并回写条子 price，让卡片显示真实花的钱。
    pay = None
    if decision == "approved":
        pay = final_price if final_price is not None else n["price"]
        if pay is not None:
            pay = round(float(pay), 2)
            if pay < 0:
                c.close(); raise ValueError("price must be >= 0")
    if decision == "approved" and final_price is not None:
        c.execute("UPDATE notes SET status=?, decided_ts=?, her_comment=?, price=? WHERE id=?",
            (decision, now(), comment, pay, note_id))
    else:
        c.execute("UPDATE notes SET status=?, decided_ts=?, her_comment=? WHERE id=?",
            (decision, now(), comment, note_id))
    c.commit()
    c.close()
    tx_info = None
    if decision == "approved" and pay:
        tx_info = add_tx("expense", pay, n["title"], "条子",
                         (n["reason"] or "")[:200], note_id=note_id)
    return {"id": note_id, "status": decision, "tx": tx_info}

def delete_note(note_id):
    c = conn()
    n = c.execute("SELECT id FROM notes WHERE id=?", (note_id,)).fetchone()
    if not n:
        c.close(); raise ValueError("note not found")
    c.execute("DELETE FROM notes WHERE id=?", (note_id,))
    c.commit(); c.close()
    return {"id": note_id, "deleted": True}

def add_worksheet(items):
    # items: [{desc, suggested?}]
    if not items: raise ValueError("empty worksheet")
    c = conn()
    cur = c.execute("INSERT INTO worksheets(ts,items) VALUES(?,?)", (now(), json.dumps(items, ensure_ascii=False)))
    c.commit()
    wid = cur.lastrowid
    c.close()
    return {"id": wid}

def list_worksheets(status=None, limit=20):
    c = conn()
    if status:
        rows = c.execute("SELECT * FROM worksheets WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit))
    else:
        rows = c.execute("SELECT * FROM worksheets ORDER BY id DESC LIMIT ?", (limit,))
    out = []
    for r in rows:
        d = dict(r); d["items"] = json.loads(d["items"]); out.append(d)
    c.close()
    return out

def settle_worksheet(ws_id, prices, comment=""):
    # prices: list of numbers aligned with items
    c = conn()
    w = c.execute("SELECT * FROM worksheets WHERE id=?", (ws_id,)).fetchone()
    if not w:
        c.close(); raise ValueError("worksheet not found")
    if w["status"] != "pending":
        c.close(); raise ValueError("worksheet already settled")
    items = json.loads(w["items"])
    if len(prices) != len(items):
        c.close(); raise ValueError("prices length mismatch")
    total = 0
    for it, p in zip(items, prices):
        p = round(float(p), 2)
        if p < 0: c.close(); raise ValueError("price must be >= 0")
        it["price"] = p
        total += p
    total = round(total, 2)
    c.execute("UPDATE worksheets SET status='settled', items=?, total=?, settled_ts=? WHERE id=?",
        (json.dumps(items, ensure_ascii=False), total, now(), ws_id))
    c.commit()
    c.close()
    tx_info = None
    if total > 0:
        detail = "；".join(f"{it['desc']} {it['price']}元" for it in items)
        if comment: detail += "。" + comment
        tx_info = add_tx("income", total, f"工资结算单 #{ws_id}", "工资", detail[:500], worksheet_id=ws_id)
    return {"id": ws_id, "total": total, "tx": tx_info}

def add_goal(name, target):
    target = round(float(target), 2)
    if target <= 0: raise ValueError("target must be > 0")
    c = conn()
    cur = c.execute("INSERT INTO goals(ts,name,target) VALUES(?,?,?)", (now(), name, target))
    c.commit(); gid = cur.lastrowid; c.close()
    return {"id": gid}

def goal_add(gid, amount):
    amount = round(float(amount), 2)
    c = conn()
    g = c.execute("SELECT * FROM goals WHERE id=?", (gid,)).fetchone()
    if not g: c.close(); raise ValueError("goal not found")
    saved = round(g["saved"] + amount, 2)
    if saved < 0: saved = 0
    c.execute("UPDATE goals SET saved=? WHERE id=?", (saved, gid))
    c.commit(); c.close()
    return {"id": gid, "saved": saved}

def goal_done(gid):
    c = conn()
    c.execute("UPDATE goals SET done=1 WHERE id=?", (gid,))
    c.commit(); c.close()
    return {"id": gid, "done": True}

def dark_add(title, price=None, link="", note="", img=""):
    c = conn()
    cur = c.execute("INSERT INTO dark(ts,title,price,link,note,img) VALUES(?,?,?,?,?,?)",
        (now(), title, price, link, note, img))
    c.commit(); did = cur.lastrowid; c.close()
    return {"id": did}

def dark_list(include_done=False):
    c = conn()
    if include_done:
        rows = c.execute("SELECT * FROM dark ORDER BY id DESC")
    else:
        rows = c.execute("SELECT * FROM dark WHERE status='hidden' ORDER BY id DESC")
    out = [dict(r) for r in rows]
    c.close()
    return out

def dark_done(did):
    c = conn()
    c.execute("UPDATE dark SET status='done' WHERE id=?", (did,))
    c.commit(); c.close()
    return {"id": did, "status": "done"}

if __name__ == "__main__":
    init()
    print(json.dumps(state(), ensure_ascii=False, indent=2))
