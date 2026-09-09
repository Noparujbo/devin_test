import secrets
import string
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, field_validator

from app.db import get_conn, init_db

ALPHABET = string.ascii_lowercase + string.digits
CODE_LENGTH = 6
RESERVED = {"api", "healthz", "static", "favicon.ico", "docs", "openapi.json", "redoc"}
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="URL Shortener", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def generate_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


class ShortenRequest(BaseModel):
    url: str
    custom_code: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.strip()
        if "://" not in value:
            value = "https://" + value
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("URL must be a valid http(s) URL")
        return value

    @field_validator("custom_code")
    @classmethod
    def validate_code(cls, value: str | None) -> str | None:
        if value is None or value.strip() == "":
            return None
        value = value.strip()
        if not all(c.isalnum() or c in "-_" for c in value):
            raise ValueError("Custom code may only contain letters, digits, - and _")
        if len(value) > 32 or value.lower() in RESERVED:
            raise ValueError("Custom code is not allowed")
        return value


def link_payload(row, base_url: str) -> dict:
    return {
        "code": row["code"],
        "long_url": row["long_url"],
        "short_url": f"{base_url}/{row['code']}",
        "created_at": row["created_at"],
        "click_count": row["click_count"],
        "last_clicked_at": row["last_clicked_at"],
    }


def base_url_of(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@app.post("/api/shorten")
def shorten(payload: ShortenRequest, request: Request) -> dict:
    with get_conn() as conn:
        if payload.custom_code:
            code = payload.custom_code
            if conn.execute("SELECT 1 FROM links WHERE code = ?", (code,)).fetchone():
                raise HTTPException(status_code=409, detail="That code is already taken")
        else:
            for _ in range(10):
                code = generate_code()
                if not conn.execute("SELECT 1 FROM links WHERE code = ?", (code,)).fetchone():
                    break
            else:
                raise HTTPException(status_code=500, detail="Could not allocate a short code")
        conn.execute(
            "INSERT INTO links (code, long_url, created_at, click_count) VALUES (?, ?, ?, 0)",
            (code, payload.url, now_iso()),
        )
        row = conn.execute("SELECT * FROM links WHERE code = ?", (code,)).fetchone()
    return link_payload(row, base_url_of(request))


@app.get("/api/links")
def list_links(request: Request) -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM links ORDER BY created_at DESC").fetchall()
    base = base_url_of(request)
    return {"links": [link_payload(row, base) for row in rows]}


@app.get("/api/links/{code}/clicks")
def link_clicks(code: str, request: Request) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM links WHERE code = ?", (code,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Short code not found")
        clicks = conn.execute(
            "SELECT clicked_at, referer, user_agent FROM clicks WHERE code = ? ORDER BY clicked_at DESC LIMIT 100",
            (code,),
        ).fetchall()
    return {
        "link": link_payload(row, base_url_of(request)),
        "clicks": [dict(click) for click in clicks],
    }


@app.delete("/api/links/{code}")
def delete_link(code: str) -> dict:
    with get_conn() as conn:
        cursor = conn.execute("DELETE FROM links WHERE code = ?", (code,))
        conn.execute("DELETE FROM clicks WHERE code = ?", (code,))
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Short code not found")
    return {"deleted": code}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/{code}")
def follow(code: str, request: Request):
    if code in RESERVED:
        raise HTTPException(status_code=404, detail="Not found")
    with get_conn() as conn:
        row = conn.execute("SELECT long_url FROM links WHERE code = ?", (code,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Short code not found")
        timestamp = now_iso()
        conn.execute(
            "UPDATE links SET click_count = click_count + 1, last_clicked_at = ? WHERE code = ?",
            (timestamp, code),
        )
        conn.execute(
            "INSERT INTO clicks (code, clicked_at, referer, user_agent) VALUES (?, ?, ?, ?)",
            (code, timestamp, request.headers.get("referer"), request.headers.get("user-agent")),
        )
    return RedirectResponse(row["long_url"], status_code=307)
