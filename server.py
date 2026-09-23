import io, json, os, random, time, uuid
from pathlib import Path

import requests
from PIL import Image
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from rembg import new_session, remove
import uvicorn

ROOT = Path(__file__).resolve().parent
WORKFLOW_PATH = ROOT / "workflows" / "character_asset_sdxl_ipadapter.json"
OUTPUT_DIR = ROOT / "outputs"
REF_DIR = ROOT / "references"
OUTPUT_DIR.mkdir(exist_ok=True)
REF_DIR.mkdir(exist_ok=True)

COMFYUI_URL = os.getenv("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
PORT = int(os.getenv("ASSET_PORT", "8010"))
REMBG_MODEL = os.getenv("REMBG_MODEL", "u2netp")
REMBG_SESSION = None

app = FastAPI(title="House VN Character Asset Generator")
LAST_SEED = None
LAST_OUTPUT = None

BODY_WORDS = {
    "very_thin": "very slender body, narrow waist, slim hips, delicate proportions",
    "thin": "slender body, slim waist, lean proportions",
    "average": "average natural adult body proportions",
    "curvy": "curvy adult body, defined waist, fuller hips and thighs",
    "heavy": "fuller adult body, wider waist and hips, natural soft proportions",
}

POSE_WORDS = {
    "front": "front view, facing camera, neutral standing pose, arms relaxed at sides",
    "three_quarter": "three-quarter view, relaxed natural standing pose",
    "back": "back view, subject facing away from camera, full body visible",
    "side": "side profile view, relaxed natural standing pose",
}


def load_workflow():
    return json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))


def upload_to_comfy(path: Path):
    with path.open("rb") as f:
        r = requests.post(
            f"{COMFYUI_URL}/upload/image",
            files={"image": (path.name, f, "image/png")},
            data={"overwrite": "true"},
            timeout=60,
        )
    r.raise_for_status()
    return r.json()["name"]


def queue_prompt(workflow):
    r = requests.post(
        f"{COMFYUI_URL}/prompt",
        json={"prompt": workflow, "client_id": str(uuid.uuid4())},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["prompt_id"]


def wait_for_output(prompt_id, timeout=600):
    started = time.time()
    while time.time() - started < timeout:
        r = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=30)
        r.raise_for_status()
        data = r.json()
        if prompt_id in data:
            outputs = data[prompt_id].get("outputs", {})
            for node in outputs.values():
                for item in node.get("images", []):
                    params = {
                        "filename": item["filename"],
                        "subfolder": item.get("subfolder", ""),
                        "type": item.get("type", "output"),
                    }
                    img = requests.get(
                        f"{COMFYUI_URL}/view", params=params, timeout=120
                    )
                    img.raise_for_status()
                    return img.content
        time.sleep(1)
    raise TimeoutError("ComfyUI generation timed out")


def clean_alpha(raw: bytes) -> bytes:
    global REMBG_SESSION

    if REMBG_SESSION is None:
        REMBG_SESSION = new_session(REMBG_MODEL)

    try:
        out = remove(raw, session=REMBG_SESSION)
        im = Image.open(io.BytesIO(out)).convert("RGBA")
    except Exception as exc:
        print(f"[WARN] Background removal failed ({REMBG_MODEL}): {exc}")
        im = Image.open(io.BytesIO(raw)).convert("RGBA")

    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def build_prompt(character_name, description, build, bust, waist, hips, legs, pose, clothing, edit):
    sliders = (
        f"bust proportion level {bust}/5, waist proportion level {waist}/5, "
        f"hip proportion level {hips}/5, leg proportion level {legs}/5"
    )
    edit_text = edit.strip()
    return (
        f"photorealistic adult woman, full body, head to toe, centered, "
        f"{BODY_WORDS.get(build, BODY_WORDS['average'])}, {sliders}, "
        f"{POSE_WORDS.get(pose, POSE_WORDS['front'])}, "
        f"{clothing.strip() or 'simple neutral fitted clothing'}, "
        f"character identity: {character_name.strip() or 'unnamed character'}, "
        f"{description.strip()} "
        f"BODY AND APPEARANCE EDIT HAS PRIORITY: "
        f"{edit_text if edit_text else 'preserve the requested body proportions'}; "
        "preserve face, hair, age, skin tone and identity from the reference; "
        "do not change identity."
    )


@app.get("/", response_class=HTMLResponse)
def index():
    return (ROOT / "index.html").read_text(encoding="utf-8")


@app.post("/api/generate")
async def generate(
    reference: UploadFile = File(...),
    character_name: str = Form(""),
    description: str = Form(""),
    build: str = Form("average"),
    bust: int = Form(3),
    waist: int = Form(3),
    hips: int = Form(3),
    legs: int = Form(3),
    pose: str = Form("front"),
    clothing: str = Form(""),
    edit: str = Form(""),
    seed_mode: str = Form("new"),
    transparent: bool = Form(True),
):
    global LAST_SEED, LAST_OUTPUT

    data = await reference.read()
    ref_path = REF_DIR / f"reference_{uuid.uuid4().hex}.png"
    im = Image.open(io.BytesIO(data)).convert("RGB")
    im.save(ref_path, "PNG")
    comfy_ref = upload_to_comfy(ref_path)

    workflow = load_workflow()
    workflow["4"]["inputs"]["image"] = comfy_ref
    workflow["2"]["inputs"]["text"] = build_prompt(
        character_name, description, build, bust, waist, hips, legs, pose, clothing, edit
    )

    if seed_mode == "same" and LAST_SEED is not None:
        seed = LAST_SEED
    else:
        seed = random.randint(1, 2**63 - 1)

    LAST_SEED = seed
    workflow["6"]["inputs"]["weight"] = 0.58 if edit.strip() else 0.68
    workflow["10"]["inputs"]["seed"] = seed

    prompt_id = queue_prompt(workflow)
    raw = wait_for_output(prompt_id)

    if transparent:
        raw = clean_alpha(raw)

    out_path = OUTPUT_DIR / f"character_{uuid.uuid4().hex[:10]}_{seed}.png"
    out_path.write_bytes(raw)
    LAST_OUTPUT = out_path

    return JSONResponse({"ok": True, "seed": seed, "url": f"/api/output/{out_path.name}"})


@app.get("/api/output/{name}")
def output(name: str):
    path = OUTPUT_DIR / name
    if not path.exists() or path.parent != OUTPUT_DIR:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, media_type="image/png")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
