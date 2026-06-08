"""KUN TARTIBI — BACKEND"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sqlite3, os, hashlib
from datetime import date, timedelta

app = FastAPI(title="Kun Tartibi API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DATABASE = os.getenv("DB_PATH", "kuntartibi.db")
PORT     = int(os.getenv("PORT", "8000"))

def hash_pw(pw): return hashlib.sha256(pw.strip().encode()).hexdigest()

def db():
    c = sqlite3.connect(DATABASE)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS app_accounts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            login        TEXT NOT NULL UNIQUE,
            password     TEXT NOT NULL,
            display_name TEXT DEFAULT '',
            is_active    INTEGER DEFAULT 1,
            is_admin     INTEGER DEFAULT 0,
            telegram_id  INTEGER DEFAULT 0,
            created_at   TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY,
            first_name TEXT DEFAULT '',
            last_name  TEXT DEFAULT '',
            username   TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            last_seen  TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS user_states (
            user_id    INTEGER PRIMARY KEY,
            state_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS plans (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            ptype       TEXT DEFAULT 'daily',
            title       TEXT NOT NULL,
            description TEXT DEFAULT '',
            plan_date   TEXT NOT NULL,
            status      TEXT DEFAULT 'pending',
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            updated_at  TEXT DEFAULT (datetime('now','localtime'))
        );
        """)
        # Migrations
        for col, typ in [("is_admin","INTEGER DEFAULT 0"), ("telegram_id","INTEGER DEFAULT 0")]:
            try: c.execute(f"ALTER TABLE app_accounts ADD COLUMN {col} {typ}")
            except: pass
        c.commit()

init_db()

# ── MODELLAR ─────────────────────────────────
class LoginIn(BaseModel):
    login:       str
    password:    str
    telegram_id: Optional[int] = 0

class RegisterIn(BaseModel):
    login:        str
    password:     str
    display_name: Optional[str] = ""
    telegram_id:  Optional[int] = 0

class AccountIn(BaseModel):
    login:        str
    password:     str
    display_name: Optional[str] = ""

class StateIn(BaseModel):
    user_id:    int
    state_json: str

class UserIn(BaseModel):
    id:         int
    first_name: str
    last_name:  Optional[str] = ""
    username:   Optional[str] = ""

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

def check_admin(admin_login: str):
    with db() as c:
        row = c.execute(
            "SELECT is_admin FROM app_accounts WHERE login=? AND is_active=1", (admin_login,)
        ).fetchone()
    if not row or not row["is_admin"]:
        raise HTTPException(403, detail="Ruxsat yo'q")

def rows(r): return [dict(x) for x in r]

# ── ASOSIY ───────────────────────────────────
@app.get("/")
def root():
    with db() as c:
        cnt = c.execute("SELECT COUNT(*) FROM app_accounts WHERE is_active=1").fetchone()[0]
    return {"status": "ok", "active_accounts": cnt}

# ── LOGIN ─────────────────────────────────────
@app.post("/api/login")
def login(d: LoginIn):
    with db() as c:
        row = c.execute(
            "SELECT * FROM app_accounts WHERE login=?", (d.login.strip(),)
        ).fetchone()
    if not row:
        raise HTTPException(401, detail="Login topilmadi")
    if not row["is_active"]:
        raise HTTPException(403, detail="Akkaunt bloklangan! Admin bilan bog'laning.")
    if row["password"] != hash_pw(d.password):
        raise HTTPException(401, detail="Parol noto'g'ri")
    # Telegram ID ni bog'lash
    if d.telegram_id and d.telegram_id != 0:
        with db() as c:
            c.execute("UPDATE app_accounts SET telegram_id=? WHERE login=?",
                      (d.telegram_id, d.login.strip()))
            c.commit()
    return {
        "ok":           True,
        "login":        row["login"],
        "display_name": row["display_name"] or row["login"],
        "is_admin":     bool(row["is_admin"]),
        "account_id":   row["id"]
    }

@app.post("/api/register")
def register(d: RegisterIn):
    if not d.login.strip() or not d.password.strip():
        raise HTTPException(400, detail="Login va parol kerak")
    with db() as c:
        try:
            c.execute(
                "INSERT INTO app_accounts (login,password,display_name,telegram_id) VALUES (?,?,?,?)",
                (d.login.strip(), hash_pw(d.password), d.display_name or d.login, d.telegram_id or 0)
            )
            c.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(400, detail="Bu login allaqachon band!")
    return {"ok": True}

@app.post("/api/bootstrap")
def bootstrap(d: AccountIn):
    with db() as c:
        cnt = c.execute("SELECT COUNT(*) FROM app_accounts").fetchone()[0]
        if cnt > 0:
            raise HTTPException(400, detail="Akkauntlar allaqachon mavjud!")
        c.execute("INSERT INTO app_accounts (login,password,display_name,is_admin) VALUES (?,?,?,1)",
                  (d.login.strip(), hash_pw(d.password), d.display_name or d.login))
        c.commit()
    return {"ok": True, "message": f"Admin yaratildi: {d.login}"}

# ── STATE ─────────────────────────────────────
@app.post("/api/state")
def save_state(s: StateIn):
    with db() as c:
        c.execute("""
            INSERT INTO user_states (user_id,state_json,updated_at) VALUES (?,?,datetime('now','localtime'))
            ON CONFLICT(user_id) DO UPDATE SET state_json=excluded.state_json,updated_at=datetime('now','localtime')
        """, (s.user_id, s.state_json))
        c.commit()
    return {"ok": True}

@app.get("/api/state")
def get_state(user_id: int):
    with db() as c:
        row = c.execute("SELECT * FROM user_states WHERE user_id=?", (user_id,)).fetchone()
    if not row: raise HTTPException(404)
    return dict(row)

# ── USERS ─────────────────────────────────────
@app.post("/api/users")
def upsert_user(u: UserIn):
    with db() as c:
        c.execute("""
            INSERT INTO users (id,first_name,last_name,username) VALUES (?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET first_name=excluded.first_name,
            last_name=excluded.last_name,username=excluded.username,
            last_seen=datetime('now','localtime')
        """, (u.id, u.first_name, u.last_name or "", u.username or ""))
        c.commit()
    return {"ok": True}

@app.get("/api/check_admin")
def check_admin_status(user_id: int):
    return {"is_admin": False}

# ── ADMIN ─────────────────────────────────────
@app.get("/admin/accounts")
def get_accounts(admin_login: str, search: Optional[str] = None):
    check_admin(admin_login)
    with db() as c:
        q = "SELECT * FROM app_accounts"
        params = []
        if search:
            q += " WHERE (login LIKE ? OR display_name LIKE ?)"
            params = [f"%{search}%", f"%{search}%"]
        q += " ORDER BY is_active DESC, created_at DESC"
        return rows(c.execute(q, params).fetchall())

@app.post("/admin/accounts")
def add_account(data: AccountIn, admin_login: str):
    check_admin(admin_login)
    with db() as c:
        try:
            c.execute("INSERT INTO app_accounts (login,password,display_name) VALUES (?,?,?)",
                      (data.login.strip(), hash_pw(data.password), data.display_name or data.login))
            c.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(400, "Bu login allaqachon mavjud")
    return {"ok": True}

@app.delete("/admin/accounts/{acc_id}")
def block_account(acc_id: int, admin_login: str):
    check_admin(admin_login)
    with db() as c:
        acc = c.execute("SELECT is_admin FROM app_accounts WHERE id=?", (acc_id,)).fetchone()
        if acc and acc["is_admin"]:
            raise HTTPException(400, "Admin akkauntni bloklash mumkin emas!")
        c.execute("UPDATE app_accounts SET is_active=0 WHERE id=?", (acc_id,))
        c.commit()
    return {"ok": True}

@app.put("/admin/accounts/{acc_id}/restore")
def restore_account(acc_id: int, admin_login: str):
    check_admin(admin_login)
    with db() as c:
        c.execute("UPDATE app_accounts SET is_active=1 WHERE id=?", (acc_id,))
        c.commit()
    return {"ok": True}

@app.get("/admin/stats")
def admin_stats(admin_login: str):
    check_admin(admin_login)
    with db() as c:
        total   = c.execute("SELECT COUNT(*) FROM app_accounts").fetchone()[0]
        active  = c.execute("SELECT COUNT(*) FROM app_accounts WHERE is_active=1").fetchone()[0]
        blocked = total - active
        linked  = c.execute("SELECT COUNT(*) FROM app_accounts WHERE telegram_id > 0").fetchone()[0]
        states  = c.execute("SELECT COUNT(*) FROM user_states").fetchone()[0]
    return {
        "total": total, "active": active,
        "blocked": blocked, "linked": linked, "states": states
    }

@app.get("/admin/user_state")
def admin_user_state(admin_login: str, account_id: int):
    """Foydalanuvchining to'liq haftalik jadvalini olish"""
    check_admin(admin_login)
    with db() as c:
        acc = c.execute(
            "SELECT telegram_id, login, display_name FROM app_accounts WHERE id=?", (account_id,)
        ).fetchone()
        if not acc:
            raise HTTPException(404, "Akkaunt topilmadi")
        tg_id = acc["telegram_id"]
        if not tg_id or tg_id == 0:
            raise HTTPException(404, f"'{acc['login']}' hali ilovaga Telegram orqali kirmagan")
        row = c.execute("SELECT state_json FROM user_states WHERE user_id=?", (tg_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Foydalanuvchi hali hech narsa saqlamagan")
    return {"state_json": row["state_json"]}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT)
