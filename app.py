#!/usr/bin/env python3
"""
Servidor local y API REST ligera para BioDelta.
100% local, privacidad total, sin dependencias externas pesadas.

Endpoints principales:
  GET  /                     -> Interfaz web principal (web/index.html)
  GET  /web/<path>           -> Recursos estáticos (JS, CSS)
  GET  /assets/<path>        -> Logos e iconos
  GET  /api/status           -> Estado de la BD, rangos de fechas, auth y binarios
  GET  /api/weeks            -> Lista de semanas disponibles en la BD
  GET  /api/report           -> Genera y devuelve el informe (HTML + JSON) para un rango
  POST /api/sync             -> Inicia sincronización incremental con Garmin Connect
  GET  /api/sync/status      -> Consulta el progreso o estado de la sincronización activa
  POST /api/auth             -> Autenticación visual Garmin Connect (detecta 2FA/MFA)
  POST /api/auth/mfa         -> Completa autenticación con el código 2FA
  POST /api/upload           -> Carga de archivo garmin_data.db mediante drag & drop
  GET  /api/demo             -> Genera entorno de demostración instantáneo
  GET  /api/settings         -> Obtiene objetivos y preferencias locales
  POST /api/settings         -> Guarda objetivos y preferencias locales
"""

import json
import sqlite3
import sys
import threading
import time
import uuid
import webbrowser
from datetime import date, datetime, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import demo_data
import generate_report
import render_html

PROJECT_DIR = Path(__file__).parent.resolve()
WEB_DIR = PROJECT_DIR / "web"
ASSETS_DIR = PROJECT_DIR / "assets"
DB_PATH = PROJECT_DIR / "garmin_data.db"
DEMO_DB_PATH = PROJECT_DIR / "output" / "demo.db"
SETTINGS_PATH = PROJECT_DIR / "settings.json"

# Tope de la subida por drag & drop: una BD de años de histórico ronda las
# decenas de MB, y el cuerpo entero se lee en memoria.
MAX_UPLOAD_BYTES = 256 * 1024 * 1024
# Una sesión 2FA a medias guarda un cliente de Garmin en memoria: se caduca sola.
MFA_SESSION_TTL_S = 600

# Estado global en memoria para sincronización en segundo plano y sesiones 2FA
_sync_state = {
    "status": "idle",       # "idle", "running", "completed", "error"
    "message": "",
    "started_at": None,
    "finished_at": None,
    "error": None,
}
_sync_lock = threading.Lock()

# Almacén de sesiones 2FA temporales: session_id -> {"client": GarminClient, "continuation": ..., "created_at": ...}
_mfa_sessions = {}
_mfa_lock = threading.Lock()


def load_settings() -> dict:
    defaults = {
        "sleep_target_hours": 8.0,
        "steps_daily_goal": 10000,
        "intensity_weekly_goal": 300,
        "theme": "light",
        "language": "en",
    }
    if SETTINGS_PATH.exists():
        try:
            saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            defaults.update(saved)
        except Exception:
            pass
    return defaults


# Rango admitido de cada objetivo numérico: fuera de él el valor se ignora.
_GOAL_LIMITS = {
    "sleep_target_hours": (float, 4.0, 12.0),
    "steps_daily_goal": (int, 1000, 100000),
    "intensity_weekly_goal": (int, 30, 2000),
}


def save_settings(data: dict) -> dict:
    current = load_settings()
    for k, (cast, lo, hi) in _GOAL_LIMITS.items():
        if k in data:
            try:
                v = cast(data[k])
            except (TypeError, ValueError):
                continue
            if lo <= v <= hi:
                current[k] = v
    for k in ("theme", "language"):
        if isinstance(data.get(k), str):
            current[k] = data[k]
    SETTINGS_PATH.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    return current


def report_goals() -> dict:
    """Objetivos personales que el informe usa (los Ajustes del panel)."""
    st = load_settings()
    return {k: st[k] for k in ("sleep_target_hours", "steps_daily_goal", "intensity_weekly_goal") if k in st}


def get_db_date_range(db_file: Path) -> tuple[date | None, date | None]:
    """Obtiene la fecha mínima y máxima con registros en la BD SQLite."""
    if not db_file.exists():
        return None, None
    try:
        conn = sqlite3.connect(db_file)
        cur = conn.cursor()
        min_date, max_date = None, None

        # Comprobar tabla days o sleep
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if "days" in tables:
            r = cur.execute("SELECT MIN(day), MAX(day) FROM days WHERE day IS NOT NULL").fetchone()
            if r and r[0] and r[1]:
                min_date = date.fromisoformat(str(r[0]))
                max_date = date.fromisoformat(str(r[1]))
        elif "sleep" in tables:
            r = cur.execute("SELECT MIN(calendar_date), MAX(calendar_date) FROM sleep WHERE calendar_date IS NOT NULL").fetchone()
            if r and r[0] and r[1]:
                min_date = date.fromisoformat(str(r[0]))
                max_date = date.fromisoformat(str(r[1]))
        conn.close()
        return min_date, max_date
    except Exception:
        return None, None


def get_available_weeks(db_file: Path, lang: str = "en") -> list[dict]:
    """Devuelve la lista de semanas ISO disponibles en la BD."""
    min_d, max_d = get_db_date_range(db_file)
    if not min_d or not max_d:
        return []

    # Alinear al lunes previo del min_d y al domingo siguiente del max_d
    start_monday = min_d - timedelta(days=min_d.weekday())
    end_sunday = max_d + timedelta(days=6 - max_d.weekday())

    months = generate_report.MONTHS_SHORT.get(lang, generate_report.MONTHS_SHORT["en"])
    week_tag = "Semana" if lang == "es" else "Week"

    weeks = []
    curr_start = end_sunday - timedelta(days=6)
    while curr_start >= start_monday:
        curr_end = curr_start + timedelta(days=6)
        iso_year, iso_week, _ = curr_start.isocalendar()
        label = f"{curr_start.day} {months[curr_start.month]} – {curr_end.day} {months[curr_end.month]} {curr_end.year} ({week_tag} {iso_week})"
        weeks.append({
            "label": label,
            "start": curr_start.isoformat(),
            "end": curr_end.isoformat(),
            "year": iso_year,
            "week": iso_week,
        })
        curr_start -= timedelta(days=7)
    return weeks


def check_garmin_auth() -> bool:
    """Comprueba si existen tokens de autenticación de Garmin en el sistema."""
    token_dir = Path.home() / ".garminconnect"
    if not token_dir.exists():
        return False
    for p in token_dir.rglob("garmin_tokens.json"):
        if p.is_file() and p.stat().st_size > 10:
            return True
    return False


def _purge_mfa_sessions():
    """Tira las sesiones 2FA que nadie completó."""
    cutoff = time.time() - MFA_SESSION_TTL_S
    with _mfa_lock:
        for sid in [k for k, v in _mfa_sessions.items() if v["created_at"] < cutoff]:
            del _mfa_sessions[sid]


class BioDeltaRequestHandler(BaseHTTPRequestHandler):
    server_version = "BioDeltaServer/1.0"

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html_str: str, status: int = 200):
        body = html_str.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, file_path: Path, content_type: str):
        if not file_path.exists() or not file_path.is_file():
            self.send_error(404, "File Not Found")
            return
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _same_origin(self) -> bool:
        """Rechaza peticiones nacidas en otra web.

        El servidor escucha en 127.0.0.1, pero cualquier página abierta en el
        navegador puede llegar hasta aquí. Sin CORS no puede leer la respuesta,
        y este filtro impide además que dispare una sincronización o sobrescriba
        la base de datos a espaldas del usuario.
        """
        origin = self.headers.get("Origin")
        if origin is None:
            return True  # navegación directa o cliente sin navegador (curl, tests)
        host = urlparse(origin).hostname
        return host in ("localhost", "127.0.0.1", "::1")

    def do_GET(self):
        if not self._same_origin():
            self.send_error(403, "Forbidden")
            return
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # 1. Rutas de Interfaz Web y Estáticos
        if path in ("/", "/index.html"):
            index_path = WEB_DIR / "index.html"
            if index_path.exists():
                self._send_file(index_path, "text/html; charset=utf-8")
            else:
                self._serve_fallback_ui()
            return

        if path.startswith("/web/"):
            rel_path = path[5:].lstrip("/")
            target = (WEB_DIR / rel_path).resolve()
            if str(target).startswith(str(WEB_DIR.resolve())) and target.exists():
                ext = target.suffix.lower()
                ctype = {
                    ".css": "text/css; charset=utf-8",
                    ".js": "application/javascript; charset=utf-8",
                    ".html": "text/html; charset=utf-8",
                    ".png": "image/png",
                    ".svg": "image/svg+xml",
                    ".jpg": "image/jpeg",
                    ".ico": "image/x-icon",
                }.get(ext, "application/octet-stream")
                self._send_file(target, ctype)
                return
            self.send_error(404, "Static file not found")
            return

        if path.startswith("/assets/"):
            rel_path = path[8:].lstrip("/")
            target = (ASSETS_DIR / rel_path).resolve()
            if str(target).startswith(str(ASSETS_DIR.resolve())) and target.exists():
                ext = target.suffix.lower()
                ctype = {
                    ".png": "image/png",
                    ".svg": "image/svg+xml",
                    ".jpg": "image/jpeg",
                }.get(ext, "application/octet-stream")
                self._send_file(target, ctype)
                return
            self.send_error(404, "Asset not found")
            return

        # 2. Rutas de la API REST
        if path == "/api/status":
            self.handle_get_status(query)
            return

        if path == "/api/weeks":
            self.handle_get_weeks(query)
            return

        if path == "/api/report":
            self.handle_get_report(query)
            return

        if path == "/api/sync/status":
            with _sync_lock:
                self._send_json(dict(_sync_state))
            return

        if path == "/api/demo":
            self.handle_get_demo(query)
            return

        if path == "/api/settings":
            self._send_json({"status": "ok", "settings": load_settings()})
            return

        if path == "/api/glossary":
            lang = query.get("lang", ["en"])[0]
            glossary_data = render_html.METRIC_EXPLANATIONS.get(lang, render_html.METRIC_EXPLANATIONS["en"])
            self._send_json({"status": "ok", "glossary": glossary_data})
            return

        self.send_error(404, "Endpoint not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if not self._same_origin():
            self._send_json({"status": "error", "message": "Origen no permitido."}, 403)
            return

        # Parsear cuerpo JSON o Multipart
        content_type = self.headers.get("Content-Type", "")
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len > MAX_UPLOAD_BYTES:
            self._send_json({"status": "error", "message": "El archivo supera el tamaño máximo admitido."}, 413)
            return
        body = self.rfile.read(content_len) if content_len > 0 else b""

        post_data = {}
        if "application/json" in content_type and body:
            try:
                post_data = json.loads(body.decode("utf-8"))
            except Exception as e:
                self._send_json({"status": "error", "message": f"JSON inválido: {e}"}, 400)
                return

        if path == "/api/sync":
            self.handle_post_sync(post_data)
            return

        if path == "/api/auth":
            self.handle_post_auth(post_data)
            return

        if path == "/api/auth/mfa":
            self.handle_post_auth_mfa(post_data)
            return

        if path == "/api/upload":
            self.handle_post_upload(body, content_type)
            return

        if path == "/api/settings":
            saved = save_settings(post_data)
            self._send_json({"status": "ok", "settings": saved})
            return

        self.send_error(404, "Endpoint not found")

    # -----------------------------------------------------------------------
    # Manejadores de la API
    # -----------------------------------------------------------------------

    def handle_get_status(self, query: dict = None):
        lang = (query or {}).get("lang", ["en"])[0]
        has_db = DB_PATH.exists() and DB_PATH.stat().st_size > 0
        min_d, max_d = get_db_date_range(DB_PATH) if has_db else (None, None)
        weeks = get_available_weeks(DB_PATH, lang=lang) if has_db else []
        has_tokens = check_garmin_auth()
        garmin_exec = generate_report.garmin_bin()

        self._send_json({
            "status": "ok",
            "has_db": has_db,
            "db_size_bytes": DB_PATH.stat().st_size if has_db else 0,
            "has_tokens": has_tokens,
            "has_garmin_bin": garmin_exec is not None,
            "garmin_bin_path": garmin_exec,
            "date_range": {
                "min": min_d.isoformat() if min_d else None,
                "max": max_d.isoformat() if max_d else None,
                "days": (max_d - min_d).days + 1 if (min_d and max_d) else 0,
            },
            "available_weeks_count": len(weeks),
            "demo_available": True,
            "settings": load_settings(),
        })

    def handle_get_weeks(self, query: dict = None):
        lang = (query or {}).get("lang", ["en"])[0]
        has_db = DB_PATH.exists() and DB_PATH.stat().st_size > 0
        target_db = DB_PATH if has_db else DEMO_DB_PATH
        if not target_db.exists():
            DEMO_DB_PATH.parent.mkdir(exist_ok=True)
            demo_data.build(DEMO_DB_PATH)
            target_db = DEMO_DB_PATH

        weeks = get_available_weeks(target_db, lang=lang)
        min_d, max_d = get_db_date_range(target_db)
        self._send_json({
            "status": "ok",
            "is_demo": target_db == DEMO_DB_PATH,
            "min_date": min_d.isoformat() if min_d else None,
            "max_date": max_d.isoformat() if max_d else None,
            "weeks": weeks,
        })

    def handle_get_report(self, query: dict):
        lang = query.get("lang", ["en"])[0]
        is_demo = query.get("demo", ["0"])[0] in ("1", "true")
        start_str = query.get("start", [None])[0]
        end_str = query.get("end", [None])[0]

        has_db = DB_PATH.exists() and DB_PATH.stat().st_size > 0
        if is_demo or not has_db:
            target_db = DEMO_DB_PATH
            target_db.parent.mkdir(exist_ok=True)
            if not target_db.exists():
                demo_data.build(target_db)
            generated_on = demo_data.GENERATED_ON
            notice = "Sample report with synthetic data: does not correspond to any real person." if lang == "en" else "Informe de ejemplo con datos sintéticos: no corresponde a ninguna persona real."
            if not start_str or not end_str:
                start, end = demo_data.REPORT_START, demo_data.REPORT_END
            else:
                start = generate_report.parse_date(start_str)
                end = generate_report.parse_date(end_str)
        else:
            target_db = DB_PATH
            generated_on = date.today()
            notice = ""
            if not start_str or not end_str:
                min_d, max_d = get_db_date_range(DB_PATH)
                if max_d:
                    end = max_d
                    start = end - timedelta(days=6)
                else:
                    start, end = generate_report.last_week_range()
            else:
                start = generate_report.parse_date(start_str)
                end = generate_report.parse_date(end_str)

        try:
            conn = sqlite3.connect(target_db)
            try:
                _md, html_content = generate_report.build_report(
                    conn, start, end, generated_on, notice, lang=lang,
                    goals=report_goals(), standalone=False)
            finally:
                conn.close()

            prev_start = start - timedelta(days=7)
            prev_end = end - timedelta(days=7)
            next_start = start + timedelta(days=7)
            next_end = end + timedelta(days=7)

            self._send_json({
                "status": "ok",
                "is_demo": target_db == DEMO_DB_PATH,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "title": generate_report.title_range(start, end, lang=lang),
                "prev_week": {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
                "next_week": {"start": next_start.isoformat(), "end": next_end.isoformat()},
                "html": html_content,
            })
        except Exception as e:
            self._send_json({"status": "error", "message": f"Error al generar informe: {str(e)}"}, 500)

    def handle_get_demo(self, query: dict = None):
        lang = (query or {}).get("lang", ["en"])[0]
        DEMO_DB_PATH.parent.mkdir(exist_ok=True)
        DEMO_DB_PATH.unlink(missing_ok=True)
        start, end = demo_data.build(DEMO_DB_PATH)
        conn = sqlite3.connect(DEMO_DB_PATH)
        notice = "Sample report with synthetic data: does not correspond to any real person." if lang == "en" else "Informe de ejemplo con datos sintéticos: no corresponde a ninguna persona real."
        try:
            _md, html_content = generate_report.build_report(
                conn, start, end, demo_data.GENERATED_ON, notice, lang=lang,
                goals=report_goals(), standalone=False)
        finally:
            conn.close()

        msg = "Demo environment generated successfully" if lang == "en" else "Entorno de demostración generado con éxito"
        self._send_json({
            "status": "ok",
            "is_demo": True,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "title": generate_report.title_range(start, end, lang=lang),
            "html": html_content,
            "message": msg,
        })


    def handle_post_sync(self, data: dict):
        with _sync_lock:
            if _sync_state["status"] == "running":
                self._send_json({"status": "already_running", "message": "Ya hay una sincronización en curso."}, 409)
                return

            _sync_state["status"] = "running"
            _sync_state["message"] = "Iniciando sincronización con Garmin Connect..."
            _sync_state["started_at"] = datetime.now().isoformat()
            _sync_state["finished_at"] = None
            _sync_state["error"] = None

        start_str = data.get("start_date")
        end_str = data.get("end_date")
        start_d = generate_report.parse_date(start_str) if start_str else None
        end_d = generate_report.parse_date(end_str) if end_str else None

        def run_background_sync():
            try:
                with _sync_lock:
                    _sync_state["message"] = "Conectando con Garmin Connect y extrayendo métricas..."
                generate_report.sync(start_d, end_d)
                with _sync_lock:
                    _sync_state["status"] = "completed"
                    _sync_state["message"] = "Sincronización completada con éxito."
                    _sync_state["finished_at"] = datetime.now().isoformat()
            except Exception as e:
                with _sync_lock:
                    _sync_state["status"] = "error"
                    _sync_state["message"] = f"Error en la sincronización: {str(e)}"
                    _sync_state["error"] = str(e)
                    _sync_state["finished_at"] = datetime.now().isoformat()

        t = threading.Thread(target=run_background_sync, daemon=True)
        t.start()
        self._send_json({"status": "started", "message": "Sincronización iniciada en segundo plano."})

    def handle_post_auth(self, data: dict):
        email = data.get("email", "").strip()
        password = data.get("password", "").strip()

        if not email or not password:
            self._send_json({"status": "error", "message": "Introduce email y contraseña de Garmin."}, 400)
            return

        try:
            from garmin_health_data.garmin_client import GarminClient
        except ImportError:
            self._send_json({"status": "error", "message": "Librería garmin-health-data no instalada en el entorno."}, 500)
            return

        _purge_mfa_sessions()
        try:
            client = GarminClient()
            login_result = client.login(email, password, return_on_mfa=True)

            if isinstance(login_result, tuple) and len(login_result) == 2 and login_result[0] == "needs_mfa":
                session_id = str(uuid.uuid4())
                with _mfa_lock:
                    _mfa_sessions[session_id] = {
                        "client": client,
                        "continuation": login_result[1],
                        "email": email,
                        "created_at": time.time(),
                    }
                self._send_json({
                    "status": "needs_mfa",
                    "session_id": session_id,
                    "message": "Garmin ha solicitado un código de verificación en dos pasos (2FA). Introduce el código recibido por SMS/Email.",
                })
                return

            self._finalize_garmin_tokens(client)
            self._send_json({
                "status": "ok",
                "message": "¡Autenticación completada con éxito! Ya puedes sincronizar tus datos.",
            })
        except Exception as e:
            self._send_json({"status": "error", "message": f"Fallo al autenticar con Garmin: {str(e)}"}, 400)

    def handle_post_auth_mfa(self, data: dict):
        session_id = data.get("session_id", "").strip()
        code = data.get("code", "").strip()

        if not session_id or not code:
            self._send_json({"status": "error", "message": "Se requiere session_id y código 2FA."}, 400)
            return

        _purge_mfa_sessions()
        with _mfa_lock:
            session = _mfa_sessions.pop(session_id, None)

        if not session:
            self._send_json({"status": "error", "message": "Sesión 2FA caducada o no encontrada. Inicia sesión de nuevo."}, 400)
            return

        client = session["client"]
        continuation = session["continuation"]

        try:
            client.resume_login(continuation, code)
            self._finalize_garmin_tokens(client)
            self._send_json({
                "status": "ok",
                "message": "¡Código 2FA verificado con éxito! Sesión guardada correctamente.",
            })
        except Exception as e:
            self._send_json({"status": "error", "message": f"Código 2FA incorrecto o expirado: {str(e)}"}, 400)

    def _finalize_garmin_tokens(self, client):
        user_profile = client.get_user_profile()
        user_id = user_profile.get("id") if user_profile else None
        if not user_id:
            raise RuntimeError("No se pudo detectar el ID de usuario de Garmin.")

        base_path = Path.home() / ".garminconnect"
        base_path.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            base_path.chmod(0o700)

        token_path = base_path / str(user_id)
        token_path.mkdir(exist_ok=True)
        if sys.platform != "win32":
            token_path.chmod(0o700)

        client.dump(str(token_path))

    def handle_post_upload(self, raw_body: bytes, content_type: str):
        """Maneja la subida directa de archivos SQLite garmin_data.db mediante drag & drop."""
        try:
            if "multipart/form-data" in content_type:
                if "boundary=" not in content_type:
                    self._send_json({"status": "error", "message": "Petición multipart sin boundary."}, 400)
                    return
                boundary = content_type.split("boundary=")[1].strip('"').encode()
                parts = raw_body.split(b"--" + boundary)
                file_bytes = None
                for part in parts:
                    if b'filename="' in part:
                        headers_part, _, data_part = part.partition(b"\r\n\r\n")
                        file_bytes = data_part.rstrip(b"\r\n")
                        break
                if not file_bytes:
                    self._send_json({"status": "error", "message": "No se encontró ningún archivo en la petición."}, 400)
                    return
            else:
                file_bytes = raw_body

            if not file_bytes.startswith(b"SQLite format 3\x00"):
                self._send_json({"status": "error", "message": "El archivo subido no es una base de datos SQLite válida de Garmin."}, 400)
                return

            # La BD anterior se guarda: subir el archivo equivocado no debe
            # llevarse por delante el histórico ya sincronizado.
            if DB_PATH.exists():
                DB_PATH.replace(DB_PATH.with_suffix(".db.bak"))
            DB_PATH.write_bytes(file_bytes)
            min_d, max_d = get_db_date_range(DB_PATH)
            self._send_json({
                "status": "ok",
                "message": "Base de datos garmin_data.db importada y validada con éxito.",
                "date_range": {
                    "min": min_d.isoformat() if min_d else None,
                    "max": max_d.isoformat() if max_d else None,
                }
            })
        except Exception as e:
            self._send_json({"status": "error", "message": f"Error al procesar el archivo: {str(e)}"}, 500)

    def _serve_fallback_ui(self):
        """Genera una interfaz visual de bienvenida si web/index.html aún no está empaquetado."""
        html = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BioDelta · Servidor Local</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #000; color: #fff; padding: 3rem; text-align: center; }
  .box { max-width: 32rem; margin: 0 auto; background: #1c1c1e; border: 1px solid #333; border-radius: 12px; padding: 2rem; }
  h1 { color: #2997ff; margin-bottom: 0.5rem; }
  p { color: #a1a1a6; line-height: 1.5; }
  a.btn { display: inline-block; background: #2997ff; color: #fff; text-decoration: none; padding: 0.75rem 1.5rem; border-radius: 980px; font-weight: 600; margin-top: 1rem; }
</style>
</head>
<body>
<div class="box">
  <h1>BioDelta</h1>
  <p>Servidor local activo en <code>http://localhost:8000</code>.</p>
  <p>Cargando la interfaz web y conectando con el motor de salud...</p>
  <a class="btn" href="/api/demo">Ver Informe Demo (JSON)</a>
</div>
</body>
</html>"""
        self._send_html(html)


def run_server(port: int = 8000, open_browser: bool = True):
    """Inicia el servidor local en el primer puerto libre a partir de `port`."""
    server = None
    target_port = port
    while target_port < port + 10:
        try:
            server = ThreadingHTTPServer(("127.0.0.1", target_port), BioDeltaRequestHandler)
            break
        except OSError:
            target_port += 1

    if not server:
        print(f"[ERROR] No se pudo vincular a ningún puerto entre {port} y {target_port - 1}", file=sys.stderr)
        sys.exit(1)

    url = f"http://localhost:{target_port}"
    print(f"============================================================")
    print(f"  🟢 BioDelta Servidor Local Activo")
    print(f"  URL: {url}")
    print(f"  Privacidad: 100% local en tu equipo (127.0.0.1)")
    print(f"  Presiona Ctrl+C para detener el servidor")
    print(f"============================================================")

    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDeteniendo servidor BioDelta...")
        server.shutdown()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Servidor local y visor interactivo de BioDelta")
    parser.add_argument("--port", type=int, default=8000, help="Puerto HTTP (por defecto: 8000)")
    parser.add_argument("--no-browser", action="store_true", help="No abrir automáticamente el navegador")
    args = parser.parse_args()

    run_server(port=args.port, open_browser=not args.no_browser)
