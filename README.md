# Character Asset Generator

Standalone character-asset generator for House VN.

## What it does
- SDXL + IP-Adapter character reference
- 512x768 full-body game assets
- body/build controls and free-form body edits
- same/new seed regeneration
- optional transparent PNG via rembg
- local web UI at http://127.0.0.1:8010

## Requirements
- Windows + Python 3.10+
- ComfyUI running at http://127.0.0.1:8188
- SDXL checkpoint configured in `workflows/character_asset_sdxl_ipadapter.json`
- IP-Adapter Plus SDXL + CLIP Vision installed in ComfyUI
- `rembg` for alpha background removal

## Run
1. Start ComfyUI.
2. Install dependencies: `pip install -r requirements.txt`
3. Run `run_generator.bat`.
4. Open http://127.0.0.1:8010

The generator does not modify the existing image-generator repository.
