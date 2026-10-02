from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn
import cv2
import numpy as np
import os
import json
import base64
from typing import List, Optional
import time

import sys
# Ensure backend directory is on path when running as `backend.main`
sys.path.insert(0, os.path.dirname(__file__))
try:
    from solver import get_trie, get_common_set, build_adjacency, solve_board, rank_results, find_trap_tiles, SCRABBLE_VALUES
    from detector import detect_board, tiles_to_solver_format
    from annotator import annotate_image, image_to_base64_png, PALETTE
except ModuleNotFoundError:
    # Fallback for package import
    from backend.solver import get_trie, get_common_set, build_adjacency, solve_board, rank_results, find_trap_tiles, SCRABBLE_VALUES
    from backend.detector import detect_board, tiles_to_solver_format
    from backend.annotator import annotate_image, image_to_base64_png, PALETTE

app = FastAPI(title="BoardSnap API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load trie at startup
TRIE, WORD_SET = None, None
COMMON_SET = None

@app.on_event("startup")
async def startup():
    global TRIE, WORD_SET, COMMON_SET
    # already imported above, reuse
    TRIE, WORD_SET = get_trie()
    COMMON_SET = get_common_set()
    print(f"Loaded dictionary {TRIE.word_count} words, common {len(COMMON_SET)}")

# Helper to decode uploaded image to cv2 BGR
def decode_image(file_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(file_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Could not decode image. Please upload PNG/JPG.")
    return img

def image_to_tiles_and_results(img_bgr, common_only=False, use_wildcards=True):
    det = detect_board(img_bgr)
    tiles_detector = det['tiles']
    solver_tiles = tiles_to_solver_format(det)
    # check <10 tiles
    if det['detected_count'] < 10:
        raise HTTPException(status_code=422, detail={"error": "Bad screenshot: fewer than 10 tiles detected. Please upload a clearer, centered board screenshot.", "detected": det['detected_count'], "tiles": tiles_detector})
    # Handle wildcard toggle: if not using wildcards, treat blanks as holes (original website behavior)
    if not use_wildcards:
        for st in solver_tiles:
            if st.get('is_wildcard') or st.get('is_blank'):
                st['is_empty'] = True
                st['is_wildcard'] = False
                st['is_blank'] = False
    # Build adjacency (wildcards are included as traversable nodes)
    adj = build_adjacency(solver_tiles)
    # Solve
    start = time.time()
    results = solve_board(solver_tiles, trie=TRIE, adjacency=adj)
    elapsed = time.time() - start
    # Filter common if requested
    filtered_results = results
    if common_only:
        filtered_results = [r for r in results if r['word'] in COMMON_SET]
        # if common filtering yields zero, fallback? No keep empty
    ranked = rank_results(filtered_results, common_set=COMMON_SET)
    # Also keep unfiltered total for stats? ranked already has common flag
    traps = find_trap_tiles(solver_tiles, results)  # use full results for trap detection

    # Generate annotated images
    # Hero image for #1 — pass wildcard_map so blank tiles are highlighted correctly
    hero_b64 = None
    if ranked['top_by_score']:
        best = ranked['top_by_score'][0]
        hero_img = annotate_image(img_bgr, solver_tiles, best['path'], best['word'], best['score'], color=PALETTE[0], highlight_index=0, wildcard_map=best.get('wildcard_map'))
        hero_b64 = image_to_base64_png(hero_img)

    # Per-word previews for top_by_score and top_by_length
    # To avoid huge payload, generate small previews (220px)
    def make_previews(lst):
        previews=[]
        for i, r in enumerate(lst):
            ann = annotate_image(img_bgr, solver_tiles, r['path'], r['word'], r['score'], color=PALETTE[i % len(PALETTE)], highlight_index=i, wildcard_map=r.get('wildcard_map'))
            # resize for preview
            h,w = ann.shape[:2]
            scale = 320 / max(h,w) if max(h,w) > 320 else 1.0
            if scale < 1:
                small = cv2.resize(ann, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            else:
                small = ann
            previews.append(image_to_base64_png(small))
        return previews

    score_previews = make_previews(ranked['top_by_score'])
    length_previews = make_previews(ranked['top_by_length'])

    # Attach previews to results
    for i, r in enumerate(ranked['top_by_score']):
        r['preview'] = score_previews[i] if i < len(score_previews) else None
    for i, r in enumerate(ranked['top_by_length']):
        r['preview'] = length_previews[i] if i < len(length_previews) else None
    # For all words, don't include preview (too many) but front can request individually

    # Build tiles response for UI (with row/col, confidence)
    tiles_ui = []
    for i, t in enumerate(tiles_detector):
        solver_t = solver_tiles[i]
        tiles_ui.append({
            "index": i,
            "x": int(t['x']),
            "y": int(t['y']),
            "r": int(t.get('r', 26)),
            "letter": solver_t['letter'],
            "value": solver_t['value'],
            "is_empty": solver_t['is_empty'],
            "is_wildcard": bool(solver_t.get('is_wildcard') or solver_t.get('is_blank')),
            "is_blank": bool(solver_t.get('is_wildcard') or solver_t.get('is_blank')),
            "confidence": round(float(t.get('confidence', 1.0)), 2),
            "row": int(t.get('row', -1)),
            "col": int(t.get('col', -1)),
        })

    return {
        "tiles": tiles_ui,
        "solver_tiles": solver_tiles,  # internal
        "detected_count": det['detected_count'],
        "playable_count": det['playable_count'],
        "empty_count": det['empty_count'],
        "wildcard_count": det.get('wildcard_count', 0),
        "adjacency": adj,
        "results": {
            "top_by_score": ranked['top_by_score'],
            "top_by_length": ranked['top_by_length'],
            "all": ranked['all'][:200],  # limit to 200 for payload, but show total count
            "total_found": ranked['total_found'],
        },
        "traps": traps,
        "hero_image": hero_b64,
        "solve_time_ms": int(elapsed*1000),
        "common_filter": common_only,
        "use_wildcards": use_wildcards,
    }

@app.get("/api/health")
def health():
    return {"status": "ok", "words": TRIE.word_count if TRIE else 0, "common": len(COMMON_SET) if COMMON_SET else 0}

@app.get("/api/examples")
def list_examples():
    idx_path = os.path.join(os.path.dirname(__file__), "samples", "index.json")
    if os.path.exists(idx_path):
        with open(idx_path) as f:
            data=json.load(f)
        # add image urls
        for item in data:
            item["image_url"] = f"/api/example/{item['id']}/image"
            item["solve_url"] = f"/api/example/{item['id']}/solve"
        return {"examples": data}
    # fallback if no index
    samples_dir = os.path.join(os.path.dirname(__file__), "samples")
    examples=[]
    if os.path.exists(samples_dir):
        for fname in sorted(os.listdir(samples_dir)):
            if fname.endswith(".png"):
                examples.append({"id": fname, "image_url": f"/samples/{fname}"})
    return {"examples": examples}

@app.get("/api/example/{example_id}/image")
def get_example_image(example_id: str):
    # example_id can be 1,2,3 or sample_1
    samples_dir = os.path.join(os.path.dirname(__file__), "samples")
    candidates = [
        os.path.join(samples_dir, f"sample_{example_id}.png"),
        os.path.join(samples_dir, f"{example_id}.png"),
        os.path.join(samples_dir, f"sample_{example_id}.png".replace("sample_sample_","sample_")),
    ]
    for p in candidates:
        if os.path.exists(p):
            return FileResponse(p, media_type="image/png")
    # also try without sample prefix
    try:
        iid=int(example_id)
        p=os.path.join(samples_dir, f"sample_{iid}.png")
        if os.path.exists(p):
            return FileResponse(p, media_type="image/png")
    except:
        pass
    raise HTTPException(status_code=404, detail="Example not found")

@app.get("/api/example/{example_id}/solve")
def solve_example(example_id: str, common_only: bool = False, use_wildcards: bool = True):
    samples_dir = os.path.join(os.path.dirname(__file__), "samples")
    # find image
    p=None
    for cand in [f"sample_{example_id}.png", f"{example_id}.png"]:
        cand_path=os.path.join(samples_dir, cand)
        if os.path.exists(cand_path):
            p=cand_path; break
    if p is None:
        try:
            iid=int(example_id)
            cand_path=os.path.join(samples_dir, f"sample_{iid}.png")
            if os.path.exists(cand_path):
                p=cand_path
        except:
            pass
    if p is None or not os.path.exists(p):
        raise HTTPException(status_code=404, detail="Example not found")
    img = cv2.imread(p)
    if img is None:
        raise HTTPException(status_code=500, detail="Could not read example image")
    result = image_to_tiles_and_results(img, common_only=common_only, use_wildcards=use_wildcards)
    # Don't expose solver_tiles internal duplicate
    result.pop("solver_tiles", None)
    result.pop("adjacency", None)
    return result

@app.post("/api/detect")
async def detect_endpoint(file: UploadFile = File(...)):
    data = await file.read()
    img = decode_image(data)
    det = detect_board(img)
    if det['detected_count'] < 10:
        # still return but with warning
        return JSONResponse(status_code=422, content={
            "error": "Bad screenshot: fewer than 10 tiles detected.",
            "detected_count": det['detected_count'],
            "tiles": [
                {"x": int(t['x']), "y": int(t['y']), "r": int(t.get('r',26)), "letter": t['letter'] if not t.get('is_wildcard') else "", "value": t['value'], "is_empty": bool(t['is_empty']), "is_wildcard": bool(t.get('is_wildcard')), "is_blank": bool(t.get('is_wildcard')), "confidence": float(t.get('confidence',0)), "row": int(t.get('row',-1)), "col": int(t.get('col',-1))}
                for t in det['tiles']
            ],
            "playable_count": det['playable_count'],
            "empty_count": det['empty_count'],
            "wildcard_count": det.get('wildcard_count', 0),
        })
    tiles_ui=[]
    for i,t in enumerate(det['tiles']):
        tiles_ui.append({
            "index": i,
            "x": int(t['x']), "y": int(t['y']), "r": int(t.get('r',26)),
            "letter": t['letter'] if not t.get('is_wildcard') and not t['is_empty'] else "",
            "value": int(t['value']),
            "is_empty": bool(t['is_empty']),
            "is_wildcard": bool(t.get('is_wildcard') or t.get('is_blank')),
            "is_blank": bool(t.get('is_wildcard') or t.get('is_blank')),
            "confidence": round(float(t.get('confidence',0)),2),
            "row": int(t.get('row',-1)), "col": int(t.get('col',-1))
        })
    return {
        "tiles": tiles_ui,
        "detected_count": det['detected_count'],
        "playable_count": det['playable_count'],
        "empty_count": det['empty_count'],
        "wildcard_count": det.get('wildcard_count', 0),
        "low_conf_count": det['low_conf_count'],
    }

@app.post("/api/solve")
async def solve_endpoint(file: UploadFile = File(...), common_only: bool = Form(False), use_wildcards: bool = Form(True)):
    data = await file.read()
    img = decode_image(data)
    try:
        result = image_to_tiles_and_results(img, common_only=common_only, use_wildcards=use_wildcards)
    except HTTPException as e:
        raise e
    # cleanup internal fields
    result.pop("solver_tiles", None)
    result.pop("adjacency", None)
    return result

@app.post("/api/solve-tiles")
async def solve_tiles_endpoint(request: Request):
    """
    Accepts either:
    - JSON body {tiles: [{x,y,letter,value,is_empty}], common_only: bool, image_base64?: string}
    - OR multipart form with file and tiles_json
    """
    content_type = request.headers.get("content-type","")
    tiles = None
    img_bgr = None
    common_only = False
    use_wildcards = True

    if "multipart/form-data" in content_type:
        form = await request.form()
        tiles_json = form.get("tiles") or form.get("tiles_json")
        if tiles_json is None:
            raise HTTPException(status_code=400, detail="Missing tiles field")
        if isinstance(tiles_json, str):
            tiles = json.loads(tiles_json)
        else:
            # might be JSON string
            tiles = json.loads(tiles_json)
        common_only_str = form.get("common_only")
        if common_only_str is not None:
            if isinstance(common_only_str, str):
                common_only = common_only_str.lower() in ("true","1","yes")
            else:
                common_only = bool(common_only_str)
        use_wildcards_str = form.get("use_wildcards")
        if use_wildcards_str is not None:
            if isinstance(use_wildcards_str, str):
                use_wildcards = use_wildcards_str.lower() not in ("false","0","no")
            else:
                use_wildcards = bool(use_wildcards_str)
        file = form.get("file") or form.get("image")
        if file is not None:
            # file is UploadFile
            data = await file.read()
            img_bgr = decode_image(data)
    else:
        # JSON
        try:
            body = await request.json()
        except:
            raise HTTPException(status_code=400, detail="Expected JSON with tiles")
        tiles = body.get("tiles")
        if tiles is None:
            raise HTTPException(status_code=400, detail="Missing tiles")
        common_only = bool(body.get("common_only", False))
        if "use_wildcards" in body:
            use_wildcards = bool(body.get("use_wildcards"))
        # also support wildcard flag aliases
        if "useWildcards" in body:
            use_wildcards = bool(body.get("useWildcards"))
        image_b64 = body.get("image_base64") or body.get("image")
        if image_b64:
            # strip data url prefix
            if "," in image_b64:
                b64part = image_b64.split(",",1)[1]
            else:
                b64part = image_b64
            try:
                img_bytes = base64.b64decode(b64part)
                img_bgr = decode_image(img_bytes)
            except Exception as e:
                # ignore, will still solve without image
                img_bgr = None

    if tiles is None or len(tiles) < 5:
        raise HTTPException(status_code=422, detail="Too few tiles provided")

    # Normalize tiles: ensure required fields
    # Wildcard handling: tiles with is_wildcard/is_blank are blanks that can be any letter (0 pts)
    solver_tiles=[]
    for t in tiles:
        letter = t.get("letter","").upper().strip() if t.get("letter") else ""
        is_wildcard = bool(t.get("is_wildcard") or t.get("is_blank") or t.get("wildcard"))
        # Also treat is_empty with no letter as wildcard when use_wildcards enabled and letter empty
        # If use_wildcards and tile is marked empty but has no letter, treat as wildcard
        if use_wildcards and t.get("is_empty") and not letter:
            is_wildcard = True
        is_empty = bool(t.get("is_empty", False) or t.get("empty", False))
        if is_wildcard:
            # wildcard is playable, not a hole
            is_empty = False
            letter = ""
            value = int(t.get("value", 0)) if t.get("value") is not None else 0
        elif is_empty:
            letter=""
            value = 0
        else:
            value = t.get("value")
            if value is None:
                value = SCRABBLE_VALUES.get(letter, 0) if letter else 0
        solver_tiles.append({
            "x": int(t.get("x",0)),
            "y": int(t.get("y",0)),
            "letter": letter,
            "value": int(value),
            "is_empty": is_empty,
            "is_wildcard": is_wildcard,
            "is_blank": is_wildcard,
        })
    # If wildcards disabled, convert them back to holes
    if not use_wildcards:
        for st in solver_tiles:
            if st.get('is_wildcard'):
                st['is_empty'] = True
                st['is_wildcard'] = False
                st['is_blank'] = False

    # playable includes wildcards (they are not empty)
    if len([t for t in solver_tiles if not t['is_empty'] or t.get('is_wildcard')]) < 10:
        raise HTTPException(status_code=422, detail="Bad board: fewer than 10 playable tiles. Check detection or manual corrections.")

    adj = build_adjacency(solver_tiles)
    start=time.time()
    results = solve_board(solver_tiles, trie=TRIE, adjacency=adj)
    elapsed=time.time()-start
    filtered = results
    if common_only:
        filtered=[r for r in results if r['word'] in COMMON_SET]
    ranked=rank_results(filtered, common_set=COMMON_SET)
    traps=find_trap_tiles(solver_tiles, results)

    hero_b64=None
    score_previews=[]
    length_previews=[]
    if img_bgr is not None:
        if ranked['top_by_score']:
            best=ranked['top_by_score'][0]
            hero_img=annotate_image(img_bgr, solver_tiles, best['path'], best['word'], best['score'], color=PALETTE[0], highlight_index=0, wildcard_map=best.get('wildcard_map'))
            hero_b64=image_to_base64_png(hero_img)
        def make_previews(lst):
            out=[]
            for i,r in enumerate(lst):
                ann=annotate_image(img_bgr, solver_tiles, r['path'], r['word'], r['score'], color=PALETTE[i % len(PALETTE)], highlight_index=i, wildcard_map=r.get('wildcard_map'))
                h,w=ann.shape[:2]
                scale=320/max(h,w) if max(h,w)>320 else 1.0
                if scale<1:
                    small=cv2.resize(ann, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                else:
                    small=ann
                out.append(image_to_base64_png(small))
            return out
        score_previews=make_previews(ranked['top_by_score'])
        length_previews=make_previews(ranked['top_by_length'])
        for i,r in enumerate(ranked['top_by_score']):
            r['preview']=score_previews[i] if i < len(score_previews) else None
        for i,r in enumerate(ranked['top_by_length']):
            r['preview']=length_previews[i] if i < len(length_previews) else None

    # Build tiles UI response (maybe updated values)
    tiles_ui=[]
    for i,t in enumerate(solver_tiles):
        orig = tiles[i] if i < len(tiles) else {}
        tiles_ui.append({
            "index": i,
            "x": t['x'], "y": t['y'],
            "r": int(orig.get('r',26)),
            "letter": t['letter'],
            "value": t['value'],
            "is_empty": t['is_empty'],
            "is_wildcard": bool(t.get('is_wildcard')),
            "is_blank": bool(t.get('is_wildcard')),
            "confidence": float(orig.get('confidence',0.95)),
            "row": int(orig.get('row',-1)),
            "col": int(orig.get('col',-1)),
        })

    return {
        "tiles": tiles_ui,
        "detected_count": len(solver_tiles),
        "playable_count": len([t for t in solver_tiles if not t['is_empty'] or t.get('is_wildcard')]),
        "empty_count": len([t for t in solver_tiles if t['is_empty']]),
        "wildcard_count": len([t for t in solver_tiles if t.get('is_wildcard')]),
        "results": {
            "top_by_score": ranked['top_by_score'],
            "top_by_length": ranked['top_by_length'],
            "all": ranked['all'][:200],
            "total_found": ranked['total_found'],
        },
        "traps": traps,
        "hero_image": hero_b64,
        "solve_time_ms": int(elapsed*1000),
        "common_filter": common_only,
        "use_wildcards": use_wildcards,
    }

@app.get("/api/words/search")
def search_words(q: str = "", limit: int = 20, common_only: bool = False):
    # Search in all words? But need board context? This endpoint just searches dictionary
    if not q:
        return {"words": []}
    q=q.upper()
    # filter WORD_SET
    source = COMMON_SET if common_only else WORD_SET
    matches=[w for w in source if w.startswith(q)][:limit]
    return {"words": matches}

# Serve frontend static
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
# Also try alternative path when running from backend dir
if not os.path.exists(frontend_dir):
    frontend_dir = os.path.join(os.getcwd(), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
else:
    @app.get("/")
    def root():
        return {"message": "BoardSnap API running. Frontend not found.", "docs": "/docs"}

if __name__=="__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

