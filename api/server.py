from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks
    from fastapi.responses import StreamingResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
except ImportError:
    raise ImportError("FastAPI and pydantic required for API server. pip install fastapi uvicorn")

# --- App setup
app = FastAPI(title="XBRL Validator API", version="1.0.0")
_executor = ThreadPoolExecutor(max_workers=2)

# Serve lightweight UI
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")

@app.get("/")
async def root_index():
    if STATIC_DIR.exists():
        return RedirectResponse(url="/ui/")
    return {"message": "XBRL Validator API running"}


@app.get("/about")
async def about():
    info: Dict[str, Any] = {"apiVersion": app.version}
    # Try to expose Arelle version
    try:
        import arelle.PackageManager  # type: ignore
        info["arelle"] = "available"
    except Exception:
        info["arelle"] = "unavailable"
    try:
        import platform
        info["python"] = platform.python_version()
    except Exception:
        pass
    # Attach build metadata if present
    try:
        meta_path = Path("artifacts/arelle.json")
        if meta_path.exists():
            info["arelleMeta"] = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    # License status (non-sensitive)
    try:
        from xbrl_validator.license import get_license_status
        st = get_license_status()
        info["license"] = {"state": st.state, "edition": st.edition, "expires": st.expires}
    except Exception:
        info["license"] = {"state": "unknown"}
    return info


# In-memory job store (use Redis/DB for production)
jobs: Dict[str, Dict[str, Any]] = {}


# --- Models
class ValidationRequest(BaseModel):
    file_path: str
    taxonomy_packages: Optional[List[str]] = None  # explicit package/entry paths
    eba_version: Optional[str] = None  # mutually exclusive with taxonomy_packages
    plugins: str = "formula"
    offline: bool = False
    severity_exit: Optional[str] = None
    calc_decimals: bool = False
    calc_precision: bool = False
    dpm_sqlite: Optional[str] = "assets/dpm.sqlite"
    dpm_schema: Optional[str] = "dpm35_10"
    fail_on_warnings: bool = False


class JobStatus(BaseModel):
    job_id: str
    status: str  # pending, running, completed, failed, cancelled
    created_at: str
    completed_at: Optional[str] = None
    return_code: Optional[int] = None
    summary: Optional[Dict[str, Any]] = None
    log_path: Optional[str] = None


# --- Simple CLI job endpoints (kept for compatibility)
@app.post("/validate", response_model=JobStatus)
async def submit_validation(request: ValidationRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "request": request.dict(),
        "completed_at": None,
        "return_code": None,
        "summary": None,
        "log_path": None,
    }
    jobs[job_id] = job
    background_tasks.add_task(_run_cli_validation_job, job_id, request)
    return JobStatus(**job)


@app.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    return JobStatus(**{k: v for k, v in job.items() if k in JobStatus.__fields__})


@app.get("/jobs", response_model=List[JobStatus])
async def list_jobs():
    return [JobStatus(**{k: v for k, v in job.items() if k in JobStatus.__fields__}) for job in jobs.values()]


@app.get("/jobs/{job_id}/log")
async def get_job_log(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    log_path = job.get("log_path")
    if not log_path or not Path(log_path).exists():
        raise HTTPException(status_code=404, detail="Log not found")
    return {"log_path": log_path, "content": Path(log_path).read_text(encoding="utf-8")}


# --- Workflow (live) endpoints
class WorkflowRequest(BaseModel):
    instance_file: str = str(Path("extra_data/sample_instances_architecture_1.0/xBRL_XML/DUMMYLEI123456789012.CON_FR_DORA010000_DORA_2025-01-31_20240625161151000.xbrl").resolve())
    taxonomy_packages: Optional[List[str]] = None
    eba_version: Optional[str] = "3.5"
    dpm_sqlite: Optional[str] = str(Path("assets/dpm.sqlite").resolve())
    dpm_schema: Optional[str] = "dpm35_10"
    fail_on_warnings: bool = False
    plugins: str = "formula"
    offline: bool = False
    calc_decimals: bool = False
    apply_filing_rules: bool = True
    filing_rules_excel: Optional[str] = None


@app.post("/workflow/run")
async def workflow_run(request: WorkflowRequest):
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "completed_at": None,
        "return_code": None,
        "summary": None,
        "log_path": None,
        "events_queue": asyncio.Queue(),
        "cancel_event": asyncio.Event(),
        "exports_dir": str(Path("exports") / job_id),
    }
    asyncio.create_task(_run_workflow(job_id, request))
    return {"job_id": job_id}


class SummarizeRequest(BaseModel):
    texts: List[str]
    severity: Optional[str] = None
    language: Optional[str] = "en"
    api_key: Optional[str] = None  # per-request key; not persisted


@app.post("/summarize")
async def summarize(req: SummarizeRequest):
    """Summarize a set of error/warning messages into a short, plain-language explanation.
    Requires OPENAI_API_KEY in environment. Never stores the key server-side.
    """
    api_key = req.api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not set in environment")
    prompt = (
        "Summarize the following XBRL validation messages into a brief, clear explanation for a business user. "
        "Avoid jargon. 2-3 sentences max. If there are missing files or unresolved taxonomy references, suggest the next action (e.g., add package or disable offline). "
        "Language: " + (req.language or "en") + ".\n\nMessages:\n" + "\n".join(req.texts[:20])
    )
    try:
        import requests  # already in requirements
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "You are a concise assistant for summarizing validation errors in plain language."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 180,
        }
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"OpenAI API error: {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return {"summary": text.strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/workflow/{job_id}/events")
async def workflow_events(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    queue: asyncio.Queue = jobs[job_id]["events_queue"]

    async def event_stream() -> AsyncGenerator[bytes, None]:
        # Initial heartbeat
        yield b"event: ping\ndata: {}\n\n"
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                yield b"event: ping\ndata: {}\n\n"
                continue
            if item is None:
                break
            payload = json.dumps(item, ensure_ascii=False)
            yield f"data: {payload}\n\n".encode("utf-8")

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/workflow/{job_id}/cancel")
async def workflow_cancel(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    jobs[job_id]["cancel_event"].set()
    # Try to kill running process if present
    proc: Optional[subprocess.Popen] = jobs[job_id].get("proc")
    if proc and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass
    jobs[job_id]["status"] = "cancelled"
    return {"ok": True}


@app.get("/workflow/{job_id}/summary")
async def workflow_summary(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = jobs[job_id]
    return {
        "job_id": job_id,
        "status": job.get("status"),
        "summary": job.get("summary"),
        "exports_dir": job.get("exports_dir"),
        "log_path": job.get("log_path"),
    }


# Also expose exports directory for download
EXPORTS_DIR = Path("exports")
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/exports", StaticFiles(directory=str(EXPORTS_DIR)), name="exports")


# --- Helpers
def _emit(queue: asyncio.Queue, step: str, status: str, message: str = "", extra: Optional[Dict[str, Any]] = None) -> None:
    evt = {"ts": datetime.now().isoformat(), "step": step, "status": status, "message": message}
    if extra:
        evt.update(extra)
    queue.put_nowait(evt)


def _detect_eba_from_instance(instance_path: str) -> tuple[Optional[str], Optional[str]]:
    """Detect EBA version (3.4/3.5) and framework (corep/finrep/dora/fc/mrel/rem) from schemaRef hrefs.
    Fallback: infer from filename tokens.
    """
    try:
        from xml.etree import ElementTree as ET
        ns = {"xlink": "http://www.w3.org/1999/xlink", "link": "http://www.xbrl.org/2003/linkbase"}
        tree = ET.parse(instance_path)
        hrefs: list[str] = []
        for ref in tree.findall(".//link:schemaRef", ns):
            href = ref.get("{" + ns["xlink"] + "}href") or ""
            if href:
                hrefs.append(href.lower())
        blob = " ".join(hrefs)
        fw: Optional[str] = None
        if "/fws/dora/" in blob:
            fw = "dora"
        elif "/fws/corep/" in blob:
            fw = "corep"
        elif "/fws/finrep/" in blob:
            fw = "finrep"
        elif "/fws/fc/" in blob:
            fw = "fc"
        elif "/fws/mrel" in blob:
            fw = "mrel"
        elif "/fws/rem" in blob:
            fw = "rem"
        ver: Optional[str] = None
        if "/3.5/" in blob or "2024-07-11" in blob or "/3.5" in blob:
            ver = "3.5"
        elif "/3.4/" in blob or "2019-04-30" in blob or "/3.4" in blob:
            ver = "3.4"
        # fallback on filename
        if fw is None or ver is None:
            name = Path(instance_path).name.lower()
            if fw is None:
                for token, f in (("dora", "dora"), ("corep", "corep"), ("finrep", "finrep"), ("mrel", "mrel"), ("fc", "fc"), ("rem", "rem")):
                    if token in name:
                        fw = f
                        break
            if ver is None:
                if "3.5" in name or "2024-07-11" in name:
                    ver = "3.5"
                elif "3.4" in name or "2019-04-30" in name:
                    ver = "3.4"
        return ver, fw
    except Exception:
        try:
            name = Path(instance_path).name.lower()
            ver = "3.5" if ("3.5" in name or "2024-07-11" in name) else ("3.4" if ("3.4" in name or "2019-04-30" in name) else None)
            fw = None
            for token, f in (("dora", "dora"), ("corep", "corep"), ("finrep", "finrep"), ("mrel", "mrel"), ("fc", "fc"), ("rem", "rem")):
                if token in name:
                    fw = f
                    break
            return ver, fw
        except Exception:
            return None, None


def _build_arelle_args(instance: str, taxonomy_packages: Optional[List[str]], validate: bool, offline: bool, cache_dir: Optional[str], extra_args: Optional[List[str]]) -> List[str]:
    args: List[str] = ["-m", "arelle.CntlrCmdLine", "--file", instance]
    if validate:
        args.append("--validate")
    for t in taxonomy_packages or []:
        if t:
            args.extend(["--packages", t])
    if cache_dir:
        args.extend(["--cacheDir", cache_dir])
    if offline:
        args.extend(["--internetConnectivity", "offline"])
    for a in (extra_args or []):
        if a:
            args.append(a)
    return args


def _prime_cache_from_packages(packages: List[str], cache_dir: str) -> None:
    """Copy relevant members from taxonomy zips into assets/cache/http/... to satisfy offline lookups.
    This avoids HTTP when Arelle tries to dereference eurofiling/eba URLs.
    """
    http_root = Path(cache_dir) / "http"
    http_root.mkdir(parents=True, exist_ok=True)
    # Candidate prefixes Arelle often requests
    wanted_roots = (
        "www.eba.europa.eu/",
        "www.eurofiling.info/",
        "www.xbrl.org/",
        "www.w3.org/",
    )
    for p in packages:
        base = str(p).split("#", 1)[0]
        if not base.lower().endswith(".zip"):
            continue
        zpath = Path(base)
        if not zpath.exists():
            continue
        try:
            import zipfile
            with zipfile.ZipFile(str(zpath), "r") as zf:
                for name in zf.namelist():
                    low = name.lower()
                    if not low.endswith((".xsd", ".xml")):
                        continue
                    # Only mirror members that contain known HTTP host roots, and strip any zip wrapper
                    idx = -1
                    roots_l = tuple(r.lower() for r in wanted_roots)
                    for root in roots_l:
                        j = low.find(root)
                        if j >= 0:
                            idx = j
                            break
                    if idx < 0:
                        continue
                    rel = name[idx:]
                    target = http_root / rel
                    if target.exists():
                        continue
                    parent = target.parent
                    try:
                        if parent.exists() and parent.is_file():
                            parent.unlink()
                        parent.mkdir(parents=True, exist_ok=True)
                    except Exception:
                        # As a last resort, attempt to clear conflicting path
                        try:
                            __import__('os').remove(str(parent))
                        except Exception:
                            pass
                        parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(name, "r") as src, open(target, "wb") as dst:
                        dst.write(src.read())
        except Exception:
            # Best effort; continue
            continue


async def _tail_jsonl(path: Path, queue: asyncio.Queue, cancel: asyncio.Event, tag: str) -> None:
    try:
        # Tail file and emit log events
        last_size = 0
        while not cancel.is_set():
            if not path.exists():
                await asyncio.sleep(0.25)
                continue
            size = path.stat().st_size
            if size > last_size:
                with path.open("r", encoding="utf-8") as f:
                    f.seek(last_size)
                    chunk = f.read()
                last_size = size
                for line in chunk.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    queue.put_nowait({"event": "log", "phase": tag, "entry": rec})
            await asyncio.sleep(0.25)
    except Exception:
        # Non-fatal
        pass


async def _run_workflow(job_id: str, req: WorkflowRequest) -> None:
    job = jobs[job_id]
    queue: asyncio.Queue = job["events_queue"]
    cancel: asyncio.Event = job["cancel_event"]
    exports_dir = Path(job["exports_dir"])
    exports_dir.mkdir(parents=True, exist_ok=True)

    steps = [
        "Cache priming", "Inputs", "Taxonomy load (DTS)", "Parse data", "Core checks", "Formula checks", "Filing rules", "DPM mapping", "Results", "Exports",
    ]
    for s in steps:
        _emit(queue, s, "not_started")

    job["status"] = "running"
    
    # Step 0: Cache priming (ensure EBA formulas work)
    _emit(queue, "Cache priming", "running")
    try:
        import subprocess
        import sys
        cache_cmd = [sys.executable, "-m", "scripts.cache_prime"]
        cache_result = subprocess.run(cache_cmd, capture_output=True, text=True, check=False, timeout=60)
        if cache_result.returncode != 0:
            _emit(queue, "Cache priming", "warning", f"Cache priming had issues: {cache_result.stderr[:100]}")
        else:
            _emit(queue, "Cache priming", "succeeded")
    except Exception as e:
        _emit(queue, "Cache priming", "warning", f"Cache priming failed: {str(e)[:100]}")
    
    # Step 1: Inputs
    inst_ok = Path(req.instance_file).exists()
    tax_ok = True
    if req.taxonomy_packages:
        tax_ok = all(Path(p.split("#", 1)[0]).exists() for p in req.taxonomy_packages)
    dpm_ok = True if not req.dpm_sqlite else Path(req.dpm_sqlite).exists()
    # Arelle availability check
    arelle_ok = True
    try:
        import arelle  # type: ignore
        _ = arelle
    except Exception:
        arelle_ok = False
    if not inst_ok or not tax_ok or not dpm_ok or not arelle_ok:
        problems = []
        if not inst_ok:
            problems.append("Instance file not found")
        if not tax_ok:
            problems.append("One or more taxonomy packages not found")
        if not dpm_ok:
            problems.append("DPM database not found")
        if not arelle_ok:
            problems.append("Validator engine (Arelle) not available. Install dependencies: pip install -r requirements.txt")
        _emit(queue, "Inputs", "failed", "; ".join(problems))
        job["status"] = "failed"
        return
    _emit(queue, "Inputs", "running")
    await asyncio.sleep(0.2)
    _emit(queue, "Inputs", "succeeded")

    # Prepare JSONL logs
    log_dts = exports_dir / "taxonomy_load.jsonl"
    log_val = exports_dir / "validation.jsonl"

    # Build taxonomy list from explicit packages or config stack if provided
    taxonomy_paths: List[str] = list(req.taxonomy_packages or [])
    # Auto-detect version/framework if not provided
    detected_ver, detected_fw = _detect_eba_from_instance(req.instance_file)
    if detected_ver or detected_fw:
        _emit(queue, "Inputs", "info", message="Auto-detected framework/version", extra={"version": detected_ver, "framework": detected_fw})
    use_ver = str(req.eba_version) if req.eba_version else (detected_ver or None)
    if not taxonomy_paths and use_ver:
        try:
            cfg = json.loads(Path("config/taxonomy.json").read_text(encoding="utf-8"))
            key = "eba_3_4" if str(use_ver) == "3.4" else "eba_3_5"
            taxonomy_paths = [str(p) for p in (cfg.get("stacks", {}).get(key, []) or [])]
        except Exception:
            taxonomy_paths = []

    # Step 2: Taxonomy load (no --validate)
    _emit(queue, "Taxonomy load (DTS)", "running")
    try:
        # Prime offline cache from taxonomy packages so http URLs map to local files
        if req.offline:
            try:
                _prime_cache_from_packages(taxonomy_paths, cache_dir=str(Path("assets/cache").resolve()))
            except Exception:
                pass
        # Use in-process runner to guarantee JSONL writes via handler
        from src.validation.arelle_runner import run_validation as run_val
        tail_task = asyncio.create_task(_tail_jsonl(log_dts, queue, cancel, tag="dts"))
        loop = asyncio.get_running_loop()
        def _run_dts():
            return run_val(
                input_path=req.instance_file,
                taxonomy_paths=taxonomy_paths,
                plugins=["formula"],
                log_jsonl_path=str(log_dts),
                validate=False,
                offline=req.offline,
                cache_dir=str(Path("assets/cache").resolve()),
                extra_args=[],
                use_subprocess=False,
            )
        summary_dts = await loop.run_in_executor(_executor, _run_dts)
        # If online and errors indicate missing HTTP resources, try to fetch and retry once
        def _collect_missing_urls(log_path: Path) -> List[str]:
            urls: List[str] = []
            try:
                if log_path.exists():
                    with log_path.open('r', encoding='utf-8') as f:
                        for line in f:
                            try:
                                rec = json.loads(line)
                            except Exception:
                                continue
                            msg = (rec.get('message') or rec.get('msg') or '').lower()
                            doc = rec.get('docUri') or rec.get('docURI') or ''
                            # Arelle often logs Forbidden retrieving/IOerror retrieving messages with absolute URLs
                            m = re.findall(r"https?://[^\s'\"]+", msg)
                            if m:
                                for u in m:
                                    if u not in urls:
                                        urls.append(u)
                            if (doc.startswith('http://') or doc.startswith('https://')) and doc not in urls:
                                urls.append(doc)
            except Exception:
                pass
            return urls
        def _download_to_cache(u: str, cache_dir: str) -> bool:
            try:
                import requests
                r = requests.get(u, timeout=20)
                if r.status_code != 200:
                    return False
                # Map to assets/cache/http/<host>/<path>
                from urllib.parse import urlparse
                pr = urlparse(u)
                rel = (pr.netloc + pr.path).lstrip('/')
                if not rel:
                    return False
                target = Path(cache_dir) / 'http' / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, 'wb') as fp:
                    fp.write(r.content)
                return True
            except Exception:
                return False
        if not req.offline and int(summary_dts.get('returnCode', 0)) != 0:
            urls = _collect_missing_urls(log_dts)
            fetched = 0
            for u in urls:
                if any(u.lower().endswith(ext) for ext in ('.xsd', '.xml')):
                    if _download_to_cache(u, str(Path('assets/cache').resolve())):
                        fetched += 1
            if fetched:
                # Retry once
                tail_task = asyncio.create_task(_tail_jsonl(log_dts, queue, cancel, tag='dts'))
                summary_dts = await loop.run_in_executor(_executor, _run_dts)
                tail_task.cancel()
        tail_task.cancel()
        if cancel.is_set():
            _emit(queue, "Taxonomy load (DTS)", "failed", "Cancelled")
            jobs[job_id]["status"] = "cancelled"
            return
        if int(summary_dts.get("returnCode", 0)) != 0:
            _emit(queue, "Taxonomy load (DTS)", "failed", f"Arelle exited with code {summary_dts.get('returnCode')}")
            job["status"] = "failed"
            return
        _emit(queue, "Taxonomy load (DTS)", "succeeded")
    except Exception as e:
        _emit(queue, "Taxonomy load (DTS)", "failed", str(e))
        job["status"] = "failed"
        return

    # Steps 3-5: Validation run (parse/core/formula)
    for s in ("Parse data", "Core checks", "Formula checks"):
        _emit(queue, s, "running")
    try:
        from src.validation.arelle_runner import run_validation as run_val
        tail_task2 = asyncio.create_task(_tail_jsonl(log_val, queue, cancel, tag="validate"))
        loop = asyncio.get_running_loop()
        def _run_val():
            return run_val(
                input_path=req.instance_file,
                taxonomy_paths=taxonomy_paths,
                plugins=["formula"],
                log_jsonl_path=str(log_val),
                validate=True,
                offline=req.offline,
                cache_dir=str(Path("assets/cache").resolve()),
                extra_args=( ["--calcDecimals"] if req.calc_decimals else [] ),
                use_subprocess=False,
            )
        summary_val = await loop.run_in_executor(_executor, _run_val)
        tail_task2.cancel()
        if cancel.is_set():
            for s in ("Parse data", "Core checks", "Formula checks"):
                _emit(queue, s, "failed", "Cancelled")
            jobs[job_id]["status"] = "cancelled"
            return
        if int(summary_val.get("returnCode", 0)) != 0:
            for s in ("Parse data", "Core checks", "Formula checks"):
                _emit(queue, s, "failed", f"Arelle exited with code {summary_val.get('returnCode')}")
            job["status"] = "failed"
            job["log_path"] = str(log_val)
            return
        for s in ("Parse data", "Core checks", "Formula checks"):
            _emit(queue, s, "succeeded")
    except Exception as e:
        for s in ("Parse data", "Core checks", "Formula checks"):
            _emit(queue, s, "failed", str(e))
        job["status"] = "failed"
        return

    # Step 6: Filing rules (basic checks)
    _emit(queue, "Filing rules", "running")
    filing_messages: List[Dict[str, Any]] = []
    try:
        try:
            import arelle.Cntlr as C
            cntlr = C.Cntlr(logFileName=None)
            modelXbrl = cntlr.modelManager.load(req.instance_file)
        except Exception:
            modelXbrl = None  # type: ignore
        if modelXbrl is not None:
            # Counters
            facts_cnt = len(getattr(modelXbrl, "factsInInstance", []) or getattr(modelXbrl, "facts", []))
            contexts_cnt = len(getattr(modelXbrl, "contexts", {}))
            units_cnt = len(getattr(modelXbrl, "units", {}))
            job["_counters"] = {"facts": facts_cnt, "contexts": contexts_cnt, "units": units_cnt}
            queue.put_nowait({"event": "counters", "facts": facts_cnt, "contexts": contexts_cnt, "units": units_cnt})
            # Basic checks
            if contexts_cnt < 1:
                filing_messages.append({"level": "ERROR", "message": "No contexts present (must have at least one entity and period)."})
            if units_cnt < 1:
                filing_messages.append({"level": "ERROR", "message": "No units present. Add at least one valid currency unit."})
            # Duplicate contexts with identical dims (heuristic)
            try:
                seen = set()
                dups = 0
                for cid, ctx in getattr(modelXbrl, "contexts", {}).items():
                    dims = tuple(sorted([(str(dimQ), str(memQ)) for dimQ, memQ in getattr(ctx, "qnameDims", {}).items()]))
                    key = (getattr(ctx, "entityIdentifier", None), getattr(ctx, "period", None), dims)
                    if key in seen:
                        dups += 1
                    else:
                        seen.add(key)
                if dups:
                    filing_messages.append({"level": "WARNING", "message": f"{dups} duplicate contexts with identical dimension sets."})
            except Exception:
                pass
            # Facts pointing to missing contexts/units
            try:
                ctxt_ids = set(getattr(modelXbrl, "contexts", {}).keys())
                unit_ids = set(getattr(modelXbrl, "units", {}).keys())
                missing_ctx = 0
                missing_unit = 0
                for f in getattr(modelXbrl, "factsInInstance", []) or getattr(modelXbrl, "facts", []):
                    if getattr(f, "contextID", None) and f.contextID not in ctxt_ids:
                        missing_ctx += 1
                    if getattr(f, "unitID", None) and f.unitID not in unit_ids:
                        missing_unit += 1
                if missing_ctx:
                    filing_messages.append({"level": "ERROR", "message": f"{missing_ctx} facts reference missing contexts."})
                if missing_unit:
                    filing_messages.append({"level": "ERROR", "message": f"{missing_unit} facts reference missing units."})
            except Exception:
                pass
            # DORA period type sanity
            try:
                if "dora" in Path(req.instance_file).name.lower():
                    # Heuristic: if most facts are duration but period types are instant (or vice versa)
                    inst = 0
                    dur = 0
                    for ctx in getattr(modelXbrl, "contexts", {}).values():
                        if getattr(ctx, "isInstantPeriod", False):
                            inst += 1
                        else:
                            dur += 1
                    if inst and dur and abs(inst - dur) > max(3, int(0.5 * (inst + dur))):
                        filing_messages.append({"level": "WARNING", "message": "Period types look inconsistent for DORA (instant vs duration)."})
            except Exception:
                pass
        # Emit filing messages
        for m in filing_messages:
            queue.put_nowait({"event": "log", "phase": "filing_rules", "entry": m})
        # Status color based on messages
        has_err = any((m.get("level") or "").upper() in ("ERROR", "FATAL") for m in filing_messages)
        has_warn = any((m.get("level") or "").upper() == "WARNING" for m in filing_messages)
        if has_err or (req.fail_on_warnings and has_warn):
            _emit(queue, "Filing rules", "failed", "Issues found")
        elif has_warn:
            _emit(queue, "Filing rules", "warning", "Warnings present")
        else:
            _emit(queue, "Filing rules", "succeeded")
    except Exception as e:
        _emit(queue, "Filing rules", "failed", str(e))

    # Step 7-9: DPM mapping, Results, Exports
    from src.pipeline import ingest_jsonl, write_validation_messages_csv, write_results_by_file_json, write_formula_rollup_csv
    from src.reporting.reports import generate_reports
    messages, rollup, by_file = ingest_jsonl(str(log_val), dpm_sqlite=req.dpm_sqlite, dpm_schema=req.dpm_schema, model_xbrl_path=req.instance_file)
    # Apply EBA Filing Rules and merge results (if enabled and Excel available)
    try:
        from xbrl_validator.config import get_eba_rules_excel_path
        from src.validation.eba_rules import apply_eba_rules, write_rules_coverage_csv
        rules_excel = req.filing_rules_excel or get_eba_rules_excel_path()
        if req.apply_filing_rules and rules_excel:
            extra = apply_eba_rules(
                messages,
                model_xbrl_path=req.instance_file,
                framework_version=str(req.eba_version) if req.eba_version else None,
                eba_rules_excel=rules_excel,
                dpm_sqlite=req.dpm_sqlite,
                dpm_schema=req.dpm_schema or "dpm35_10",
            )
            extra_msgs, coverage = (extra if isinstance(extra, tuple) else (extra, None))
            if extra_msgs:
                messages.extend(extra_msgs)
            # Write coverage CSV if available
            try:
                if coverage is not None:
                    write_rules_coverage_csv(coverage, str(Path(job["exports_dir"]) / "rules_coverage.csv"))
            except Exception:
                pass
            # Recompute severity rollup minimally
            sev2: Dict[str, int] = {}
            for m in messages:
                lv = (m.get("level") or "INFO").upper()
                sev2[lv] = sev2.get(lv, 0) + 1
            rollup["bySeverity"] = sev2
            rollup["total"] = len(messages)
    except Exception:
        # Never fail workflow due to filing rules post-processing
        pass
    # Determine overall severity
    sev = {k.upper(): v for k, v in (rollup.get("bySeverity") or {}).items()}
    errors = sev.get("ERROR", 0) + sev.get("FATAL", 0)
    warnings = sev.get("WARNING", 0)

    _emit(queue, "DPM mapping", "running")
    # Mapping is attached in ingest step per message; emit small sample for panel
    try:
        sample_map = []
        for m in messages:
            mc = m.get("mappedCell")
            if mc:
                sample_map.append({
                    "concept": (mc.get("concept") or m.get("modelObjectQname") or ""),
                    "template": mc.get("template_id"),
                    "table": mc.get("table_id"),
                    "cell": mc.get("cell_id"),
                })
                if len(sample_map) >= 8:
                    break
        if sample_map:
            queue.put_nowait({"event": "mapping", "rows": sample_map})
    except Exception:
        pass
    _emit(queue, "DPM mapping", "succeeded")

    _emit(queue, "Results", "running")
    counters = job.get("_counters") or {}
    summary = {
        "facts": counters.get("facts"),
        "contexts": counters.get("contexts"),
        "units": counters.get("units"),
        "errors": int(errors),
        "warnings": int(warnings),
        "bySeverity": sev,
        "total": rollup.get("total", 0),
    }
    job["summary"] = summary
    if errors > 0:
        _emit(queue, "Results", "failed", extra={"summary": summary})
    elif warnings > 0 or (req.fail_on_warnings and warnings > 0):
        _emit(queue, "Results", "warning", extra={"summary": summary})
    else:
        _emit(queue, "Results", "succeeded", extra={"summary": summary})

    _emit(queue, "Exports", "running")
    try:
        # Write exports
        write_validation_messages_csv(messages, str(exports_dir / "validation_messages.csv"))
        write_results_by_file_json(by_file, str(exports_dir / "results_by_file.json"))
        write_formula_rollup_csv(messages, str(exports_dir / "formula_rollup.csv"))
        _ = generate_reports(messages=messages, exports_dir=str(exports_dir))
        _emit(queue, "Exports", "succeeded")
        # Provide exports dir to client
        queue.put_nowait({"event": "exports", "dir": str(exports_dir)})
    except Exception as e:
        _emit(queue, "Exports", "failed", str(e))

    job["log_path"] = str(log_val)
    # Finish
    if req.fail_on_warnings and warnings > 0:
        job["status"] = "completed"
        job["return_code"] = 1
    else:
        job["status"] = "completed"
        job["return_code"] = 0 if errors == 0 else 1

    # Close stream
    queue.put_nowait(None)


async def _run_cli_validation_job(job_id: str, request: ValidationRequest):
    job = jobs[job_id]
    job["status"] = "running"
    # Create temp log file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        log_path = f.name
    job["log_path"] = log_path
    cmd = [
        sys.executable, "-m", "app.validate",
        "--file", request.file_path,
        "--out", log_path,
        "--plugins", request.plugins,
        "--exports", f"exports/{job_id}",
    ]
    if request.eba_version:
        cmd.extend(["--ebaVersion", request.eba_version])
    if request.offline:
        cmd.append("--offline")
    if request.severity_exit:
        cmd.extend(["--severity-exit", request.severity_exit])
    if request.calc_decimals:
        cmd.append("--calcDecimals")
    if request.calc_precision:
        cmd.append("--calcPrecision")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        summary = {"total": 0, "byLevel": {}, "returnCode": result.returncode}
        if Path(log_path).exists():
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            rec = json.loads(line.strip())
                            summary["total"] += 1
                            level = (rec.get("level") or "INFO").upper()
                            summary["byLevel"][level] = summary["byLevel"].get(level, 0) + 1
                        except Exception:
                            pass
        job["status"] = "completed"
        job["return_code"] = result.returncode
        job["summary"] = summary
        job["completed_at"] = datetime.now().isoformat()
    except subprocess.TimeoutExpired:
        job["status"] = "failed"
        job["return_code"] = 124
        job["summary"] = {"error": "timeout"}
        job["completed_at"] = datetime.now().isoformat()
    except Exception as e:
        job["status"] = "failed"
        job["return_code"] = 1
        job["summary"] = {"error": str(e)}
        job["completed_at"] = datetime.now().isoformat()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
