import sqlite3, re, json, os, secrets
from datetime import date, timedelta
from functools import wraps
from flask import Flask, request, redirect, session, flash, get_flashed_messages, url_for, g
from werkzeug.security import generate_password_hash as gh, check_password_hash as ch
from itsdangerous import URLSafeTimedSerializer
from markupsafe import escape as E

app = Flask(__name__)
if not os.path.exists(".secret"): open(".secret", "w").write(secrets.token_hex(32))
app.secret_key = os.environ.get("SECRET") or open(".secret").read()
app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True)
tok = URLSafeTimedSerializer(app.secret_key)
DB = "brightloop.db"
STEP = {"daily": 1, "weekly": 7, "monthly": 30, "yearly": 365}
FLOW = {"Draft": ["Quotation"], "Quotation": ["Confirmed"], "Confirmed": ["Active"], "Active": ["Closed"]}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, pw TEXT NOT NULL, role TEXT NOT NULL, name TEXT);
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, name TEXT, type TEXT, price REAL, cost REAL, notes TEXT);
CREATE TABLE IF NOT EXISTS variants(id INTEGER PRIMARY KEY, product_id INT, attr TEXT, val TEXT, extra REAL);
CREATE TABLE IF NOT EXISTS taxes(id INTEGER PRIMARY KEY, name TEXT, rate REAL);
CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY, name TEXT, price REAL, period TEXT, min_qty INT, start TEXT, end TEXT, auto_close INT, closable INT, pausable INT, renewable INT);
CREATE TABLE IF NOT EXISTS templates(id INTEGER PRIMARY KEY, name TEXT, plan_id INT, lines TEXT, valid_days INT);
CREATE TABLE IF NOT EXISTS subs(id INTEGER PRIMARY KEY, number TEXT UNIQUE, customer_id INT, plan_id INT, start TEXT, expiry TEXT, terms TEXT, status TEXT, next_bill TEXT);
CREATE TABLE IF NOT EXISTS sub_lines(id INTEGER PRIMARY KEY, sub_id INT, product_id INT, variant_id INT, qty INT, price REAL, tax_id INT);
CREATE TABLE IF NOT EXISTS discounts(id INTEGER PRIMARY KEY, name TEXT, kind TEXT, value REAL, min_amount REAL, min_qty INT, start TEXT, end TEXT, max_uses INT, used INT DEFAULT 0, product_id INT);
CREATE TABLE IF NOT EXISTS invoices(id INTEGER PRIMARY KEY, number TEXT UNIQUE, sub_id INT, customer_id INT, period TEXT, status TEXT, lines TEXT, subtotal REAL, discount REAL, tax REAL, total REAL, due TEXT, UNIQUE(sub_id, period));
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, invoice_id INT, method TEXT, amount REAL, date TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS ix_inv ON invoices(status, due); CREATE INDEX IF NOT EXISTS ix_sub ON subs(status, next_bill);
"""

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
    return g.db
@app.teardown_appcontext
def close(_): 
    d = g.pop("db", None)
    if d: d.close()
def q(sql, a=()): return db().execute(sql, a).fetchall()
def one(sql, a=()): r = q(sql, a); return r[0] if r else None
def ex(sql, a=()):
    c = db().execute(sql, a); db().commit(); return c.lastrowid

def init():
    c = sqlite3.connect(DB); c.executescript(SCHEMA)
    if not c.execute("SELECT 1 FROM users").fetchone():
        c.execute("INSERT INTO users(email,pw,role,name) VALUES('admin@brightloop.com',?,'admin','Admin')", (gh("Admin@12345"),))
        c.execute("INSERT INTO taxes(name,rate) VALUES('GST 18%',18)")
        c.execute("INSERT INTO products(name,type,price,cost,notes) VALUES('Brightloop CRM','Software',1000,300,'Core CRM')")
        c.execute("INSERT INTO variants(product_id,attr,val,extra) VALUES(1,'Brand','Odoo',560)")
        c.execute("INSERT INTO plans VALUES(NULL,'CRM Monthly',1000,'monthly',1,'2026-01-01','2030-12-31',0,1,1,1)")
        c.execute("INSERT INTO templates VALUES(NULL,'Standard CRM Offer',1,?,30)", (json.dumps([{"product_id": 1, "qty": 5}]),))
    c.commit(); c.close()

# ---------- helpers ----------
def me(): return one("SELECT * FROM users WHERE id=?", (session["uid"],)) if "uid" in session else None
def need(*roles):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            u = me()
            if not u: return redirect("/login")
            if roles and u["role"] not in roles: return page("Denied", "<p>Access denied for your role.</p>"), 403
            return f(*a, **k)
        return w
    return deco
def pw_ok(p): return len(p) > 8 and re.search("[A-Z]", p) and re.search("[a-z]", p) and re.search(r"[^A-Za-z0-9]", p)
def money(x): return f"{x:,.2f}"
def num(v, d=0.0):
    try: return float(v)
    except (TypeError, ValueError): return d
def page(title, body):
    h = _page(title, body)
    return re.sub(r"(<form[^>]*method=post[^>]*>)", lambda m: m.group(1) + '<input type=hidden name=_csrf value="%s">' % csrf(), h)
def _page(title, body):
    u = me(); nav = ""
    if u:
        links = [("/", "Dashboard"), ("/subs", "Subscriptions"), ("/invoices", "Invoices")]
        if u["role"] != "customer": links += [("/payments", "Payments"), ("/products", "Products"), ("/plans", "Plans")]
        if u["role"] == "admin": links += [("/discounts", "Discounts"), ("/taxes", "Taxes"), ("/staff", "Staff")]
        nav = "".join(f'<a href="{h}">{t}</a>' for h, t in links) + f'<a href="/logout">Logout ({E(u["role"])})</a>'
    fl = "".join(f'<div class="fl">{E(m)}</div>' for m in get_flashed_messages())
    return f"""<!doctype html><meta name=viewport content="width=device-width,initial-scale=1"><title>{E(title)}</title>
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=VT323&display=swap" rel=stylesheet>
<style>:root{{--g:#5d9b3a;--gd:#3f6e26;--st:#c6c6c6;--sd:#555;--dirt:#6b4a2b}}
*{{border-radius:0!important}}body{{font:20px/1.25 VT323,'Courier New',monospace;margin:0;color:#222;background:var(--dirt);
background-image:linear-gradient(45deg,#00000014 25%,transparent 25%,transparent 75%,#00000014 75%),linear-gradient(45deg,#00000014 25%,transparent 25%,transparent 75%,#00000014 75%);background-size:32px 32px;background-position:0 0,16px 16px}}
nav{{background:var(--g);border-bottom:6px solid var(--gd);display:flex;flex-wrap:wrap;gap:6px;padding:8px;align-items:center}}
.logo{{font:12px 'Press Start 2P',monospace;color:#fff;text-shadow:2px 2px #000;margin-right:10px}}
nav a{{color:#fff;text-decoration:none;padding:4px 10px;background:var(--gd);border:3px solid;border-color:#7cc455 #2a4a19 #2a4a19 #7cc455;text-shadow:1px 1px #000}}
nav a:hover{{background:#2f5a1c}}main{{max-width:1000px;margin:auto;padding:14px}}
h2,h3{{font:14px/1.6 'Press Start 2P',monospace;color:#fff;text-shadow:3px 3px #000}}
.card,form.card{{background:var(--st);border:4px solid;border-color:#fff var(--sd) var(--sd) #fff;padding:12px;margin:12px 0;overflow-x:auto;box-shadow:4px 4px 0 #0006}}
table{{width:100%;border-collapse:collapse}}th{{font:10px 'Press Start 2P',monospace;background:#8b8b8b;color:#fff;text-shadow:1px 1px #000}}
td,th{{padding:6px;border:2px solid #8b8b8b;text-align:left}}
input,select{{padding:6px;margin:3px 0;border:3px solid;border-color:#373737 #fff #fff #373737;background:#8b8b8b;color:#000;font:inherit;max-width:100%}}
input:focus,select:focus{{outline:3px solid #ffd83d}}input[type=checkbox]{{width:18px;height:18px}}
button,.b{{background:var(--g);color:#fff;font:inherit;border:3px solid;border-color:#7cc455 #2a4a19 #2a4a19 #7cc455;padding:4px 12px;cursor:pointer;text-decoration:none;display:inline-block;text-shadow:2px 2px #000;margin:2px}}
button:hover,.b:hover{{background:#4a8a2a}}button:active,.b:active{{border-color:#2a4a19 #7cc455 #7cc455 #2a4a19}}
.fl{{background:#ffd83d;border:4px solid #000;padding:8px;margin:10px 0}}.g{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}}
.k{{font:18px 'Press Start 2P',monospace;margin-top:8px}}.tag{{background:#3f6e26;color:#fff;padding:1px 8px;border:2px solid #000}}a{{color:#1a3fb0}}</style>
<nav><b class=logo>⛏ BRIGHTLOOP</b>{nav}</nav><main>{fl}<h2>{E(title)}</h2>{body}</main>"""
def table(head, rows): return "<div class=card><table><tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr>" + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</table></div>"
def form(action, fields, btn="Save"):
    h = f'<form class=card method=post action="{action}">'
    for n, label, *t in fields: h += f'<label>{label}<br><input name={n} type={t[0] if t else "text"} required></label><br>'
    return h + f"<button>{btn}</button></form>"

# ---------- security + helpers ----------
def csrf():
    if "csrf" not in session: session["csrf"] = secrets.token_hex(16)
    return session["csrf"]
MUT = re.compile(r"^/(subs/\d+/|billing/run|invoice/\d+/|del/|sub/\d+/)")
@app.before_request
def guard():
    t = session.get("csrf")
    bad = (request.method == "POST" and (not t or request.form.get("_csrf") != t)) or (request.method == "GET" and MUT.match(request.path) and (not t or request.args.get("t") != t))
    if bad: flash("Session expired, please retry"); return redirect("/login" if "uid" not in session else "/")
def pgnum():
    p = request.args.get("p", "1"); return int(p) if p.isdigit() and int(p) > 0 else 1
def pager(pg, base, n, st=None):
    s = f"&status={E(st)}" if st else ""
    return "<div>" + (f'<a class=b href="{base}?p={pg-1}{s}">◀ Prev</a>' if pg > 1 else "") + f" Page {pg} " + (f'<a class=b href="{base}?p={pg+1}{s}">Next ▶</a>' if n == 50 else "") + "</div>"
def ops(t, i):
    u = me()
    return f'<a href="/edit/{t}/{i}">✎</a> <a href="/del/{t}/{i}?t={csrf()}" onclick="return confirm(\'Delete?\')">✖</a>' if u and u["role"] == "admin" else ""
def actions(s, role):
    a = [(n, n) for n in FLOW.get(s["status"], [])] if role != "customer" else []
    if s["status"] == "Active" and s["pausable"]: a.append(("pause", "Pause"))
    if s["status"] == "Paused": a.append(("resume", "Resume"))
    if s["status"] in ("Active", "Paused", "Confirmed") and s["closable"] and "Closed" not in [x for x, _ in a]: a.append(("close", "Close early"))
    if s["renewable"] and s["status"] in ("Active", "Closed"): a.append(("renew", "Renew"))
    return a

# ---------- auth ----------
def send_mail(to, subj, body):
    h = os.environ.get("SMTP_HOST")
    if not h: print("\n[MAIL -> %s] %s\n%s\n" % (to, subj, body)); return   # no SMTP set: prints to console
    import smtplib; from email.message import EmailMessage
    m = EmailMessage(); m["From"] = os.environ.get("SMTP_USER"); m["To"] = to; m["Subject"] = subj; m.set_content(body)
    try:
        with smtplib.SMTP(h, int(os.environ.get("SMTP_PORT", 587))) as c: c.starttls(); c.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"]); c.send_message(m)
    except Exception as x: print("Mail failed:", x)

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        e, p = request.form["email"].strip().lower(), request.form["pw"]
        if not re.match(r"[^@\s]+@[^@\s]+\.\w+$", e): flash("Invalid email")
        elif not pw_ok(p): flash("Password: 9+ chars, upper, lower and a special character")
        elif one("SELECT 1 FROM users WHERE email=?", (e,)): flash("Email already registered")
        else:
            session["uid"] = ex("INSERT INTO users(email,pw,role,name) VALUES(?,?,'customer',?)", (e, gh(p), request.form["name"]))
            return redirect("/")
    return page("Sign up", form("/signup", [("name", "Name"), ("email", "Email", "email"), ("pw", "Password", "password")], "Create account") + '<a href="/login">Login</a>')
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = one("SELECT * FROM users WHERE email=?", (request.form["email"].strip().lower(),))
        if u and ch(u["pw"], request.form["pw"]): session["uid"] = u["id"]; return redirect("/")
        flash("Wrong email or password")
    return page("Login", form("/login", [("email", "Email", "email"), ("pw", "Password", "password")], "Login") + '<a href="/signup">Sign up</a> | <a href="/forgot">Forgot password?</a>')
@app.route("/logout")
def logout(): session.clear(); return redirect("/login")
@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        e = request.form["email"].strip().lower()
        if one("SELECT 1 FROM users WHERE email=?", (e,)):
            link = request.host_url + "reset/" + tok.dumps(e, salt="reset")
            send_mail(e, "Reset your password", "Reset link (valid 1 hour): " + link)
        flash("If the email is registered, a reset link has been sent.")
    return page("Forgot password", form("/forgot", [("email", "Registered email", "email")], "Send reset link"))
@app.route("/reset/<t>", methods=["GET", "POST"])
def reset(t):
    try: e = tok.loads(t, salt="reset", max_age=3600)
    except Exception: return page("Reset", "<p>Link invalid or expired.</p>")
    if request.method == "POST":
        if pw_ok(request.form["pw"]): ex("UPDATE users SET pw=? WHERE email=?", (gh(request.form["pw"]), e)); flash("Password updated"); return redirect("/login")
        flash("Password too weak")
    return page("New password", form(request.path, [("pw", "New password", "password")]))
@app.route("/staff", methods=["GET", "POST"])
@need("admin")
def staff():
    if request.method == "POST":
        e, p = request.form["email"].strip().lower(), request.form["pw"]
        if not pw_ok(p): flash("Weak password")
        elif one("SELECT 1 FROM users WHERE email=?", (e,)): flash("Email exists")
        else: ex("INSERT INTO users(email,pw,role,name) VALUES(?,?,'staff',?)", (e, gh(p), request.form["name"])); flash("Staff added")
    rows = [(E(u["name"] or ""), E(u["email"]), u["role"]) for u in q("SELECT * FROM users ORDER BY role")]
    return page("Staff", form("/staff", [("name", "Name"), ("email", "Email", "email"), ("pw", "Password", "password")], "Add staff") + table(["Name", "Email", "Role"], rows))

# ---------- catalog ----------
@app.route("/products", methods=["GET", "POST"])
@need("admin", "staff")
def products():
    u = me()
    if request.method == "POST" and u["role"] == "admin":
        pid = ex("INSERT INTO products(name,type,price,cost,notes) VALUES(?,?,?,?,?)", tuple(request.form[k] for k in ("name", "type")) + (num(request.form["price"]), num(request.form["cost"]), request.form["notes"]))
        for v in filter(None, request.form["variants"].split(",")):  # Brand:Odoo:560, Brand:Zoho:300
            try: a, val, x = v.strip().split(":"); ex("INSERT INTO variants(product_id,attr,val,extra) VALUES(?,?,?,?)", (pid, a, val, num(x)))
            except ValueError: flash("Skipped bad variant: " + v)
    rows = [(f'{E(p["name"])} {ops("products", p["id"])}', p["type"], money(p["price"]), money(p["cost"]), E(", ".join(f'{v["attr"]}:{v["val"]} (+{v["extra"]:g})' for v in q("SELECT * FROM variants WHERE product_id=?", (p["id"],))))) for p in q("SELECT * FROM products")]
    f = form("/products", [("name", "Name"), ("type", "Type"), ("price", "Sales price", "number"), ("cost", "Cost price", "number"), ("notes", "Notes"), ("variants", "Variants (Brand:Odoo:560, ...)")], "Add product").replace(" required>", ">") if u["role"] == "admin" else ""
    return page("Products", f + table(["Name", "Type", "Price", "Cost", "Variants"], rows))
@app.route("/plans", methods=["GET", "POST"])
@need("admin", "staff")
def plans():
    u = me()
    if request.method == "POST" and u["role"] == "admin":
        r = request.form
        if r["period"] not in STEP: flash("Bad period")
        else: ex("INSERT INTO plans VALUES(NULL,?,?,?,?,?,?,?,?,?,?)", (r["name"], num(r["price"]), r["period"], int(num(r["min_qty"], 1)), r["start"], r["end"], "auto" in r, "closable" in r, "pausable" in r, "renewable" in r))
    rows = [(f'{E(p["name"])} {ops("plans", p["id"])}', money(p["price"]), p["period"], p["min_qty"], f'{p["start"]} → {p["end"]}', "auto-close" if p["auto_close"] else "manual", "✔" if p["closable"] else "", "✔" if p["pausable"] else "", "✔" if p["renewable"] else "") for p in q("SELECT * FROM plans")]
    f = """<form class=card method=post>Name <input name=name required> Price <input name=price type=number step=any required>
    Period <select name=period><option>daily<option>weekly<option selected>monthly<option>yearly</select> Min qty <input name=min_qty type=number value=1>
    From <input name=start type=date required> To <input name=end type=date required><br>
    <label><input type=checkbox name=auto> auto-close</label> <label><input type=checkbox name=closable> closable early</label>
    <label><input type=checkbox name=pausable> pausable</label> <label><input type=checkbox name=renewable> renewable</label> <button>Add plan</button></form>""" if u["role"] == "admin" else ""
    return page("Plans", f + table(["Plan", "Price", "Bills", "Min qty", "Available", "End", "Closable", "Pausable", "Renewable"], rows))
@app.route("/discounts", methods=["GET", "POST"])
@need("admin")
def discounts():
    if request.method == "POST":
        r = request.form
        ex("INSERT INTO discounts(name,kind,value,min_amount,min_qty,start,end,max_uses,product_id) VALUES(?,?,?,?,?,?,?,?,?)", (r["name"], r["kind"], num(r["value"]), num(r["min_amount"]), int(num(r["min_qty"])), r["start"], r["end"], int(num(r["max_uses"], 999999)), int(r["product_id"]) if r["product_id"].isdigit() else None))
    rows = [(f'{E(d["name"])} {ops("discounts", d["id"])}', d["kind"], d["value"], d["min_amount"], d["min_qty"], f'{d["start"]} → {d["end"]}', f'{d["used"]}/{d["max_uses"]}', d["product_id"] or "whole sub") for d in q("SELECT * FROM discounts")]
    f = """<form class=card method=post>Name <input name=name required> <select name=kind><option value=percent>percent<option value=fixed>fixed</select>
    Value <input name=value type=number step=any required> Min amount <input name=min_amount type=number value=0> Min qty <input name=min_qty type=number value=0>
    From <input name=start type=date required> To <input name=end type=date required> Max uses <input name=max_uses type=number value=100> Product ID (blank=whole sub) <input name=product_id> <button>Add</button></form>"""
    return page("Discounts", f + table(["Name", "Kind", "Value", "Min amt", "Min qty", "Valid", "Used", "Applies to"], rows))

# ---------- subscriptions ----------
def sub_total(sid): return sum(l["qty"] * l["price"] for l in q("SELECT * FROM sub_lines WHERE sub_id=?", (sid,)))
@app.route("/subs", methods=["GET", "POST"])
@need()
def subs():
    u = me(); isc = u["role"] == "customer"; pg = pgnum(); off = (pg - 1) * 50
    if request.method == "POST" and not isc:
        t = one("SELECT * FROM templates WHERE id=?", (request.form["tpl"],)); cust = one("SELECT id FROM users WHERE email=?", (request.form["email"].strip().lower(),))
        if not (t and cust): flash("Template or customer email not found")
        else:
            plan = one("SELECT * FROM plans WHERE id=?", (t["plan_id"],)); today = date.today()
            sid = ex("INSERT INTO subs(number,customer_id,plan_id,start,expiry,terms,status,next_bill) VALUES('TMP',?,?,?,?,?,'Draft',?)", (cust["id"], plan["id"], today.isoformat(), (today + timedelta(days=int(request.form["days"]))).isoformat(), request.form["terms"], today.isoformat()))
            ex("UPDATE subs SET number=? WHERE id=?", (f"SUB{sid:05d}", sid))
            for l in json.loads(t["lines"]):
                p = one("SELECT * FROM products WHERE id=?", (l["product_id"],)); vid = request.form.get("variant", "")
                v = one("SELECT * FROM variants WHERE id=? AND product_id=?", (vid, p["id"])) if vid.isdigit() else None
                ex("INSERT INTO sub_lines(sub_id,product_id,variant_id,qty,price,tax_id) VALUES(?,?,?,?,?,?)", (sid, p["id"], v["id"] if v else None, max(l["qty"], plan["min_qty"]), plan["price"] + (v["extra"] if v else 0), int(request.form.get("tax") or 1)))
    where, a = ("WHERE s.customer_id=?", (u["id"],)) if isc else ("", ())
    st = request.args.get("status")
    if st: where += (" AND" if where else "WHERE") + " s.status=?"; a += (st,)
    rows = []
    for s in q(f"SELECT s.*, u.email, p.name pn, p.pausable, p.closable, p.renewable FROM subs s JOIN users u ON u.id=s.customer_id JOIN plans p ON p.id=s.plan_id {where} ORDER BY s.id DESC LIMIT 50 OFFSET {off}", a):
        act = "".join(f'<a class=b href="/subs/{s["id"]}/{k}?t={csrf()}">{lab}</a> ' for k, lab in actions(s, u["role"]))
        rows.append((f'<a href="/sub/{s["id"]}">{s["number"]}</a>', E(s["email"]), E(s["pn"]), f'{s["start"]} → {s["expiry"]}', f'<span class=tag>{s["status"]}</span>', money(sub_total(s["id"])), act))
    f = ""
    if not isc:
        opts = "".join(f'<option value={t["id"]}>{E(t["name"])}</option>' for t in q("SELECT * FROM templates"))
        topts = "".join(f'<option value={t["id"]}>{E(t["name"])}</option>' for t in q("SELECT * FROM taxes"))
        vopts = "".join(f'<option value={v["id"]}>{E(v["attr"])}: {E(v["val"])} (+{v["extra"]:g})</option>' for v in q("SELECT * FROM variants"))
        f = f'<form class=card method=post>New from template <select name=tpl>{opts}</select> Customer email <input name=email type=email required> Variant <select name=variant><option value="">none</option>{vopts}</select> Tax <select name=tax>{topts}</select> Valid days <input name=days type=number value=30> Terms <input name=terms value="Net 15"> <button>Create</button></form>'
    flt = "".join(f'<a class=b href="/subs?status={s}">{s}</a> ' for s in ["Draft", "Quotation", "Confirmed", "Active", "Closed"]) + '<a class=b href="/subs">All</a>'
    return page("Subscriptions", f + flt + table(["No.", "Customer", "Plan", "Period", "Status", "Per cycle", ""], rows) + pager(pg, "/subs", len(rows), st))
@app.route("/subs/<int:i>/<new>")
@need()
def sub_status(i, new):
    u = me(); s = one("SELECT s.*, p.pausable, p.closable, p.renewable FROM subs s JOIN plans p ON p.id=s.plan_id WHERE s.id=?", (i,))
    if not s or (u["role"] == "customer" and s["customer_id"] != u["id"]) or new not in [k for k, _ in actions(s, u["role"])]:
        flash("Not allowed"); return redirect("/subs")
    today = date.today(); nb = max(s["next_bill"], today.isoformat())
    if new == "pause": ex("UPDATE subs SET status='Paused' WHERE id=?", (i,))
    elif new == "resume": ex("UPDATE subs SET status='Active', next_bill=? WHERE id=?", (nb, i))
    elif new == "close": ex("UPDATE subs SET status='Closed' WHERE id=?", (i,))
    elif new == "renew": ex("UPDATE subs SET status='Active', next_bill=?, expiry=? WHERE id=?", (nb, (max(today, date.fromisoformat(s["expiry"])) + timedelta(days=365)).isoformat(), i))
    else: ex("UPDATE subs SET status=? WHERE id=?", (new, i))
    flash(f'{s["number"]} updated'); return redirect("/subs")
@app.route("/sub/<int:i>", methods=["GET", "POST"])
@need()
def sub_detail(i):
    u = me(); s = one("SELECT * FROM subs WHERE id=?", (i,))
    if not s or (u["role"] == "customer" and s["customer_id"] != u["id"]): return page("Not found", ""), 404
    plan = one("SELECT * FROM plans WHERE id=?", (s["plan_id"],)); edit = u["role"] != "customer" and s["status"] in ("Draft", "Quotation")
    if request.method == "POST" and edit:
        p = one("SELECT * FROM products WHERE id=?", (request.form["product"],)); v = one("SELECT * FROM variants WHERE id=? AND product_id=?", (request.form.get("variant", ""), p["id"])) if p else None
        if p: ex("INSERT INTO sub_lines(sub_id,product_id,variant_id,qty,price,tax_id) VALUES(?,?,?,?,?,?)", (i, p["id"], v["id"] if v else None, max(int(num(request.form["qty"], 1)), plan["min_qty"]), p["price"] + (v["extra"] if v else 0), int(request.form["tax"])))
    ls = q("SELECT sl.*, p.name, t.name tn, t.rate, v.val FROM sub_lines sl JOIN products p ON p.id=sl.product_id LEFT JOIN taxes t ON t.id=sl.tax_id LEFT JOIN variants v ON v.id=sl.variant_id WHERE sl.sub_id=?", (i,))
    rows = [(E(l["name"]) + (f' ({E(l["val"])})' if l["val"] else ""), l["qty"], money(l["price"]), E(l["tn"] or "-"), money(l["qty"] * l["price"]), f'<a href="/sub/{i}/del/{l["id"]}?t={csrf()}">✖</a>' if edit else "") for l in ls]
    f = ""
    if edit:
        po = "".join(f'<option value={p["id"]}>{E(p["name"])}</option>' for p in q("SELECT * FROM products"))
        vo = '<option value="">no variant</option>' + "".join(f'<option value={v["id"]}>{E(v["attr"])}: {E(v["val"])} (+{v["extra"]:g})</option>' for v in q("SELECT * FROM variants"))
        to = "".join(f'<option value={t["id"]}>{E(t["name"])}</option>' for t in q("SELECT * FROM taxes"))
        f = f'<form class=card method=post>Add line <select name=product>{po}</select> <select name=variant>{vo}</select> Qty <input name=qty type=number value=1 min=1> <select name=tax>{to}</select> <button>Add</button></form>'
    info = f'<div class=card>{s["number"]} · <span class=tag>{s["status"]}</span> · {E(plan["name"])} ({plan["period"]}) · {s["start"]} → {s["expiry"]} · Next bill {s["next_bill"]} · {E(s["terms"])} · Total/cycle <b>{money(sum(l["qty"] * l["price"] for l in ls))}</b></div>'
    return page("Subscription " + s["number"], info + table(["Product", "Qty", "Unit price", "Tax", "Amount", ""], rows) + f)
@app.route("/sub/<int:i>/del/<int:lid>")
@need("admin", "staff")
def sub_line_del(i, lid):
    s = one("SELECT status FROM subs WHERE id=?", (i,))
    if s and s["status"] in ("Draft", "Quotation"): ex("DELETE FROM sub_lines WHERE id=? AND sub_id=?", (lid, i))
    return redirect(f"/sub/{i}")

# ---------- billing ----------
def active_discount(sub, lines, subtotal):
    today = date.today().isoformat(); best = 0; used = None
    for d in q("SELECT * FROM discounts WHERE start<=? AND end>=? AND used<max_uses", (today, today)):
        if d["product_id"]: base = sum(l["qty"] * l["price"] for l in lines if l["product_id"] == d["product_id"]); qty = sum(l["qty"] for l in lines if l["product_id"] == d["product_id"])
        else: base, qty = subtotal, sum(l["qty"] for l in lines)
        if base <= 0 or base < d["min_amount"] or qty < d["min_qty"]: continue
        amt = min(base, base * d["value"] / 100 if d["kind"] == "percent" else d["value"])
        if amt > best: best, used = amt, d["id"]
    return best, used
@app.route("/billing/run")
@need("admin", "staff")
def run_billing():
    flash(f"{generate_invoices()} invoice(s) generated"); return redirect("/invoices")
def generate_invoices(today=None):
    today = today or date.today().isoformat(); made = 0
    for s in q("SELECT s.*, p.period FROM subs s JOIN plans p ON p.id=s.plan_id WHERE s.status='Active' AND s.next_bill<=?", (today,)):
        while s["next_bill"] <= today and s["next_bill"] <= s["expiry"]:   # catches up skipped cycles, never double-bills (UNIQUE sub_id+period)
            lines = q("SELECT sl.*, p.name, t.rate FROM sub_lines sl JOIN products p ON p.id=sl.product_id LEFT JOIN taxes t ON t.id=sl.tax_id WHERE sl.sub_id=?", (s["id"],))
            sub_t = sum(l["qty"] * l["price"] for l in lines); disc, did = active_discount(s, lines, sub_t)
            tax = sum((l["qty"] * l["price"]) * (1 - (disc / sub_t if sub_t else 0)) * (l["rate"] or 0) / 100 for l in lines)
            if not one("SELECT 1 FROM invoices WHERE sub_id=? AND period=?", (s["id"], s["next_bill"])):
                n = ex("INSERT INTO invoices(number,sub_id,customer_id,period,status,lines,subtotal,discount,tax,total,due) VALUES('TMP',?,?,?,'Draft',?,?,?,?,?,?)", (s["id"], s["customer_id"], s["next_bill"], json.dumps([dict(name=l["name"], qty=l["qty"], price=l["price"], rate=l["rate"]) for l in lines]), sub_t, disc, tax, sub_t - disc + tax, (date.fromisoformat(s["next_bill"]) + timedelta(days=15)).isoformat()))
                ex("UPDATE invoices SET number=? WHERE id=?", (f"INV{n:06d}", n)); made += 1
                if did: ex("UPDATE discounts SET used=used+1 WHERE id=?", (did,))
            nb = (date.fromisoformat(s["next_bill"]) + timedelta(days=STEP[s["period"]])).isoformat()
            ex("UPDATE subs SET next_bill=? WHERE id=?", (nb, s["id"])); s = one("SELECT s.*, p.period FROM subs s JOIN plans p ON p.id=s.plan_id WHERE s.id=?", (s["id"],))
    ex("UPDATE subs SET status='Closed' WHERE status='Active' AND expiry<? AND plan_id IN (SELECT id FROM plans WHERE auto_close=1)", (today,))
    return made
def paid(iid): return (one("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE invoice_id=?", (iid,)) or {"s": 0})["s"]
@app.route("/invoices")
@need()
def invoices():
    u = me(); where, a = ("WHERE i.customer_id=?", (u["id"],)) if u["role"] == "customer" else ("", ())
    st = request.args.get("status"); pg = pgnum()
    if st == "Overdue": where += (" AND" if where else "WHERE") + " i.status!='Paid' AND i.status!='Cancelled' AND i.due<?"; a += (date.today().isoformat(),)
    elif st: where += (" AND" if where else "WHERE") + " i.status=?"; a += (st,)
    rows = [(f'<a href="/invoice/{i["id"]}">{i["number"]}</a>', E(i["email"]), money(i["total"]), money(i["total"] - i["paid"]), i["due"], f'<span class=tag>{i["status"]}</span>') for i in q(f"SELECT i.*, u.email, (SELECT COALESCE(SUM(amount),0) FROM payments WHERE invoice_id=i.id) paid FROM invoices i JOIN users u ON u.id=i.customer_id {where} ORDER BY i.id DESC LIMIT 50 OFFSET {(pg-1)*50}", a)]
    top = "" if u["role"] == "customer" else f'<a class=b href="/billing/run?t={csrf()}">▶ Run billing</a> '
    top += "".join(f'<a class=b href="/invoices?status={s}">{s}</a> ' for s in ["Draft", "Confirmed", "Paid", "Cancelled", "Overdue"]) + '<a class=b href="/invoices">All</a>'
    return page("Invoices", top + table(["No.", "Customer", "Total", "Balance", "Due", "Status"], rows) + pager(pg, "/invoices", len(rows), st))
@app.route("/invoice/<int:i>")
@need()
def invoice(i):
    u = me(); inv = one("SELECT * FROM invoices WHERE id=?", (i,))
    if not inv or (u["role"] == "customer" and inv["customer_id"] != u["id"]): return page("Not found", ""), 404
    ls = [(E(l["name"]), l["qty"], money(l["price"]), f'{l["rate"] or 0:g}%', money(l["qty"] * l["price"])) for l in json.loads(inv["lines"])]
    acts = "" if u["role"] == "customer" else (f'<a class=b href="/invoice/{i}/Confirmed?t={csrf()}">Confirm</a> ' if inv["status"] == "Draft" else "") + (f'<a class=b href="/invoice/{i}/Cancelled?t={csrf()}">Cancel</a> ' if inv["status"] in ("Draft", "Confirmed") else "") + (f'<a class=b href="/invoice/{i}/send?t={csrf()}">Send to customer</a> ' if inv["status"] in ("Confirmed", "Paid") else "")
    pay = "".join(f"<tr><td>{p['date']}</td><td>{E(p['method'])}</td><td>{money(p['amount'])}</td><td>{E(p['note'] or '')}</td></tr>" for p in q("SELECT * FROM payments WHERE invoice_id=?", (i,)))
    pf = form("/payments", [("invoice_id", "Invoice ID"), ("method", "Method (UPI/Card/Bank)"), ("amount", "Amount", "number"), ("note", "Note")], "Record payment").replace('name=invoice_id type=text', f'name=invoice_id type=hidden value={i}') if u["role"] != "customer" and inv["status"] == "Confirmed" else ""
    return page(f'Invoice {inv["number"]}', f'<div class=card>Status: <b>{inv["status"]}</b> · Due {inv["due"]}<br>Subtotal {money(inv["subtotal"])} · Discount −{money(inv["discount"])} · Tax {money(inv["tax"])} · <b>Total {money(inv["total"])}</b> · Paid {money(paid(i))}</div>' + table(["Item", "Qty", "Price", "Tax", "Amount"], ls) + acts + '<button onclick="print()">Print</button>' + "<h3>Payments</h3><div class=card><table>" + pay + "</table></div>" + pf)
@app.route("/invoice/<int:i>/<new>")
@need("admin", "staff")
def inv_status(i, new):
    inv = one("SELECT * FROM invoices WHERE id=?", (i,))
    if inv and new == "send":
        c = one("SELECT email FROM users WHERE id=?", (inv["customer_id"],))
        send_mail(c["email"], "Invoice " + inv["number"], f'Your invoice {inv["number"]} for {money(inv["total"])} is due on {inv["due"]}.'); flash("Invoice sent to " + c["email"])
    elif inv and new in ("Confirmed", "Cancelled"): ex("UPDATE invoices SET status=? WHERE id=? AND status IN ('Draft','Confirmed')", (new, i))
    return redirect(f"/invoice/{i}")
@app.route("/payments", methods=["GET", "POST"])
@need("admin", "staff")
def payments():
    if request.method == "POST":
        inv = one("SELECT * FROM invoices WHERE id=?", (request.form["invoice_id"],)); amt = num(request.form["amount"])
        if not inv or inv["status"] != "Confirmed": flash("Invoice must be Confirmed")
        elif amt <= 0 or amt > inv["total"] - paid(inv["id"]) + 0.005: flash("Amount invalid or exceeds balance")
        else:
            ex("INSERT INTO payments(invoice_id,method,amount,date,note) VALUES(?,?,?,?,?)", (inv["id"], request.form["method"], amt, date.today().isoformat(), request.form["note"]))
            if paid(inv["id"]) >= inv["total"] - 0.005: ex("UPDATE invoices SET status='Paid' WHERE id=?", (inv["id"],))
        return redirect(f'/invoice/{inv["id"]}' if inv else "/payments")
    rows = [(p["date"], p["number"], E(p["method"]), money(p["amount"]), E(p["note"] or "")) for p in q("SELECT p.*, i.number FROM payments p JOIN invoices i ON i.id=p.invoice_id ORDER BY p.id DESC LIMIT 200")]
    return page("Payments", table(["Date", "Invoice", "Method", "Amount", "Note"], rows))

# ---------- admin extras ----------
EDITABLE = ("products", "plans", "discounts", "taxes")
@app.route("/taxes", methods=["GET", "POST"])
@need("admin")
def taxes():
    if request.method == "POST": ex("INSERT INTO taxes(name,rate) VALUES(?,?)", (request.form["name"], num(request.form["rate"])))
    rows = [(f'{E(t["name"])} {ops("taxes", t["id"])}', f'{t["rate"]:g}%') for t in q("SELECT * FROM taxes")]
    return page("Taxes", form("/taxes", [("name", "Tax name"), ("rate", "Rate %", "number")], "Add tax") + table(["Tax", "Rate"], rows))
@app.route("/edit/<tbl>/<int:i>", methods=["GET", "POST"])
@need("admin")
def edit(tbl, i):
    row = one(f"SELECT * FROM {tbl} WHERE id=?", (i,)) if tbl in EDITABLE else None
    if not row: return page("Not found", ""), 404
    cols = [c for c in row.keys() if c not in ("id", "used")]
    if request.method == "POST":
        ex(f"UPDATE {tbl} SET " + ",".join(f"{c}=?" for c in cols) + " WHERE id=?", [request.form.get(c) or None for c in cols] + [i]); flash("Updated"); return redirect("/" + tbl)
    h = "".join(f'<label>{c}<br><input name={c} value="{E(row[c] if row[c] is not None else "")}"></label><br>' for c in cols)
    return page("Edit " + tbl, f"<form class=card method=post>{h}<button>Save</button></form>")
@app.route("/del/<tbl>/<int:i>")
@need("admin")
def delete(tbl, i):
    if tbl not in EDITABLE: return page("Not found", ""), 404
    use = {"products": "SELECT 1 FROM sub_lines WHERE product_id=?", "plans": "SELECT 1 FROM subs WHERE plan_id=?", "taxes": "SELECT 1 FROM sub_lines WHERE tax_id=?"}.get(tbl)
    if use and one(use, (i,)): flash("In use by subscriptions, cannot delete")
    else:
        if tbl == "products": ex("DELETE FROM variants WHERE product_id=?", (i,))
        ex(f"DELETE FROM {tbl} WHERE id=?", (i,)); flash("Deleted")
    return redirect("/" + tbl)

# ---------- dashboard ----------
@app.route("/")
@need()
def home():
    u = me()
    if u["role"] == "customer": return redirect("/subs")
    t = date.today().isoformat(); fr = request.args.get("from") or "2000-01-01"; to = request.args.get("to") or "2999-12-31"
    sc = {r["status"]: r["c"] for r in q("SELECT status, COUNT(*) c FROM subs GROUP BY status")}
    rev = one("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE date BETWEEN ? AND ?", (fr, to))["s"]
    owed = one("SELECT COALESCE(SUM(i.total - (SELECT COALESCE(SUM(amount),0) FROM payments WHERE invoice_id=i.id)),0) s FROM invoices i WHERE i.status='Confirmed'")["s"]
    od = q("SELECT i.*, u.email FROM invoices i JOIN users u ON u.id=i.customer_id WHERE i.status='Confirmed' AND i.due<? ORDER BY i.due LIMIT 20", (t,))
    mrr = sum(sub_total(s["id"]) * 30 / STEP[s["period"]] for s in q("SELECT s.id, p.period FROM subs s JOIN plans p ON p.id=s.plan_id WHERE s.status='Active'"))
    ms = q("SELECT substr(date,1,7) m, SUM(amount) s FROM payments WHERE date BETWEEN ? AND ? GROUP BY m ORDER BY m DESC LIMIT 6", (fr, to))[::-1]
    mx = max([m["s"] for m in ms] or [1])
    bars = "".join(f'<div style="display:flex;gap:8px;align-items:center;margin:4px 0"><span style="width:80px">{m["m"]}</span><div style="background:var(--g);border:3px solid #000;height:20px;width:{max(2, int(m["s"] / mx * 60))}%"></div>{money(m["s"])}</div>' for m in ms) or "No payments in range"
    k = lambda l, v: f'<div class=card><div>{l}</div><div class=k>{v}</div></div>'
    flt = f'<form class=card>From <input type=date name=from value="{E(request.args.get("from", ""))}"> To <input type=date name=to value="{E(request.args.get("to", ""))}"> <button>Filter</button> <a class=b href="/">Reset</a></form>'
    summ = " ".join(f'<span class=tag>{k_}: {v}</span>' for k_, v in sc.items())
    return page("Dashboard", flt + f'<div class=g>{k("Active subscriptions", sc.get("Active", 0))}{k("Est. MRR", money(mrr))}{k("Revenue collected", money(rev))}{k("Outstanding", money(owed))}</div><div class=card>{summ}</div><h3>Revenue by month</h3><div class=card>{bars}</div><h3>Overdue invoices</h3>' + table(["No.", "Customer", "Total", "Due"], [(f'<a href="/invoice/{i["id"]}">{i["number"]}</a>', E(i["email"]), money(i["total"]), i["due"]) for i in od]))

def seed_demo():
    import random; random.seed(7); today = date.today()
    ex("INSERT INTO plans VALUES(NULL,'CRM Yearly',10000,'yearly',1,'2026-01-01','2030-12-31',1,1,0,1)")
    ex("INSERT INTO discounts(name,kind,value,min_amount,min_qty,start,end,max_uses,product_id) VALUES('Bulk 10%','percent',10,0,10,'2026-01-01','2030-12-31',50,NULL)")
    for n, name in enumerate(["Aarav Traders", "Zenith Cafe", "Pixel Studio", "Nova Retail", "Orbit Labs", "Kiran Foods", "Bluebird Co", "Maple Tech", "Sunrise Mart", "Delta Works", "Lotus Clinic", "Quartz Media"]):
        cid = ex("INSERT INTO users(email,pw,role,name) VALUES(?,?,'customer',?)", (f"customer{n+1}@demo.com", gh("Demo@12345"), name))
        plan = 2 if n % 4 == 0 else 1; st = "Active" if n < 9 else ["Draft", "Quotation", "Confirmed"][n - 9]; start = today - timedelta(days=random.randint(20, 100))
        sid = ex("INSERT INTO subs(number,customer_id,plan_id,start,expiry,terms,status,next_bill) VALUES('TMP',?,?,?,?,'Net 15',?,?)", (cid, plan, start.isoformat(), (start + timedelta(days=365)).isoformat(), st, start.isoformat()))
        ex("UPDATE subs SET number=? WHERE id=?", (f"SUB{sid:05d}", sid))
        ex("INSERT INTO sub_lines(sub_id,product_id,variant_id,qty,price,tax_id) VALUES(?,1,NULL,?,?,1)", (sid, random.choice([3, 5, 12]), 1000 if plan == 1 else 10000))
    generate_invoices(); ex("UPDATE invoices SET status='Confirmed'")
    for n, inv in enumerate(q("SELECT * FROM invoices")):
        if n % 3 != 1:
            ex("INSERT INTO payments(invoice_id,method,amount,date,note) VALUES(?,?,?,?,'Demo payment')", (inv["id"], random.choice(["UPI", "Card", "Bank"]), inv["total"], inv["period"])); ex("UPDATE invoices SET status='Paid' WHERE id=?", (inv["id"],))

init()
with app.app_context():
    if not one("SELECT 1 FROM users WHERE role='customer'"): seed_demo()
if __name__ == "__main__": app.run(debug=os.environ.get("DEBUG") == "1")
