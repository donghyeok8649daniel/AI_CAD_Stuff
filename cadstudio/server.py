from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .catalog import catalog
from .kernel import export, preview
from .models import Design, DraftRequest, Project, Extrusion
from .constraints import solve_sketch
from .planner import local_draft, openai_draft

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("CADSTUDIO_DATA_DIR", ROOT / "data"))
app = FastAPI(title="Prompt CAD Studio", version=__version__, docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])
shutdown_callback = None


def issues(exc):
    return [{"field": ".".join(str(x) for x in e["loc"]), "message": e["msg"].removeprefix("Value error, ")} for e in exc.errors()]


@app.exception_handler(RequestValidationError)
@app.exception_handler(ValidationError)
async def invalid_request(request, exc):
    return JSONResponse(status_code=422, content={"detail": "입력한 설계 치수를 확인하세요.", "issues": issues(exc)})


@app.middleware("http")
async def local_boundary(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse(status_code=403, content={"detail": "다른 사이트에서는 이 로컬 CAD 앱에 요청할 수 없습니다."})
        if request.headers.get("x-cad-request") != "1":
            return JSONResponse(status_code=403, content={"detail": "CAD 요청 헤더가 필요합니다."})
        # Enforce the actual streamed size, not just a client-supplied Content-Length.
        size, chunks = 0, []
        async for chunk in request.stream():
            size += len(chunk)
            if size > 1_000_000:
                return JSONResponse(status_code=413, content={"detail": "설계 파일은 1 MB 이하여야 합니다."})
            chunks.append(chunk)
        request._body = b"".join(chunks)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/status")
def status():
    import cadquery
    return {"app": "prompt-cad-studio", "version": __version__, "kernel": f"CadQuery {cadquery.__version__} / Open CASCADE", "api_configured": bool(os.getenv("OPENAI_API_KEY")), "model": os.getenv("OPENAI_MODEL", "gpt-4.1"), "units": "mm"}


@app.get("/api/catalog")
def get_catalog():
    return catalog()


@app.post("/api/shutdown")
def shutdown():
    if shutdown_callback is None:
        raise HTTPException(409, "터미널에서 실행한 서버는 해당 터미널에서 종료하세요.")
    shutdown_callback()
    return {"stopped": True}


@app.get("/api/schema")
def get_schema():
    return Design.model_json_schema()


def checked_preview(design):
    try:
        return preview(design)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except Exception:
        logging.getLogger(__name__).exception("CAD build failed")
        raise HTTPException(422, "이 치수 조합으로 형상을 만들지 못했습니다. 치수를 조정해 주세요.") from None


@app.post("/api/build")
def build_design(design: Design):
    return {"design": design.model_dump(), **checked_preview(design)}


@app.post("/api/sketch/solve")
def solve_sketch_constraints(sketch: Extrusion):
    return {"sketch":sketch.model_dump(),"status":solve_sketch(sketch.points,sketch.constraints)[1]}


@app.post("/api/draft")
def draft(request: DraftRequest):
    try:
        result = openai_draft(request) if request.provider == "openai" else local_draft(request)
        design = Design.model_validate(result["design"])
        return {**result, **checked_preview(design)}
    except (ValueError, ValidationError) as exc:
        if isinstance(exc, ValidationError):
            return JSONResponse(status_code=422, content={"detail": "설계 초안의 치수를 확인하세요.", "issues": issues(exc)})
        raise HTTPException(422, str(exc)) from None
    except HTTPException:
        raise
    except Exception:
        # Provider exceptions may contain request bodies, headers or secrets: never echo them.
        raise HTTPException(502, "AI 요청을 완료하지 못했습니다. API 키 권한, 모델 이름, 사용 한도와 네트워크를 확인하세요.") from None


@app.post("/api/export/{fmt}")
def export_design(fmt: str, design: Design):
    if fmt == "autodesk":
        from .native_export import conversion_package
        try:
            payload=conversion_package(design)
        except Exception:
            raise HTTPException(422, "변환 패키지를 만들지 못했습니다. 형상과 치수를 확인하세요.") from None
        return Response(payload, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="Autodesk-conversion.zip"'})
    if fmt not in {"step", "stl"}:
        raise HTTPException(404, "지원하지 않는 파일 형식입니다.")
    with tempfile.TemporaryDirectory(prefix="prompt-cad-") as directory:
        path = Path(directory) / f"design.{fmt}"
        try:
            export(design, path, fmt)
        except Exception:
            raise HTTPException(422, "내보내기에 실패했습니다. 형상과 치수를 확인하세요.") from None
        return Response(path.read_bytes(), media_type="application/octet-stream", headers={"Content-Disposition": f'attachment; filename="design.{fmt}"'})


def project_path(identifier):
    if not re.fullmatch(r"[0-9a-f]{32}", identifier):
        raise HTTPException(404, "프로젝트를 찾지 못했습니다.")
    return DATA / "projects" / f"{identifier}.json"


@app.get("/api/projects")
def list_projects():
    directory = DATA / "projects"
    if not directory.exists():
        return []
    entries = []
    for path in sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:200]:
        try:
            saved = Project.model_validate_json(path.read_text(encoding="utf-8"))
            entries.append({"id": path.stem, "name": saved.design.name, "mode": saved.design.mode, "parts": len(saved.design.parts), "modified": path.stat().st_mtime})
        except (ValueError, OSError):
            continue
    return entries


@app.get("/api/projects/{identifier}")
def load_project(identifier: str):
    path = project_path(identifier)
    if not path.exists():
        raise HTTPException(404, "프로젝트를 찾지 못했습니다.")
    return Project.model_validate_json(path.read_text(encoding="utf-8")).model_dump()


def store_project(identifier, project):
    checked_preview(project.design)
    path = project_path(identifier)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(project.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return {"id": identifier, "name": project.design.name}


@app.post("/api/projects")
def save_project(project: Project):
    return store_project(uuid.uuid4().hex, project)


@app.put("/api/projects/{identifier}")
def update_project(identifier: str, project: Project):
    if not project_path(identifier).exists():
        raise HTTPException(404, "프로젝트를 찾지 못했습니다.")
    return store_project(identifier, project)


@app.post("/api/projects/validate")
def validate_project(project: Project):
    return {"project": project.model_dump(), **checked_preview(project.design)}


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")
