"""
Screenshot OCR v2.0 — Configuration Manager
Loads/saves settings from config.json, auto-creates with defaults.
"""
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')

DEFAULTS = {
    "engines": {
        "easyocr": True,
        "paddleocr": True,
        "trocr": True,
        "cloud_vision": True
    },
    "cloud_vision_min_confidence": 0.85,
    "cloud_vision_credentials": r"C:\Temp\Sandbox\GIMP ScreenshotReader\ocr-screenshot-reader-536512501a34.json",
    "parallel_workers": 2,
    "naming_template": "{YYYY}-{MM}-{DD}_{HH}_{mm}_{ss}",
    "scan_all_corners": True
}

def load():
    """Load config from disk, or create defaults."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                cfg = json.load(f)
            # Merge missing keys from defaults
            for key, val in DEFAULTS.items():
                if key not in cfg:
                    cfg[key] = val
            return cfg
        except Exception:
            return dict(DEFAULTS)
    else:
        save(DEFAULTS)
        return dict(DEFAULTS)

def save(cfg):
    """Save config to disk."""
    with open(CONFIG_PATH, 'w') as f:
        json.dump(cfg, f, indent=2)

def get(key, default=None):
    """Get a single config value."""
    cfg = load()
    return cfg.get(key, default)
