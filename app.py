"""쇼츠 편집기 웹 서버.  실행: uvicorn app:app --host 0.0.0.0 --port 8000"""
import json
import logging
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from shorts_editor.config import DATA_DIR, ROOT, Options
from shorts_editor.pipeline import analyze, make_shorts, render_short
from shorts_editor.planner import ShortPlan

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

JOBS_DIR = DATA_DIR / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

app = FastAPI(title="쇼츠 편집기")
executor = ThreadPoolExecutor(max_workers=1)  # 인코딩은 CPU를 많이 써서 한 번에 하나씩
lock = threading.Lock()


def job_dir(job_id: str) -> Path:
    if not job_id.isalnum():
        raise HTTPException(400, "잘못된 작업 ID")
    d = JOBS_DIR / job_id
    if not d.exists():
        raise HTTPException(404, "작업을 찾을 수 없습니다")
    return d


def read_state(d: Path) -> dict:
    return json.loads((d / "state.json").read_text(encoding="utf-8"))


def write_state(d: Path, **updates) -> dict:
    with lock:
        f = d / "state.json"
        state = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        state.update(updates)
        f.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        return state


def run_job(d: Path) -> None:
    state = read_state(d)
    opts = Options.from_dict(state["options"])
    try:
        summary = make_shorts(str(d / state["source"]), d, opts,
                              lambda stage, pct: write_state(d, status="running", stage=stage, progress=pct))
        write_state(d, status="done", stage="완료", progress=1.0, result=summary)
    except Exception as e:
        logging.exception("작업 실패")
        write_state(d, status="error", stage="실패", error=str(e))


@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    count: int = Form(3),
    min_len: float = Form(20),
    max_len: float = Form(45),
    layout: str = Form("blur"),
    use_ai: bool = Form(True),
    teaser: bool = Form(True),
    cut_silence: bool = Form(True),
    zoom_punch: bool = Form(True),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"지원하지 않는 형식입니다: {ext}")
    if layout not in ("blur", "crop") or not (1 <= count <= 10) or not (5 <= min_len <= max_len <= 180):
        raise HTTPException(400, "옵션 값을 확인해 주세요")
    job_id = uuid.uuid4().hex[:12]
    d = JOBS_DIR / job_id
    d.mkdir(parents=True)
    src = d / f"source{ext}"
    with src.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    opts = Options(count=count, min_len=min_len, max_len=max_len, layout=layout, use_ai=use_ai,
                   teaser=teaser, cut_silence=cut_silence, zoom_punch=zoom_punch)
    write_state(d, id=job_id, filename=file.filename, source=src.name, status="queued",
                stage="대기 중", progress=0.0, options=opts.to_dict())
    executor.submit(run_job, d)
    return {"id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return read_state(job_dir(job_id))


class ClipEdit(BaseModel):
    start: float
    end: float
    title: str
    hook_text: str
    highlight_words: list[str] = []
    teaser_start: float = 0.0
    teaser_end: float = 0.0


def run_rerender(d: Path, index: int, plan: ShortPlan) -> None:
    state = read_state(d)
    opts = Options.from_dict(state["options"])
    try:
        src = str(d / state["source"])
        res = render_short(src, d, analyze(src, d, opts), plan, opts, index)
        with lock:
            s = json.loads((d / "state.json").read_text(encoding="utf-8"))
            s["result"]["shorts"][index] = res
            s["rendering"] = [i for i in s.get("rendering", []) if i != index]
            s.pop("error", None)
            (d / "state.json").write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logging.exception("재렌더 실패")
        st = read_state(d)
        write_state(d, rendering=[i for i in st.get("rendering", []) if i != index], error=str(e))


@app.post("/api/jobs/{job_id}/clips/{index}")
def rerender_clip(job_id: str, index: int, edit: ClipEdit):
    d = job_dir(job_id)
    state = read_state(d)
    if state.get("status") != "done":
        raise HTTPException(409, "아직 처리 중입니다")
    shorts = state["result"]["shorts"]
    if not 0 <= index < len(shorts):
        raise HTTPException(404, "클립이 없습니다")
    dur = state["result"]["source_duration"]
    if not 0 <= edit.start < edit.end <= dur + 0.01:
        raise HTTPException(400, "시작/끝 시간을 확인해 주세요")
    old = shorts[index]["plan"]
    plan = ShortPlan(start=edit.start, end=edit.end, title=edit.title, hook_text=edit.hook_text,
                     highlight_words=[w for w in edit.highlight_words if w.strip()],
                     teaser_start=edit.teaser_start, teaser_end=edit.teaser_end,
                     reason=old.get("reason", ""), score=old.get("score", 0))
    if not (plan.start <= plan.teaser_start < plan.teaser_end <= plan.end):
        plan.teaser_start = plan.teaser_end = 0.0
    write_state(d, rendering=sorted(set(state.get("rendering", [])) | {index}))
    executor.submit(run_rerender, d, index, plan)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/files/{name}")
def get_file(job_id: str, name: str):
    d = job_dir(job_id)
    if "/" in name or "\\" in name or not name.startswith("short_") or Path(name).suffix not in (".mp4", ".jpg"):
        raise HTTPException(400, "잘못된 파일")
    f = d / name
    if not f.exists():
        raise HTTPException(404, "파일 없음")
    return FileResponse(f, headers={"Cache-Control": "no-store"})


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
