"""VIKSITBHARAT AI starter backend: auth, Gemini chat, daily plan limits,
Dodo Payments checkout + webhook, and a private admin view."""
import os, json, sqlite3, hashlib, secrets, datetime as dt
from contextlib import closing
import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Depends, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel
from google import genai
from dodopayments import AsyncDodoPayments

load_dotenv()
SECRET = os.environ["JWT_SECRET"]
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").lower()
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
APP_URL = os.getenv("APP_URL", "http://localhost:8000")
LIMITS = {"free": 20, "pro": 1000, "business": 5000}  # per day; "unlimited" = fair-use cap
PRODUCTS = {os.getenv("DODO_PRODUCT_PRO"): "pro", os.getenv("DODO_PRODUCT_BUSINESS"): "business"}
SYSTEM = ("You are VIKSITBHARAT AI, a helpful assistant for reasoning, coding, writing and "
          "business. Answer clearly. Reply in the user's language (English, Hindi or Hinglish). "
          "If unsure, say so instead of guessing.")

gem = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
dodo = AsyncDodoPayments(bearer_token=os.environ["DODO_PAYMENTS_API_KEY"],
                         environment=os.getenv("DODO_PAYMENTS_ENVIRONMENT", "test_mode"),
                         webhook_key=os.environ["DODO_PAYMENTS_WEBHOOK_KEY"])
app = FastAPI()
DB = os.getenv("DB_PATH", "viksit.db")

def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c
with closing(db()) as c:
    c.executescript("""CREATE TABLE IF NOT EXISTS users(email TEXT PRIMARY KEY, salt TEXT, pw TEXT,
      plan TEXT DEFAULT 'free', created TEXT);
      CREATE TABLE IF NOT EXISTS usage(email TEXT, day TEXT, n INTEGER, PRIMARY KEY(email, day));""")
    c.commit()

def hash_pw(pw, salt): return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()
def today(): return dt.date.today().isoformat()
def token(email): return jwt.encode({"sub": email, "exp": dt.datetime.utcnow() + dt.timedelta(days=7)}, SECRET, "HS256")

def current_user(authorization: str = Header(default="")):
    try:
        email = jwt.decode(authorization.removeprefix("Bearer "), SECRET, ["HS256"])["sub"]
    except Exception:
        raise HTTPException(401, "Please log in again")
    with closing(db()) as c:
        u = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not u: raise HTTPException(401, "Unknown user")
    return u

class Auth(BaseModel): email: str; password: str
class Chat(BaseModel): messages: list[dict]
class Plan(BaseModel): plan: str

@app.post("/api/signup")
def signup(a: Auth):
    email = a.email.strip().lower()
    if "@" not in email or len(a.password) < 8: raise HTTPException(400, "Valid email and 8+ character password required")
    salt = secrets.token_hex(8)
    try:
        with closing(db()) as c:
            c.execute("INSERT INTO users VALUES(?,?,?,?,?)", (email, salt, hash_pw(a.password, salt), "free", today())); c.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Email already registered")
    return {"token": token(email), "plan": "free"}

@app.post("/api/login")
def login(a: Auth):
    email = a.email.strip().lower()
    with closing(db()) as c: u = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not u or u["pw"] != hash_pw(a.password, u["salt"]): raise HTTPException(401, "Wrong email or password")
    return {"token": token(email), "plan": u["plan"]}

@app.get("/api/me")
def me(u=Depends(current_user)):
    with closing(db()) as c:
        r = c.execute("SELECT n FROM usage WHERE email=? AND day=?", (u["email"], today())).fetchone()
    return {"email": u["email"], "plan": u["plan"], "used": r["n"] if r else 0,
            "limit": LIMITS[u["plan"]], "admin": u["email"] == ADMIN_EMAIL}

@app.post("/api/chat")
async def chat(body: Chat, u=Depends(current_user)):
    with closing(db()) as c:
        r = c.execute("SELECT n FROM usage WHERE email=? AND day=?", (u["email"], today())).fetchone()
        if (r["n"] if r else 0) >= LIMITS[u["plan"]]:
            raise HTTPException(429, "Daily limit reached. Upgrade your plan for more messages.")
    contents = [{"role": "user" if m.get("role") == "user" else "model",
                 "parts": [{"text": str(m.get("text", ""))[:4000]}]} for m in body.messages[-12:]]
    if not contents or contents[-1]["role"] != "user": raise HTTPException(400, "Last message must be from user")
    try:
        res = await gem.aio.models.generate_content(model=MODEL, contents=contents,
                                                    config={"system_instruction": SYSTEM, "max_output_tokens": 1500})
    except Exception:
        raise HTTPException(502, "The AI is busy. Please try again.")
    with closing(db()) as c:
        c.execute("INSERT INTO usage VALUES(?,?,1) ON CONFLICT(email,day) DO UPDATE SET n=n+1", (u["email"], today())); c.commit()
    return {"text": res.text or ""}

@app.post("/api/checkout")
async def checkout(p: Plan, u=Depends(current_user)):
    pid = next((k for k, v in PRODUCTS.items() if v == p.plan and k), None)
    if not pid: raise HTTPException(400, "Unknown plan")
    s = await dodo.checkout_sessions.create(product_cart=[{"product_id": pid, "quantity": 1}],
                                            customer={"email": u["email"]}, return_url=APP_URL)
    return {"url": s.checkout_url}

@app.post("/api/webhook")
async def webhook(req: Request):
    raw = (await req.body()).decode()
    h = {k: req.headers.get(k, "") for k in ("webhook-id", "webhook-timestamp", "webhook-signature")}
    try:
        dodo.webhooks.unwrap(raw, headers=h)
    except Exception:
        raise HTTPException(400, "Bad signature")
    ev = json.loads(raw); d = ev.get("data", {}); t = ev.get("type", "")
    email = (d.get("customer") or {}).get("email", "").lower()
    plan = PRODUCTS.get(d.get("product_id"))
    if not plan:
        plan = next((PRODUCTS.get(i.get("product_id")) for i in d.get("product_cart", []) or []), None)
    with closing(db()) as c:
        if plan and email and t in ("payment.succeeded", "subscription.active", "subscription.renewed"):
            c.execute("UPDATE users SET plan=? WHERE email=?", (plan, email))
        elif email and t in ("subscription.cancelled", "subscription.expired"):
            c.execute("UPDATE users SET plan='free' WHERE email=?", (email,))
        c.commit()
    return {"ok": True}

def admin_only(u=Depends(current_user)):
    if u["email"] != ADMIN_EMAIL: raise HTTPException(403, "Admin only")
    return u

@app.get("/api/admin/users")
def admin_users(_=Depends(admin_only)):
    with closing(db()) as c:
        rows = c.execute("""SELECT u.email,u.plan,u.created,COALESCE(SUM(x.n),0) AS messages
                            FROM users u LEFT JOIN usage x ON x.email=u.email GROUP BY u.email""").fetchall()
    return [dict(r) for r in rows]

@app.post("/api/admin/set-plan/{email}")
def admin_set(email: str, p: Plan, _=Depends(admin_only)):
    if p.plan not in LIMITS: raise HTTPException(400, "Unknown plan")
    with closing(db()) as c: c.execute("UPDATE users SET plan=? WHERE email=?", (p.plan, email.lower())); c.commit()
    return {"ok": True}

@app.get("/")
def home(): return FileResponse("static/index.html")
