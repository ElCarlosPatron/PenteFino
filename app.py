"""Pente Fino 3.1 — contagem compartilhada, interface mobile-first.

Execute para testar: python app.py
Para uso na rede local: waitress-serve --listen=0.0.0.0:5050 app:app
"""
from __future__ import annotations

import csv
import io
import os
import secrets
import socket
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from werkzeug.middleware.proxy_fix import ProxyFix

from flask import (Flask, abort, current_app, flash, g, jsonify, redirect,
                   render_template, request, send_file, session, url_for)

from core import load_comptar, safe_filename, export_adjustments, is_sem_localizacao
from reports import build_pdf

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
TZ = ZoneInfo("America/Sao_Paulo")


def timestamp():
    return datetime.now(TZ).isoformat(timespec="seconds")


def secret_key():
    """Chave persistente entre reinícios do servidor, definida no Render."""
    env_key = os.environ.get("SECRET_KEY", "").strip()
    if env_key:
        if len(env_key) < 32:
            raise RuntimeError("SECRET_KEY precisa ter pelo menos 32 caracteres.")
        return env_key
    if os.environ.get("RENDER") or os.environ.get("DATABASE_URL"):
        raise RuntimeError("Configure SECRET_KEY nas variáveis de ambiente antes de publicar.")
    # Apenas local: a pasta data permanece no disco do computador.
    key_path = DATA_DIR / ".secret_key"
    if not key_path.exists():
        try:
            with key_path.open("x", encoding="utf-8") as handle:
                handle.write(secrets.token_hex(32))
        except FileExistsError:
            pass
    return key_path.read_text(encoding="utf-8").strip()


CLOUD_DB_URL = os.environ.get("DATABASE_URL", "").strip()
if os.environ.get("RENDER") and not CLOUD_DB_URL:
    raise RuntimeError("Render sem DATABASE_URL: use um banco Neon para proteger as contagens.")
if CLOUD_DB_URL and not CLOUD_DB_URL.startswith(("postgresql://", "postgres://")):
    raise RuntimeError("DATABASE_URL precisa ser uma conexão PostgreSQL do Neon.")

app = Flask(__name__)
if os.environ.get("RENDER"):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config.update(
    SECRET_KEY=secret_key(),
    DB_PATH=str(DATA_DIR / "pente_fino.sqlite3"),
    MAX_CONTENT_LENGTH=15 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)


class PostgresConnection:
    """Compatibilidade DB-API das consultas SQLite já usadas pelo projeto.

    A conexão PostgreSQL começa transações no primeiro SELECT. O BEGIN IMMEDIATE
    exclusivo do SQLite vira no-op; travamos explicitamente as linhas do
    aparelho em pontos críticos com SELECT ... FOR UPDATE.
    """
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, params=None):
        if sql.strip().upper() == "BEGIN IMMEDIATE":
            return None
        return self.connection.execute(sql.replace("?", "%s"), params or ())

    def executemany(self, sql, params_seq):
        with self.connection.cursor() as cursor:
            cursor.executemany(sql.replace("?", "%s"), params_seq)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


def db():
    if "db" not in g:
        if CLOUD_DB_URL:
            import psycopg
            from psycopg.rows import dict_row
            connection = psycopg.connect(
                CLOUD_DB_URL, row_factory=dict_row, connect_timeout=15,
                sslmode="require",
            )
            g.db = PostgresConnection(connection)
        else:
            connection = sqlite3.connect(current_app.config["DB_PATH"], timeout=20)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA busy_timeout=20000")
            g.db = connection
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def initialize_database():
    if CLOUD_DB_URL:
        _initialize_postgres()
    else:
        _initialize_sqlite()

    # Atualização 3.1: recupera Saldo, C1 e C.Dif dos CSVs anteriores
    # sem tocar nas quantidades nem nas revisões.
    old_counts = db().execute("""
        SELECT c.code, c.source_csv FROM counts c
        WHERE EXISTS (
            SELECT 1 FROM products p WHERE p.code=c.code AND
            (p.saldo_comptar IS NULL OR p.c1_comptar IS NULL OR p.cdif_comptar IS NULL)
        )
    """).fetchall()
    for old_count in old_counts:
        _, work, indices = load_comptar(old_count["source_csv"])
        db().executemany("""
            UPDATE products SET saldo_comptar=?, c1_comptar=?, cdif_comptar=?
            WHERE code=? AND source_index=?
        """, [
            (str(row["Saldo"]), str(row["C1"]), str(row["C.Dif"]),
             old_count["code"], int(indices[i]))
            for i, row in work.iterrows()
        ])
    db().commit()


def _initialize_postgres():
    """Schema permanente e idempotente no Neon/PostgreSQL."""
    ddl = [
        """CREATE TABLE IF NOT EXISTS counts (
            code TEXT PRIMARY KEY, store TEXT NOT NULL, filename TEXT NOT NULL,
            source_csv BYTEA NOT NULL, created_at TEXT NOT NULL,
            phone_count INTEGER NOT NULL, admin_token TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS phones (
            code TEXT NOT NULL REFERENCES counts(code) ON DELETE CASCADE,
            slot INTEGER NOT NULL, operator TEXT, join_token TEXT,
            finished_at TEXT, joined_at TEXT, finish_kind TEXT,
            PRIMARY KEY(code, slot)
        )""",
        """CREATE TABLE IF NOT EXISTS products (
            id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            code TEXT NOT NULL REFERENCES counts(code) ON DELETE CASCADE,
            source_index INTEGER NOT NULL, slot INTEGER NOT NULL,
            sku TEXT NOT NULL, description TEXT NOT NULL,
            location TEXT NOT NULL, final_original TEXT NOT NULL,
            final_count INTEGER NOT NULL, reviewed_at TEXT,
            reviewed_by TEXT, saldo_comptar TEXT, c1_comptar TEXT,
            cdif_comptar TEXT, UNIQUE(code, source_index)
        )""",
        """CREATE TABLE IF NOT EXISTS events (
            id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            code TEXT NOT NULL, slot INTEGER NOT NULL,
            operator TEXT NOT NULL, event TEXT NOT NULL,
            sku TEXT, quantity INTEGER, at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_products_slot ON products(code,slot,reviewed_at)",
        "CREATE INDEX IF NOT EXISTS idx_events_by_phone ON events(code,slot,id)",
    ]
    for statement in ddl:
        db().execute(statement)
    # Migrações idempotentes para futura atualização de uma instância Neon.
    definitions = {
        "phones": {"joined_at": "TEXT", "finish_kind": "TEXT"},
        "products": {"reviewed_by": "TEXT", "saldo_comptar": "TEXT",
                     "c1_comptar": "TEXT", "cdif_comptar": "TEXT"},
    }
    for table, columns in definitions.items():
        for col, kind in columns.items():
            db().execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {kind}")


def _initialize_sqlite():
    """Mantém exatamente o comportamento SQLite das versões 3.0/3.2."""
    db().executescript("""
        CREATE TABLE IF NOT EXISTS counts (
            code TEXT PRIMARY KEY,
            store TEXT NOT NULL,
            filename TEXT NOT NULL,
            source_csv BLOB NOT NULL,
            created_at TEXT NOT NULL,
            phone_count INTEGER NOT NULL,
            admin_token TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS phones (
            code TEXT NOT NULL REFERENCES counts(code) ON DELETE CASCADE,
            slot INTEGER NOT NULL,
            operator TEXT,
            join_token TEXT,
            finished_at TEXT,
            PRIMARY KEY (code, slot)
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL REFERENCES counts(code) ON DELETE CASCADE,
            source_index INTEGER NOT NULL,
            slot INTEGER NOT NULL,
            sku TEXT NOT NULL,
            description TEXT NOT NULL,
            location TEXT NOT NULL,
            final_original TEXT NOT NULL,
            final_count INTEGER NOT NULL,
            reviewed_at TEXT,
            saldo_comptar TEXT,
            c1_comptar TEXT,
            cdif_comptar TEXT,
            UNIQUE(code, source_index)
        );
        CREATE INDEX IF NOT EXISTS idx_products_slot
            ON products(code, slot, reviewed_at);
    """)
    definitions = {
        "phones": {"joined_at": "TEXT", "finish_kind": "TEXT"},
        "products": {"reviewed_by": "TEXT", "saldo_comptar": "TEXT",
                     "c1_comptar": "TEXT", "cdif_comptar": "TEXT"},
    }
    for table, columns in definitions.items():
        existing = {r["name"] for r in db().execute(f"PRAGMA table_info({table})")}
        for name, kind in columns.items():
            if name not in existing:
                db().execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
    db().execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            slot INTEGER NOT NULL,
            operator TEXT NOT NULL,
            event TEXT NOT NULL,
            sku TEXT,
            quantity INTEGER,
            at TEXT NOT NULL
        )
    """)
    db().execute("CREATE INDEX IF NOT EXISTS idx_events_by_phone ON events(code,slot,id)")

def audit(code, slot, operator, event, sku=None, quantity=None):
    db().execute("""INSERT INTO events(code,slot,operator,event,sku,quantity,at)
                 VALUES (?,?,?,?,?,?,?)""",
                 (code, slot, operator or "(sem operador)", event, sku, quantity, timestamp()))


with app.app_context():
    initialize_database()


def get_count(code):
    count = db().execute("SELECT * FROM counts WHERE code=?", (code.upper(),)).fetchone()
    if not count:
        abort(404)
    return count


def admin_authorized(count):
    return secrets.compare_digest(
        session.get("admins", {}).get(count["code"], ""), count["admin_token"]
    )


def worker_info(count):
    credential = session.get("workers", {}).get(count["code"])
    if not credential:
        return None
    phone = db().execute("SELECT * FROM phones WHERE code=? AND slot=?",
                         (count["code"], credential.get("slot"))).fetchone()
    if phone and phone["join_token"] and secrets.compare_digest(
        phone["join_token"], credential.get("token", "")
    ):
        return phone
    return None


def require_admin(count):
    if not admin_authorized(count):
        abort(403, "Acesso reservado ao responsável pela contagem neste navegador.")


def require_worker(count):
    phone = worker_info(count)
    if phone is None:
        abort(403, "Este celular ainda não está vinculado à contagem.")
    return phone


def summary(count):
    rows = db().execute("""
        SELECT ph.slot, ph.operator, ph.joined_at, ph.finished_at, ph.finish_kind,
               COUNT(p.id) AS total,
               SUM(CASE WHEN p.reviewed_at IS NOT NULL THEN 1 ELSE 0 END) AS reviewed,
               SUM(CASE WHEN p.reviewed_at IS NOT NULL AND
                 CAST(p.final_original AS INTEGER) != p.final_count THEN 1 ELSE 0 END) AS changes
        FROM phones ph LEFT JOIN products p
           ON ph.code=p.code AND ph.slot=p.slot
        WHERE ph.code=?
        GROUP BY ph.code, ph.slot, ph.operator, ph.joined_at, ph.finished_at, ph.finish_kind ORDER BY ph.slot
    """, (count["code"],)).fetchall()
    phones = [dict(r) for r in rows]
    for ph in phones:
        ph["reviewed"] = ph["reviewed"] or 0
        ph["pending"] = ph["total"] - ph["reviewed"]
        last = db().execute("""
            SELECT sku, at, operator FROM events
            WHERE code=? AND slot=? AND event='reviewed'
              AND operator=? AND at>=?
            ORDER BY id DESC LIMIT 1
        """, (count["code"], ph["slot"], ph["operator"] or "",
              ph["joined_at"] or "")).fetchone()
        if last is None:  # Existing v2 records predate the audit table.
            last = db().execute("""
                SELECT sku, reviewed_at AS at, reviewed_by AS operator FROM products
                WHERE code=? AND slot=? AND reviewed_at IS NOT NULL
                ORDER BY reviewed_at DESC, id DESC LIMIT 1
            """, (count["code"], ph["slot"])).fetchone()
        ph["last_sku"] = last["sku"] if last else None
        ph["last_reviewed_at"] = last["at"] if last else None
    total = sum(p["total"] for p in phones)
    reviewed = sum(p["reviewed"] for p in phones)
    finished = sum(bool(p["finished_at"]) for p in phones)
    ready = (len(phones) == count["phone_count"] and
             finished == count["phone_count"] and total > 0)
    early = sum(bool(p["finished_at"] and p["pending"]) for p in phones)
    return {"phones": phones, "total": total, "reviewed": reviewed,
            "finished": finished, "ready": ready, "early": early,
            "pending": total-reviewed,
            "percentage": round(100 * reviewed / total) if total else 0}


def product_report_rows(count):
    rows = db().execute("""
        SELECT p.sku, p.description, p.final_original, p.final_count, p.reviewed_at,
               p.reviewed_by, p.slot, p.source_index, ph.operator, ph.finished_at
        FROM products p JOIN phones ph ON ph.code=p.code AND ph.slot=p.slot
        WHERE p.code=? ORDER BY p.source_index
    """, (count["code"],)).fetchall()
    result = []
    for r in rows:
        entry = dict(r)
        if entry["reviewed_at"]:
            entry["status"] = "Conferido"
        elif entry["finished_at"]:
            entry["status"] = "Finalizado antes de conferir"
        else:
            entry["status"] = "Pendente"
        # Never change the Comptar final quantity for SKUs without physical review.
        entry["quantity"] = entry["final_count"] if entry["reviewed_at"] else int(entry["final_original"])
        result.append(entry)
    return result


def check_export(count):
    require_admin(count)
    stats = summary(count)
    if not stats["ready"]:
        abort(409, "A exportação só é liberada quando TODOS os celulares finalizarem (inclusive antecipadamente).")
    return stats


def local_join_link(code):
    """Mostra um link acessível na rede local ao abrir o painel via localhost."""
    regular_link = url_for("join", code=code, _external=True)
    if request.host.split(":")[0].lower() not in ("localhost", "127.0.0.1"):
        return regular_link
    address = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as conn:
            conn.connect(("1.1.1.1", 80))  # descobre interface; não envia tráfego
            address = conn.getsockname()[0]
    except OSError:
        try:
            address = socket.gethostbyname(socket.gethostname())
        except OSError:
            pass
    if address and not address.startswith("127."):
        return f"http://{address}:5050" + url_for("join", code=code)
    return regular_link


@app.context_processor
def global_template_data():
    return {"today": datetime.now(TZ).strftime("%d/%m/%Y %H:%M"), "online_mode": bool(CLOUD_DB_URL)}


@app.get("/saude")
def health():
    return jsonify({"status": "online", "database": "neon" if CLOUD_DB_URL else "sqlite"})


@app.get("/")
def home():
    return render_template("home.html")


@app.post("/criar")
def create():
    upload = request.files.get("arquivo")
    store = (request.form.get("loja") or "").strip()[:100]
    try:
        phones = int(request.form.get("celulares", "1"))
    except ValueError:
        phones = 0
    if not upload or not upload.filename or not upload.filename.lower().endswith(".csv"):
        flash("Selecione um arquivo CSV do Comptar.", "error")
        return redirect(url_for("home"))
    if not store or not (1 <= phones <= 20):
        flash("Informe a loja e escolha entre 1 e 20 celulares.", "error")
        return redirect(url_for("home"))
    content = upload.read()
    try:
        original, work, valid_indices = load_comptar(content)
    except ValueError as error:
        flash(f"Não foi possível ler o CSV: {error}", "error")
        return redirect(url_for("home"))
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
    while db().execute("SELECT 1 FROM counts WHERE code=?", (code,)).fetchone():
        code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
    admin_token = secrets.token_urlsafe(32)
    connection = db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("INSERT INTO counts VALUES (?,?,?,?,?,?,?)",
                           (code, store, upload.filename[:255], content,
                            timestamp(), phones, admin_token))
        connection.executemany("INSERT INTO phones(code,slot) VALUES (?,?)",
                               [(code, i) for i in range(1, phones + 1)])
        connection.executemany("""
            INSERT INTO products
                (code,source_index,slot,sku,description,location,final_original,final_count,
                 saldo_comptar,c1_comptar,cdif_comptar)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, [
            (code, int(valid_indices[i]), (i % phones) + 1,
             str(row["Codigo"]), str(row["Descricao"]), str(row["Localizacoes"]),
             str(row["Final"]), int(row["CONT.FINAL"]),
             str(row["Saldo"]), str(row["C1"]), str(row["C.Dif"]))
            for i, row in work.iterrows()
        ])
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    admins = dict(session.get("admins", {}))
    admins[code] = admin_token
    session["admins"] = admins
    session.permanent = True
    flash(f"Contagem criada: {len(work)} produtos para {phones} celular(es).", "success")
    return redirect(url_for("admin", code=code))


@app.get("/gestao/<code>/recuperar/<token>")
def recover_admin(code, token):
    count = get_count(code)
    if not secrets.compare_digest(token, count["admin_token"]):
        abort(403)
    admins = dict(session.get("admins", {}))
    admins[count["code"]] = token
    session["admins"] = admins
    session.permanent = True
    return redirect(url_for("admin", code=count["code"]))


@app.get("/gestao/<code>")
def admin(code):
    count = get_count(code)
    require_admin(count)
    return render_template("admin.html", count=count, stats=summary(count), join_link=local_join_link(code))


@app.get("/entrar")
def join_landing():
    return render_template("join.html", count=None, phone=None, free=[])


@app.post("/entrar")
def join_landing_post():
    code = (request.form.get("codigo") or "").strip().replace("-", "").upper()
    if not db().execute("SELECT 1 FROM counts WHERE code=?", (code,)).fetchone():
        flash("Código não encontrado. Confira os oito caracteres.", "error")
        return redirect(url_for("join_landing"))
    return redirect(url_for("join", code=code))


@app.get("/entrar/<code>")
def join(code):
    count = get_count(code)
    phone = worker_info(count)
    if phone:
        return redirect(url_for("work", code=count["code"]))
    free = db().execute("SELECT slot FROM phones WHERE code=? AND join_token IS NULL ORDER BY slot",
                        (count["code"],)).fetchall()
    return render_template("join.html", count=count, phone=None, free=[x["slot"] for x in free])


@app.post("/entrar/<code>")
def reserve_phone(code):
    count = get_count(code)
    if worker_info(count):
        return redirect(url_for("work", code=code))
    name = (request.form.get("operador") or "").strip()[:80]
    try:
        slot = int(request.form.get("celular", "0"))
    except ValueError:
        slot = 0
    if not name or slot < 1 or slot > count["phone_count"]:
        flash("Informe seu nome e selecione um celular disponível.", "error")
        return redirect(url_for("join", code=code))
    token = secrets.token_urlsafe(32)
    connection = db()
    connection.execute("BEGIN IMMEDIATE")
    updated = connection.execute("""
        UPDATE phones SET operator=?,join_token=?,joined_at=?
        WHERE code=? AND slot=? AND join_token IS NULL
    """, (name, token, timestamp(), count["code"], slot)).rowcount
    if updated:
        audit(count["code"], slot, name, "joined")
    connection.commit()
    if not updated:
        flash("Este celular já foi reservado. Escolha outro.", "error")
        return redirect(url_for("join", code=code))
    workers = dict(session.get("workers", {}))
    workers[count["code"]] = {"slot": slot, "token": token}
    session["workers"] = workers
    session.permanent = True
    return redirect(url_for("work", code=code))


# Filtros pertencem à navegação do celular: os mesmos critérios são usados
# na lista, nos botões Anterior/Próximo e no redirecionamento após salvar.
FILTERS = {"todos", "conferidos", "pendentes", "sem_localizacao"}


def normalized_filter(value):
    return value if value in FILTERS else "todos"


def matching_products(rows, status_filter, query):
    query = query.casefold()
    matches = []
    for row in rows:
        if query and query not in f'{row["sku"]} {row["description"]} {row["location"]}'.casefold():
            continue
        if status_filter == "conferidos" and row["reviewed_at"] is None:
            continue
        if status_filter == "pendentes" and row["reviewed_at"] is not None:
            continue
        if status_filter == "sem_localizacao" and not is_sem_localizacao(
            row["saldo_comptar"], row["c1_comptar"], row["cdif_comptar"]
        ):
            continue
        matches.append(row)
    return matches


@app.get("/contar/<code>")
def work(code):
    count = get_count(code)
    phone = require_worker(count)
    rows = db().execute("""
        SELECT * FROM products WHERE code=? AND slot=? ORDER BY source_index
    """, (count["code"], phone["slot"])).fetchall()
    reviewed = sum(row["reviewed_at"] is not None for row in rows)
    total = len(rows)
    sem_localizacao_ids = {
        row["id"] for row in rows
        if is_sem_localizacao(row["saldo_comptar"], row["c1_comptar"], row["cdif_comptar"])
    }
    if phone["finished_at"]:
        return render_template("work.html", count=count, phone=phone, total=total,
                               reviewed=reviewed, product=None, position=0,
                               completed=True, query="", status_filter="todos")

    query = (request.args.get("q") or "").strip()[:80]
    status_filter = normalized_filter(request.args.get("status", "todos"))
    filtered_rows = matching_products(rows, status_filter, query)
    item_param = request.args.get("item")
    search_results = None
    product = None
    position = 0
    previous_item = None
    next_item = None
    finish_prompt = request.args.get("finalizar") == "1"
    in_active_filter = True

    # Abrir item tem prioridade sobre apresentar lista filtrada. A URL do item
    # conserva ?status=...&q=..., inclusive após atualizar a página.
    if item_param is not None:
        try:
            item_id = int(item_param)
        except (TypeError, ValueError):
            abort(404)
        product = next((row for row in rows if row["id"] == item_id), None)
        if product is None:
            abort(404)
    elif query or status_filter != "todos":
        search_results = filtered_rows[:150]
    else:
        product = next((row for row in rows if row["reviewed_at"] is None), None)

    if product is not None:
        # Anterior e Próximo navegam APENAS pelas SKUs que correspondem ao filtro.
        selected_idx = next((i for i, r in enumerate(filtered_rows)
                             if r["id"] == product["id"]), None)
        if selected_idx is not None:
            position = selected_idx + 1
            previous_item = filtered_rows[selected_idx-1] if selected_idx else None
            next_item = (filtered_rows[selected_idx+1]
                         if selected_idx+1 < len(filtered_rows) else None)
        else:
            # Pode acontecer após uma SKU de 'pendentes' ser conferida e o
            # usuário retornar pelo histórico do navegador. Mantém o cartão
            # editável e navega apenas pelos SKUs que ainda satisfazem o filtro.
            in_active_filter = False
            previous_item = next((r for r in reversed(filtered_rows)
                                  if r["source_index"] < product["source_index"]), None)
            next_item = next((r for r in filtered_rows
                              if r["source_index"] > product["source_index"]), None)
    return render_template("work.html", count=count, phone=phone, total=total,
                           reviewed=reviewed, product=product, position=position,
                           filtered_total=len(filtered_rows),
                           in_active_filter=in_active_filter,
                           previous_item=previous_item, next_item=next_item,
                           search_results=search_results, result_count=len(filtered_rows),
                           finish_prompt=finish_prompt, completed=False,
                           query=query, status_filter=status_filter,
                           sem_localizacao_ids=sem_localizacao_ids,
                           sem_localizacao_total=len(sem_localizacao_ids))


@app.post("/contar/<code>/produto/<int:product_id>")
def save_product(code, product_id):
    count = get_count(code)
    phone = require_worker(count)
    if phone["finished_at"]:
        abort(409, "Essa parte da contagem já foi finalizada.")
    query = (request.form.get("q") or "").strip()[:80]
    status_filter = normalized_filter(request.form.get("status", "todos"))
    context = {"status": status_filter, "q": query}
    value = (request.form.get("quantidade") or "").strip()
    if not value.isdecimal() or len(value) > 12:
        flash("Digite uma quantidade inteira maior ou igual a zero.", "error")
        return redirect(url_for("work", code=code, item=product_id, **context))
    quantity = int(value)
    connection = db()
    connection.execute("BEGIN IMMEDIATE")
    status = connection.execute("SELECT finished_at FROM phones WHERE code=? AND slot=?" + (" FOR UPDATE" if CLOUD_DB_URL else ""),
                                (count["code"], phone["slot"])).fetchone()
    if status is None or status["finished_at"]:
        connection.rollback()
        abort(409, "Essa parte da contagem foi finalizada.")
    rows = connection.execute("""
        SELECT * FROM products WHERE code=? AND slot=? ORDER BY source_index
    """, (count["code"], phone["slot"])).fetchall()
    current = next((row for row in rows if row["id"] == product_id), None)
    if current is None:
        connection.rollback()
        abort(404)

    # Calcular o próximo ANTES de salvar, pois o item atual pode sair do filtro
    # "Não conferidos" logo após a confirmação.
    matches = matching_products(rows, status_filter, query)
    next_id = next((row["id"] for row in matches
                    if row["source_index"] > current["source_index"]), None)
    updated = connection.execute("""
        UPDATE products SET final_count=?, reviewed_at=?, reviewed_by=?
        WHERE id=? AND code=? AND slot=?
    """, (quantity, timestamp(), phone["operator"], product_id, count["code"], phone["slot"])).rowcount
    if updated != 1:
        connection.rollback()
        abort(404)
    audit(count["code"], phone["slot"], phone["operator"],
          "reviewed", current["sku"], quantity)
    connection.commit()
    if next_id is not None:
        return redirect(url_for("work", code=code, item=next_id, **context))
    return redirect(url_for("work", code=code, **context))


@app.post("/contar/<code>/finalizar")
def finish_phone(code):
    count = get_count(code)
    phone = require_worker(count)
    connection = db()
    connection.execute("BEGIN IMMEDIATE")
    current = connection.execute("SELECT finished_at FROM phones WHERE code=? AND slot=?" + (" FOR UPDATE" if CLOUD_DB_URL else ""),
                                 (count["code"], phone["slot"])).fetchone()
    if current is None or current["finished_at"]:
        connection.rollback()
        abort(409, "Esta parte já foi finalizada.")
    remaining = connection.execute("""
        SELECT COUNT(*) AS n FROM products WHERE code=? AND slot=? AND reviewed_at IS NULL
    """, (count["code"], phone["slot"])).fetchone()["n"]
    if remaining and request.form.get("confirmar_antecipado") != "sim":
        connection.rollback()
        flash(f"Faltam {remaining} SKUs. Confira o aviso e confirme a finalização antecipada.", "error")
        return redirect(url_for("work", code=code, finalizar="1"))
    finish_kind = "early" if remaining else "complete"
    connection.execute("UPDATE phones SET finished_at=?,finish_kind=? WHERE code=? AND slot=?",
                       (timestamp(), finish_kind, count["code"], phone["slot"]))
    audit(count["code"], phone["slot"], phone["operator"],
          "finished_early" if remaining else "finished_complete")
    connection.commit()
    flash((f"Parte finalizada com {remaining} SKUs sem conferência física."
           if remaining else "Todos os SKUs foram conferidos e sua parte foi finalizada!"), "success")
    return redirect(url_for("work", code=code))


@app.get("/api/<code>/status")
def progress_api(code):
    count = get_count(code)
    if not admin_authorized(count) and not worker_info(count):
        abort(403)
    return jsonify(summary(count))


@app.post("/gestao/<code>/reabrir/<int:slot>")
def reopen_phone(code, slot):
    count = get_count(code)
    require_admin(count)
    if slot < 1 or slot > count["phone_count"]:
        abort(404)
    phone = db().execute("SELECT operator FROM phones WHERE code=? AND slot=?", (count["code"],slot)).fetchone()
    db().execute("UPDATE phones SET finished_at=NULL,finish_kind=NULL WHERE code=? AND slot=?",
                 (count["code"], slot))
    audit(count["code"], slot, phone["operator"] if phone else None, "reopened")
    db().commit()
    flash(f"Celular {slot} reaberto para correções.", "success")
    return redirect(url_for("admin", code=code))


@app.post("/gestao/<code>/liberar/<int:slot>")
def release_phone(code, slot):
    count = get_count(code)
    require_admin(count)
    if slot < 1 or slot > count["phone_count"]:
        abort(404)
    # Mantém quantidades revisadas; o novo operador assume o restante.
    phone = db().execute("SELECT operator FROM phones WHERE code=? AND slot=?", (count["code"],slot)).fetchone()
    audit(count["code"], slot, phone["operator"] if phone else None, "released")
    db().execute("""
        UPDATE phones SET operator=NULL,join_token=NULL,joined_at=NULL,finished_at=NULL,finish_kind=NULL
        WHERE code=? AND slot=?
    """, (count["code"], slot))
    db().commit()
    flash(f"Celular {slot} liberado. Outro operador pode assumir a parte restante.", "success")
    return redirect(url_for("admin", code=code))


@app.get("/gestao/<code>/baixar")
def download_csv(code):
    count = get_count(code)
    check_export(count)
    rows = product_report_rows(count)
    data = export_adjustments(rows)
    filename = f"PENTE_FINO_AJUSTES_{safe_filename(count['store'])}_{code}.csv"
    return send_file(io.BytesIO(data), as_attachment=True, download_name=filename,
                     mimetype="text/csv; charset=utf-8")


@app.get("/gestao/<code>/relatorio.pdf")
def download_pdf(code):
    count = get_count(code)
    stats = check_export(count)
    history = [dict(row) for row in db().execute("""
        SELECT e.slot,e.operator,e.event,e.sku,e.quantity,e.at,
          (SELECT r.sku FROM events r WHERE r.code=e.code AND r.slot=e.slot
             AND r.operator=e.operator AND r.event='reviewed' AND r.id < e.id
             ORDER BY r.id DESC LIMIT 1) AS last_sku
        FROM events e
        WHERE e.code=? AND e.event IN ('joined','released','finished_early','finished_complete','reopened')
        ORDER BY e.id
    """, (count["code"],)).fetchall()]
    pdf = build_pdf(dict(count), stats, product_report_rows(count), history)
    filename = f"PENTE_FINO_RELATORIO_{safe_filename(count['store'])}_{code}.pdf"
    return send_file(io.BytesIO(pdf), as_attachment=True, download_name=filename,
                     mimetype="application/pdf")


@app.get("/gestao/<code>/operadores.csv")
def download_operators(code):
    count = get_count(code)
    stats = check_export(count)
    payload = io.StringIO(newline="")
    writer = csv.writer(payload, delimiter=";", lineterminator="\r\n")
    writer.writerow(["CELULAR", "OPERADOR", "ENTRADA", "FINALIZAÇÃO",
                     "CONFERIDOS", "TOTAL", "NÃO CONFERIDOS", "ÚLTIMO SKU CONFERIDO", "SITUAÇÃO"])

    def excel_datetime(value):
        if not value:
            return ""
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.strftime("%d/%m/%Y %H:%M:%S")
        except ValueError:
            return value

    def excel_safe(value):
        text = str(value or "")
        return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else text

    for ph in stats["phones"]:
        writer.writerow([ph["slot"], excel_safe(ph["operator"]),
                         excel_datetime(ph["joined_at"]), excel_datetime(ph["finished_at"]),
                         ph["reviewed"], ph["total"], ph["pending"], excel_safe(ph["last_sku"]),
                         "Finalização antecipada" if ph["finished_at"] and ph["pending"]
                         else "Concluído" if ph["finished_at"] else "Em andamento"])
    return send_file(io.BytesIO(payload.getvalue().encode("utf-8-sig")),
                     as_attachment=True,
                     download_name=f"PENTE_FINO_OPERADORES_{code}.csv",
                     mimetype="text/csv; charset=utf-8")


@app.errorhandler(413)
def file_too_large(error):
    return "O arquivo ultrapassa o limite de 15 MB.", 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5050")), debug=False)
