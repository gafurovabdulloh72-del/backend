"""
╔══════════════════════════════════════════════════╗
║     KUN TARTIBI — BACKEND (FastAPI + SQLite)     ║
╚══════════════════════════════════════════════════╝
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sqlite3, os, hashlib
from datetime import datetime, date, timedelta

app = FastAPI(title="Kun Tartibi API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════
# ⚙️  SOZLAMALAR
# ═══════════════════════════════════════════════
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DATABASE  = os.getenv("DB_PATH", "kuntartibi.db")
PORT      = int(os.getenv("PORT", "8000"))

def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.strip().encode()).hexdigest()

# ═══════════════════════════════════════════════
# 🗄  DATABASE
# ═══════════════════════════════════════════════
def db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY,
            first_name TEXT    NOT NULL DEFAULT '',
            last_name  TEXT    DEFAULT '',
            username   TEXT    DEFAULT '',
            created_at TEXT    DEFAULT (datetime('now','localtime')),
            last_seen  TEXT    DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS user_states (
            user_id    INTEGER PRIMARY KEY,
            state_json TEXT    NOT NULL DEFAULT '{}',
            updated_at TEXT    DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS app_accounts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            login        TEXT    NOT NULL UNIQUE,
            password     TEXT    NOT NULL,
            display_name TEXT    DEFAULT '',
            is_active    INTEGER DEFAULT 1,
            created_at   TEXT    DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS plans (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            ptype       TEXT    NOT NULL DEFAULT 'daily',
            title       TEXT    NOT NULL,
            description TEXT    DEFAULT '',
            plan_date   TEXT    NOT NULL,
            status      TEXT    DEFAULT 'pending',
            created_at  TEXT    DEFAULT (datetime('now','localtime')),
            updated_at  TEXT    DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """)
        c.commit()

init_db()

# ═══════════════════════════════════════════════
# 📦  MODELLAR
# ═══════════════════════════════════════════════
class StateIn(BaseModel):
    user_id:    int
    state_json: str

class UserIn(BaseModel):
    id:         int
    first_name: str
    last_name:  Optional[str] = ""
    username:   Optional[str] = ""

class LoginIn(BaseModel):
    login:    str
    password: str

class AccountIn(BaseModel):
    login:        str
    password:     str
    display_name: Optional[str] = ""

class PlanIn(BaseModel):
    user_id:     int
    ptype:       str = "daily"
    title:       str
    description: Optional[str] = ""
    plan_date:   str

class PlanUpdate(BaseModel):
    title:       Optional[str] = None
    description: Optional[str] = None
    status:      Optional[str] = None

# ═══════════════════════════════════════════════
# 🔐  YORDAMCHI
# ═══════════════════════════════════════════════
def require_admin(admin_id: int):
    if admin_id != ADMIN_ID:
        raise HTTPException(403, detail="Ruxsat yo'q")

def row_list(rows):
    return [dict(r) for r in rows]

# ═══════════════════════════════════════════════
# 🌐  ENDPOINTLAR
# ═══════════════════════════════════════════════

@app.get("/")
def root():
    return {"status": "ok", "admin_configured": ADMIN_ID != 0}

@app.get("/api/check_admin")
def check_admin_status(user_id: int):
    return {"is_admin": user_id == ADMIN_ID}

@app.post("/api/bootstrap")
def bootstrap(data: AccountIn):
    {
  "login": "941434499",
  "password": "Abdulloh1222",
  "display_name": "Admin"
}
    with db() as c:
        count = c.execute("SELECT COUNT(*) FROM app_accounts").fetchone()[0]
        if count > 0:
            raise HTTPException(400, detail="Akkauntlar allaqachon mavjud! /admin/accounts dan foydalaning.")
        c.execute(
            "INSERT INTO app_accounts (login, password, display_name) VALUES (?,?,?)",
            (data.login.strip(), hash_pw(data.password), data.display_name or data.login)
        )
        c.commit()
    return {"ok": True, "message": f"✅ Birinchi akkaunt yaratildi: {data.login}"}

# ─── LOGIN ────────────────────────────────────
@app.post("/api/login")
def login(data: LoginIn):
    with db() as c:
        row = c.execute(
            "SELECT * FROM app_accounts WHERE login=? AND is_active=1",
            (data.login.strip(),)
        ).fetchone()
        if not row:
            raise HTTPException(401, detail="Login topilmadi")
        if row["password"] != hash_pw(data.password):
            raise HTTPException(401, detail="Parol noto'g'ri")
        return {
            "ok": True,
            "display_name": row["display_name"] or row["login"],
            "login": row["login"]
        }

# ─── State ────────────────────────────────────
@app.post("/api/state")
def save_state(s: StateIn):
    with db() as c:
        c.execute("""
            INSERT INTO user_states (user_id, state_json, updated_at)
            VALUES (?, ?, datetime('now','localtime'))
            ON CONFLICT(user_id) DO UPDATE SET
                state_json = excluded.state_json,
                updated_at = datetime('now','localtime')
        """, (s.user_id, s.state_json))
        c.commit()
    return {"ok": True}

@app.get("/api/state")
def get_state(user_id: int):
    with db() as c:
        row = c.execute(
            "SELECT * FROM user_states WHERE user_id=?", (user_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "State topilmadi")
        return dict(row)

# ─── Foydalanuvchi ────────────────────────────
@app.post("/api/users")
def upsert_user(u: UserIn):
    with db() as c:
        c.execute("""
            INSERT INTO users (id, first_name, last_name, username)
            VALUES (?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                first_name = excluded.first_name,
                last_name  = excluded.last_name,
                username   = excluded.username,
                last_seen  = datetime('now','localtime')
        """, (u.id, u.first_name, u.last_name or "", u.username or ""))
        c.commit()
    return {"ok": True}

@app.get("/api/me")
def get_me(user_id: int):
    with db() as c:
        row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Foydalanuvchi topilmadi")
        data = dict(row)
        data["is_admin"] = (user_id == ADMIN_ID)
        return data

# ─── Rejalar ──────────────────────────────────
@app.get("/api/plans")
def get_plans(user_id: int, date: Optional[str] = None, ptype: Optional[str] = None):
    with db() as c:
        q = "SELECT * FROM plans WHERE user_id=?"
        p = [user_id]
        if date:  q += " AND plan_date=?"; p.append(date)
        if ptype: q += " AND ptype=?";     p.append(ptype)
        q += " ORDER BY created_at DESC"
        return row_list(c.execute(q, p).fetchall())

@app.get("/api/plans/week")
def get_week_plans(user_id: int, week_start: Optional[str] = None):
    if not week_start:
        today = date.today()
        start = today - timedelta(days=today.weekday())
        week_start = start.isoformat()
    week_end = (date.fromisoformat(week_start) + timedelta(days=6)).isoformat()
    with db() as c:
        rows = c.execute("""
            SELECT * FROM plans WHERE user_id=? AND plan_date BETWEEN ? AND ?
            ORDER BY plan_date ASC, created_at ASC
        """, (user_id, week_start, week_end)).fetchall()
        return row_list(rows)

@app.get("/api/history")
def get_history(user_id: int):
    with db() as c:
        rows = c.execute("""
            SELECT * FROM plans WHERE user_id=?
            ORDER BY plan_date DESC, created_at DESC
        """, (user_id,)).fetchall()
        return row_list(rows)

@app.post("/api/plans")
def create_plan(plan: PlanIn):
    with db() as c:
        cur = c.execute("""
            INSERT INTO plans (user_id, ptype, title, description, plan_date)
            VALUES (?,?,?,?,?)
        """, (plan.user_id, plan.ptype, plan.title, plan.description, plan.plan_date))
        c.commit()
        row = c.execute("SELECT * FROM plans WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)

@app.put("/api/plans/{plan_id}")
def update_plan(plan_id: int, upd: PlanUpdate, user_id: int):
    with db() as c:
        exists = c.execute("SELECT id FROM plans WHERE id=? AND user_id=?", (plan_id, user_id)).fetchone()
        if not exists: raise HTTPException(404, "Reja topilmadi")
        sets, params = ["updated_at=datetime('now','localtime')"], []
        if upd.title       is not None: sets.append("title=?");       params.append(upd.title)
        if upd.description is not None: sets.append("description=?"); params.append(upd.description)
        if upd.status      is not None: sets.append("status=?");      params.append(upd.status)
        params += [plan_id, user_id]
        c.execute(f"UPDATE plans SET {','.join(sets)} WHERE id=? AND user_id=?", params)
        c.commit()
        return dict(c.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone())

@app.delete("/api/plans/{plan_id}")
def delete_plan(plan_id: int, user_id: int):
    with db() as c:
        res = c.execute("DELETE FROM plans WHERE id=? AND user_id=?", (plan_id, user_id))
        c.commit()
        if res.rowcount == 0: raise HTTPException(404, "Reja topilmadi")
        return {"ok": True}

# ─── Admin ────────────────────────────────────
@app.get("/admin/users")
def admin_users(admin_id: int):
    require_admin(admin_id)
    with db() as c:
        rows = c.execute("""
            SELECT u.*,
                   COUNT(p.id) AS total,
                   SUM(p.status='done') AS done,
                   SUM(p.status='pending') AS pending,
                   MAX(p.plan_date) AS last_plan_date
            FROM users u
            LEFT JOIN plans p ON u.id = p.user_id
            GROUP BY u.id ORDER BY u.last_seen DESC
        """).fetchall()
        return row_list(rows)

@app.get("/admin/plans")
def admin_plans(admin_id: int, user_id: Optional[int] = None, plan_date: Optional[str] = None):
    require_admin(admin_id)
    with db() as c:
        q = "SELECT p.*, u.first_name, u.username FROM plans p JOIN users u ON p.user_id=u.id WHERE 1=1"
        params = []
        if user_id:    q += " AND p.user_id=?";    params.append(user_id)
        if plan_date:  q += " AND p.plan_date=?";  params.append(plan_date)
        q += " ORDER BY p.created_at DESC LIMIT 300"
        return row_list(c.execute(q, params).fetchall())

@app.get("/admin/stats")
def admin_stats(admin_id: int):
    require_admin(admin_id)
    with db() as c:
        users  = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total  = c.execute("SELECT COUNT(*) FROM plans").fetchone()[0]
        done   = c.execute("SELECT COUNT(*) FROM plans WHERE status='done'").fetchone()[0]
        accounts = c.execute("SELECT COUNT(*) FROM app_accounts WHERE is_active=1").fetchone()[0]
        return {
            "users": users,
            "total_plans": total,
            "done_plans": done,
            "accounts": accounts,
            "completion_pct": round(done/total*100) if total else 0
        }

# ─── Admin: Akkauntlar ────────────────────────
@app.get("/admin/accounts")
def get_accounts(admin_id: int):
    require_admin(admin_id)
    with db() as c:
        rows = c.execute(
            "SELECT id, login, display_name, is_active, created_at FROM app_accounts ORDER BY created_at DESC"
        ).fetchall()
        return row_list(rows)

@app.post("/admin/accounts")
def add_account(data: AccountIn, admin_id: int):
    require_admin(admin_id)
    with db() as c:
        try:
            c.execute("""
                INSERT INTO app_accounts (login, password, display_name)
                VALUES (?,?,?)
            """, (data.login.strip(), hash_pw(data.password), data.display_name or data.login))
            c.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(400, "Bu login allaqachon mavjud")
    return {"ok": True}

@app.delete("/admin/accounts/{acc_id}")
def delete_account(acc_id: int, admin_id: int):
    require_admin(admin_id)
    with db() as c:
        c.execute("DELETE FROM app_accounts WHERE id=?", (acc_id,))
        c.commit()
    return {"ok": True}

# ═══════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
