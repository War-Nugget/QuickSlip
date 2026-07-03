"""
Endpoints:
  POST /api/upload           -> upload a file, get back a short code
  GET  /api/status/{code}    -> check whether a code is valid (and time left)
  GET  /api/download/{code}  -> download the file for a code
  GET  /                     -> single-page frontend (upload + retrieve)
"""
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import codes, config
from .store import create_store

CHUNK_SIZE = 1024 * 1024  # 1 MB read chunks during upload


# ---------------------------------------------------------------------------
# App lifecycle: connect the metadata store, start the janitor task
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.store, backend = await create_store()
    print(f"[quickslip] metadata store: {backend}")
    janitor = asyncio.create_task(cleanup_orphans_forever())
    yield
    janitor.cancel()


app = FastAPI(title="QuickSlip", lifespan=lifespan)


async def cleanup_orphans_forever():
    """Safety net: delete files on disk older than TTL whose metadata expired.

    Redis TTL removes the *code*, but the bytes on disk still need removal
    if the file was never downloaded. Runs once a minute.
    """
    while True:
        try:
            if config.UPLOAD_DIR.exists():
                import time
                cutoff = time.time() - config.FILE_TTL_SECONDS - 60
                for f in config.UPLOAD_DIR.iterdir():
                    if f.is_file() and f.stat().st_mtime < cutoff:
                        f.unlink(missing_ok=True)
        except Exception as exc:  # never let the janitor die
            print(f"[quickslip] janitor error: {exc}")
        await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# Rate limiting helper (per-IP wrong-guess limiting on the download side)
# ---------------------------------------------------------------------------
async def check_rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    key = f"rl:{ip}"
    count = await request.app.state.store.incr_with_ttl(key, config.RATE_LIMIT_WINDOW)
    if count > config.RATE_LIMIT_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please wait a minute and try again.",
        )


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------
@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    dest = codes.new_file_path()
    size = 0
    try:
        with open(dest, "wb") as out:
            while chunk := await file.read(CHUNK_SIZE):
                size += len(chunk)
                if size > config.MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large (max {config.MAX_FILE_SIZE // (1024*1024)} MB).",
                    )
                out.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except Exception:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Upload failed. Please try again.")

    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Empty file.")

    # Generate a code; retry on the (unlikely) collision
    store = app.state.store
    for _ in range(5):
        code = codes.generate_code()
        if await store.get(f"file:{code}") is None:
            break
    else:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Could not generate a code. Try again.")

    await store.set(
        f"file:{code}",
        {
            "path": str(dest),
            "filename": codes.safe_filename(file.filename),
            "size": size,
            "content_type": file.content_type or "application/octet-stream",
        },
        ttl=config.FILE_TTL_SECONDS,
    )

    return {
        "code": code,
        "expires_in": config.FILE_TTL_SECONDS,
        "filename": codes.safe_filename(file.filename),
        "size": size,
    }


# ---------------------------------------------------------------------------
# Status check (lets the frontend validate a code before redirecting)
# ---------------------------------------------------------------------------
@app.get("/api/status/{code}")
async def status(code: str, request: Request):
    await check_rate_limit(request)
    code = codes.normalize_code(code)
    store = app.state.store
    meta = await store.get(f"file:{code}")
    if meta is None:
        raise HTTPException(status_code=404, detail="Code not found or expired.")
    ttl = await store.ttl(f"file:{code}")
    return {
        "filename": meta["filename"],
        "size": meta["size"],
        "expires_in": max(ttl, 0),
    }


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
@app.get("/api/download/{code}")
async def download(code: str, request: Request):
    await check_rate_limit(request)
    code = codes.normalize_code(code)
    store = app.state.store
    meta = await store.get(f"file:{code}")
    if meta is None:
        raise HTTPException(status_code=404, detail="Code not found or expired.")

    path = Path(meta["path"])
    if not path.exists():
        await store.delete(f"file:{code}")
        raise HTTPException(status_code=410, detail="File is no longer available.")

    if config.DELETE_AFTER_DOWNLOAD:
        # Invalidate the code immediately; delete bytes after the response is sent.
        await store.delete(f"file:{code}")
        background = _delete_file_later(path)
    else:
        background = None

    return FileResponse(
        path,
        media_type=meta["content_type"],
        filename=meta["filename"],
        background=background,
    )


def _delete_file_later(path: Path):
    from starlette.background import BackgroundTask

    def _rm():
        path.unlink(missing_ok=True)

    return BackgroundTask(_rm)


# ---------------------------------------------------------------------------
# Frontend (static single page)
# ---------------------------------------------------------------------------
static_dir = Path(__file__).parent.parent / "static"
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return FileResponse(static_dir / "index.html")
