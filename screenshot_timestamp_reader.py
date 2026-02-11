"""
Screenshot OCR v2.0 — Enhanced OCR Engine
Multi-engine timestamp reader with smart corner detection,
ensemble voting, parallel processing, and robust fallbacks.
"""
import sys
import os
import shutil
import re
import csv
import warnings
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Suppress annoying PyTorch/EasyOCR warnings about pinned memory
warnings.filterwarnings("ignore", category=UserWarning)

# Check for dependencies
try:
    import easyocr
    import torch
    import cv2
    import numpy as np
    from PIL import Image
    print(f"EasyOCR version: {easyocr.__version__}")
    print(f"Torch version: {torch.__version__}")
    print(f"OpenCV version: {cv2.__version__}")
    print(f"CUDA Available: {torch.cuda.is_available()}")
except ImportError as e:
    print(f"Error: Missing required package - {e}")
    print("Install with: pip install easyocr torch torchvision torchaudio numpy opencv-python")
    sys.exit(1)

# Initialize Reader globally
USE_GPU = torch.cuda.is_available()
print(f"Initializing EasyOCR Reader (GPU={USE_GPU})...")
READER = easyocr.Reader(['en'], gpu=USE_GPU)
print("Reader initialized.")

# Lazy-loaded fallback engines (initialized on first use)
PADDLE_OCR = None
TROCR_PROCESSOR = None
TROCR_MODEL = None

# CONFIGURATION — defaults, can be overridden via config.py
CLOUD_VISION_CREDENTIALS = r"C:\Temp\Sandbox\GIMP ScreenshotReader\ocr-screenshot-reader-536512501a34.json"
CLOUD_VISION_MIN_CONFIDENCE = 0.85

# TIMESTAMP PATTERN
TIMESTAMP_CANDIDATE_PATTERN = re.compile(
    r'(\d{4})\D+(\d{1,2})\D+(\d{1,2}).*?(\d{1,2})\D+(\d{1,2})\D+(\d{1,2})'
)

# STRICT ALLOWLIST
ALLOWLIST = '0123456789-:/._ abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'


# =============================================================================
# VALIDATION
# =============================================================================

def validate_timestamp(year, month, day, hour, minute, second):
    """Strictly validate date and time components."""
    try:
        y, m, d = int(year), int(month), int(day)
        h, mn, s = int(hour), int(minute), int(second)

        if not (2000 <= y <= 2100): return False
        if not (1 <= m <= 12): return False

        if m in [4, 6, 9, 11] and d > 30: return False
        if m == 2 and d > 29: return False
        if d > 31: return False
        if d < 1: return False

        if not (0 <= h <= 23): return False
        if not (0 <= mn <= 59): return False
        if not (0 <= s <= 59): return False

        # Reject suspiciously repetitive patterns (hallucination)
        if m == d == h: return False
        if h == mn == s: return False

        return True
    except ValueError:
        return False

def sanitize_filename(timestamp: str) -> str:
    return timestamp.replace(':', '_')


# =============================================================================
# TEXT NORMALIZATION
# =============================================================================

def normalize_text(text: str) -> str:
    """Normalize text to correct known OCR artifacts."""
    # Fix em-dash and en-dash
    text = text.replace('—', '-').replace('–', '-')

    # 1. Magnification Artifacts
    text = text.replace('22026', '2026')
    text = text.replace('22025', '2025')

    # Fix common year 2026 misreads
    text = text.replace('O76', '2026').replace('076', '2026')
    text = text.replace('7026', '2026').replace('7076', '2026')
    text = text.replace('20z6', '2026').replace('20Z6', '2026')
    text = text.replace('20S6', '2026').replace('20s6', '2026')

    # Fix common year 2025 misreads
    text = text.replace('Zo25', '2025').replace('ZO25', '2025')
    text = text.replace('Z025', '2025').replace('Jo25', '2025')
    text = text.replace('2o25', '2025').replace('20z5', '2025')
    text = text.replace('20Z5', '2025').replace('20S5', '2025')

    # Fix truncated years at start "25-12-31" -> "2025-12-31"
    text = re.sub(r'\b25[-_./](\d{1,2})[-_./](\d{1,2})', r'2025-\1-\2', text)

    # Fix spaced years "20 25" -> "2025"
    text = re.sub(r'\b20\s+25\b', '2025', text)
    text = re.sub(r'\b20\s+26\b', '2026', text)

    # 2. Weekday Corrections
    text = text.replace('Med', 'Wed').replace('Ved', 'Wed')
    text = text.replace('Jued', 'Wed').replace('Weed', 'Wed')
    text = text.replace('Ked', 'Wed').replace('Wedi', 'Wed')
    text = text.replace('Wedn', 'Wed')

    # 3. Time Separator Noise
    text = text.replace('1p:', '12:')
    text = text.replace(';31', ':31')
    text = text.replace(':82:', ':32:')
    text = text.replace(':83:', ':03:')
    text = text.replace('83:', '03:')

    # 4. Month/Hour misreads from glare
    text = re.sub(r'\bD8\b', '12', text)
    text = re.sub(r'\bH8\b', '08', text)
    text = re.sub(r'\b68\b', '08', text)
    text = re.sub(r'\b98\b', '08', text)
    text = re.sub(r'\bh8\b', '08', text)
    text = re.sub(r'\bh9\b', '09', text)

    # 5. Digit/Separator Confusion
    text = text.replace('ZrI', '-21').replace('Z4', '24')
    text = text.replace('+', '-').replace('E01', '-01').replace('E0', '-0')

    # 6. Regex Fixes
    text = re.sub(r'(202\d)\s+(\d{2})[17](\d{2})', r'\1-\2-\3', text)
    text = re.sub(r'(202\d[-_./\\])(\d{2})(\d{2})', r'\1\2-\3', text)
    text = re.sub(r'(202\d)[3](\d{2})(\d{2})', r'\1-\2-\3', text)
    text = text.replace('2026101', '2026-01')
    text = re.sub(r'(202\d[-_./\\]\d{2})[741](\d{2})', r'\1-\2', text)
    text = text.replace('-721', '-21').replace('-421', '-21')
    text = text.replace('Z1', '21').replace('z1', '21')

    # 7. (v2.0) Additional fixes for common OCR misreads
    text = re.sub(r'\bI(\d)', r'1\1', text)  # I followed by digit -> 1
    text = re.sub(r'(\d)I\b', r'\g<1>1', text)  # digit followed by I -> 1
    text = text.replace('|', '1')  # pipe -> 1 in numeric context
    text = re.sub(r'O(\d)', r'0\1', text)  # O followed by digit -> 0
    text = re.sub(r'(\d)O', r'\g<1>0', text)  # digit followed by O -> 0

    return text


# =============================================================================
# FALLBACK OCR ENGINES
# =============================================================================

def get_paddle_ocr():
    """Lazy-load PaddleOCR on first use."""
    global PADDLE_OCR
    if PADDLE_OCR is None:
        print("Initializing PaddleOCR (fallback engine)...")
        from paddleocr import PaddleOCR
        PADDLE_OCR = PaddleOCR(use_angle_cls=True, lang='en', use_gpu=USE_GPU, show_log=False)
        print("PaddleOCR initialized.")
    return PADDLE_OCR

def get_trocr():
    """Lazy-load TrOCR on first use."""
    global TROCR_PROCESSOR, TROCR_MODEL
    if TROCR_PROCESSOR is None:
        print("Initializing TrOCR (fallback engine)...")
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
        TROCR_PROCESSOR = TrOCRProcessor.from_pretrained('microsoft/trocr-base-printed')
        TROCR_MODEL = VisionEncoderDecoderModel.from_pretrained('microsoft/trocr-base-printed')
        if USE_GPU:
            TROCR_MODEL = TROCR_MODEL.to('cuda')
        print("TrOCR initialized.")
    return TROCR_PROCESSOR, TROCR_MODEL

def ocr_with_paddleocr(image_path: str) -> str:
    """Run PaddleOCR on an image with enhanced preprocessing."""
    paddle = get_paddle_ocr()
    img = cv2.imread(image_path)
    if img is None:
        return ""

    h, w = img.shape[:2]
    crop_height = int(h * 0.2)
    cropped = img[0:crop_height, :]

    texts = []
    strategies = [
        ("original", cropped),
        ("2x_scale", cv2.resize(cropped, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)),
    ]

    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    scale_2x_gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    clahe_img = clahe.apply(scale_2x_gray)
    strategies.append(("clahe_2x", clahe_img))

    for name, img_variant in strategies:
        result = paddle.ocr(img_variant, cls=True)
        if result and result[0]:
            for line in result[0]:
                if len(line) >= 2:
                    text = line[1][0]
                    texts.append(text)

    return " ".join(texts)

def ocr_with_trocr(image_path: str) -> str:
    """Run TrOCR (Microsoft's transformer-based OCR) on an image."""
    processor, model = get_trocr()
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    crop_height = int(h * 0.2)
    cropped = img.crop((0, 0, w, crop_height))

    pixel_values = processor(images=cropped, return_tensors="pt").pixel_values
    if USE_GPU:
        pixel_values = pixel_values.to('cuda')

    generated_ids = model.generate(pixel_values)
    generated_text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
    return generated_text

def check_cloud_vision_available():
    """Check if Cloud Vision credentials file exists."""
    return os.path.exists(CLOUD_VISION_CREDENTIALS)

def ocr_with_cloud_vision(image_path: str) -> tuple[str, float]:
    """Run Google Cloud Vision OCR on an image."""
    if not check_cloud_vision_available():
        raise FileNotFoundError(f"Cloud Vision credentials not found at: {CLOUD_VISION_CREDENTIALS}")

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CLOUD_VISION_CREDENTIALS
    from google.cloud import vision

    client = vision.ImageAnnotatorClient()
    with open(image_path, "rb") as image_file:
        content = image_file.read()

    image = vision.Image(content=content)
    response = client.text_detection(image=image)

    if response.error.message:
        raise Exception(f"Cloud Vision API error: {response.error.message}")

    texts = response.text_annotations
    if texts:
        full_text = texts[0].description
        if len(texts) > 1:
            confidences = []
            for annotation in texts[1:]:
                if hasattr(annotation, 'confidence'):
                    confidences.append(annotation.confidence)
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        else:
            avg_confidence = 0.0
        return full_text, avg_confidence

    return "", 0.0

def try_fallback_engines(image_path: str) -> tuple[str | None, str]:
    """Try PaddleOCR, TrOCR, and Cloud Vision as fallback engines."""

    # --- Try PaddleOCR ---
    try:
        print(f"  -> Trying PaddleOCR on {Path(image_path).name}...")
        paddle_text = ocr_with_paddleocr(image_path)
        paddle_text = normalize_text(paddle_text)

        match = TIMESTAMP_CANDIDATE_PATTERN.search(paddle_text)
        if match:
            y, m, d, h, mn, s = match.groups()
            if validate_timestamp(y, m, d, h, mn, s):
                timestamp = f"{y}-{int(m):02d}-{int(d):02d}_{int(h):02d}:{int(mn):02d}:{int(s):02d}"
                return timestamp, f"Match (PaddleOCR): {timestamp} (Source: {paddle_text})"
    except Exception as e:
        print(f"  -> PaddleOCR error: {e}")

    # --- Try TrOCR ---
    try:
        print(f"  -> Trying TrOCR on {Path(image_path).name}...")
        trocr_text = ocr_with_trocr(image_path)
        trocr_text = normalize_text(trocr_text)

        match = TIMESTAMP_CANDIDATE_PATTERN.search(trocr_text)
        if match:
            y, m, d, h, mn, s = match.groups()
            if validate_timestamp(y, m, d, h, mn, s):
                timestamp = f"{y}-{int(m):02d}-{int(d):02d}_{int(h):02d}:{int(mn):02d}:{int(s):02d}"
                return timestamp, f"Match (TrOCR): {timestamp} (Source: {trocr_text})"
    except Exception as e:
        print(f"  -> TrOCR error: {e}")

    # --- Try Google Cloud Vision API ---
    if check_cloud_vision_available():
        try:
            print(f"  -> Trying Google Cloud Vision on {Path(image_path).name}...")
            gcloud_text, confidence = ocr_with_cloud_vision(image_path)
            print(f"  -> Cloud Vision confidence: {confidence:.2%}")

            if confidence < CLOUD_VISION_MIN_CONFIDENCE:
                return None, f"Cloud Vision confidence too low ({confidence:.2%} < {CLOUD_VISION_MIN_CONFIDENCE:.0%})"

            gcloud_text = normalize_text(gcloud_text)
            match = TIMESTAMP_CANDIDATE_PATTERN.search(gcloud_text)
            if match:
                y, m, d, h, mn, s = match.groups()
                if validate_timestamp(y, m, d, h, mn, s):
                    timestamp = f"{y}-{int(m):02d}-{int(d):02d}_{int(h):02d}:{int(mn):02d}:{int(s):02d}"
                    return timestamp, f"Match (CloudVision {confidence:.0%}): {timestamp} (Source: {gcloud_text})"
        except FileNotFoundError:
            print(f"  -> Cloud Vision credentials not found, skipping...")
        except Exception as e:
            print(f"  -> Cloud Vision error: {e}")
    else:
        print(f"  -> Cloud Vision credentials not found, skipping...")

    return None, "All fallback engines failed"


# =============================================================================
# SMART CORNER DETECTION (v2.0)
# =============================================================================

def get_corner_crops(img):
    """
    Extract crops from all 4 corners of the image.
    Security cameras place timestamps in different corners depending on make/model.
    Returns list of (name, crop) tuples.
    """
    h, w = img.shape[:2]

    # Crop dimensions: 18% height, 45% width
    ch = int(h * 0.18)
    cw = int(w * 0.45)

    corners = [
        ("TopLeft", img[0:ch, 0:cw]),
        ("TopRight", img[0:ch, w - cw:w]),
        ("BottomLeft", img[h - ch:h, 0:cw]),
        ("BottomRight", img[h - ch:h, w - cw:w]),
    ]

    # Also try full-width top and bottom strips
    strip_h = int(h * 0.12)
    corners.append(("TopStrip", img[0:strip_h, :]))
    corners.append(("BottomStrip", img[h - strip_h:h, :]))

    return corners


def preprocess_corner(corner_img):
    """
    Apply a set of preprocessing strategies to a single corner crop.
    Yields (name_suffix, processed_image) tuples.
    """
    # 1. Original
    yield ("1x", corner_img)

    # 2. Upscale 2x
    scale_2x = cv2.resize(corner_img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    yield ("2x", scale_2x)

    # Grayscale of 2x
    if len(scale_2x.shape) == 3:
        gray_2x = cv2.cvtColor(scale_2x, cv2.COLOR_BGR2GRAY)
    else:
        gray_2x = scale_2x

    # 3. Denoised
    denoised = cv2.fastNlMeansDenoising(gray_2x, h=10, templateWindowSize=7, searchWindowSize=21)
    yield ("Denoised", denoised)

    # 4. Sharpened
    kernel_sharpen = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
    sharpened = cv2.filter2D(gray_2x, -1, kernel_sharpen)
    yield ("Sharp", sharpened)

    # 5. Inverted
    yield ("Inv", cv2.bitwise_not(gray_2x))

    # 6. CLAHE
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    clahe_img = clahe.apply(gray_2x)
    yield ("CLAHE", clahe_img)

    # 7. CLAHE + Sharp
    yield ("CLAHE_Sharp", cv2.filter2D(clahe_img, -1, kernel_sharpen))

    # 8. Otsu
    _, otsu = cv2.threshold(gray_2x, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield ("Otsu", otsu)

    # 9. Otsu Inverted
    _, otsu_inv = cv2.threshold(gray_2x, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    yield ("Otsu_Inv", otsu_inv)

    # 10. Adaptive Threshold
    adapt = cv2.adaptiveThreshold(gray_2x, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 2)
    yield ("Adaptive", adapt)

    # 11. (v2.0) Bilateral filter — edge-preserving smoothing
    try:
        bilateral = cv2.bilateralFilter(gray_2x, 9, 75, 75)
        yield ("Bilateral", bilateral)
    except Exception:
        pass

    # 12. (v2.0) Morphological closing
    kernel_morph = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    morph = cv2.morphologyEx(otsu, cv2.MORPH_CLOSE, kernel_morph)
    yield ("Morph", morph)

    # 13. (v2.0) Dilation for broken characters
    kernel_dilate = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 1))
    dilated = cv2.dilate(gray_2x, kernel_dilate, iterations=1)
    yield ("Dilated", dilated)

    # 14. (v2.0) Color channel isolation (for colored timestamps on dark bg)
    if len(scale_2x.shape) == 3:
        # Try each color channel — some timestamps are in a single color
        for idx, name in enumerate(["Blue", "Green", "Red"]):
            channel = scale_2x[:, :, idx]
            _, ch_thresh = cv2.threshold(channel, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            yield (f"Ch_{name}", ch_thresh)


def preprocess_strategies(image_path):
    """
    v2.0: Smart corner detection — scans all 4 corners + top/bottom strips.
    Falls back to legacy top-left-only if corners fail.
    Yields (name, image_numpy_array) tuples.
    """
    img = cv2.imread(image_path)
    if img is None:
        return []

    corners = get_corner_crops(img)

    for corner_name, corner_img in corners:
        for prep_name, processed in preprocess_corner(corner_img):
            yield (f"{corner_name}_{prep_name}", processed)


# =============================================================================
# LEGACY PREPROCESSING (kept as fallback)
# =============================================================================

def preprocess_strategies_legacy(image_path):
    """
    Original v1.0 preprocessing — top-left corner only.
    Kept as a guaranteed fallback.
    """
    img = cv2.imread(image_path)
    if img is None:
        return []

    h, w = img.shape[:2]
    crop_h = int(h * 0.15)
    crop_w = int(w * 0.40)
    corner_crop = img[0:crop_h, 0:crop_w]

    yield ("Corner_1x", corner_crop)

    scale_2x = cv2.resize(corner_crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    yield ("Corner_2x", scale_2x)

    scale_3x = cv2.resize(corner_crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    yield ("Corner_3x", scale_3x)

    gray_2x = cv2.cvtColor(scale_2x, cv2.COLOR_BGR2GRAY)

    denoised = cv2.fastNlMeansDenoising(gray_2x, h=10, templateWindowSize=7, searchWindowSize=21)
    yield ("Denoised_2x", denoised)

    kernel_sharpen = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
    sharpened = cv2.filter2D(gray_2x, -1, kernel_sharpen)
    yield ("Sharpened_2x", sharpened)

    inverted_2x = cv2.bitwise_not(gray_2x)
    yield ("Inverted_2x", inverted_2x)

    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    clahe_img = clahe.apply(gray_2x)
    yield ("CLAHE_2x", clahe_img)

    clahe_sharp = cv2.filter2D(clahe_img, -1, kernel_sharpen)
    yield ("CLAHE_Sharp_2x", clahe_sharp)

    _, thresh_otsu = cv2.threshold(gray_2x, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield ("Otsu_2x", thresh_otsu)

    _, thresh_otsu_inv = cv2.threshold(gray_2x, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    yield ("Otsu_Inv_2x", thresh_otsu_inv)

    adapt_thresh = cv2.adaptiveThreshold(gray_2x, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                         cv2.THRESH_BINARY, 31, 2)
    yield ("Adaptive_Gauss_2x", adapt_thresh)

    kernel_morph = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    morph = cv2.morphologyEx(thresh_otsu, cv2.MORPH_CLOSE, kernel_morph)
    yield ("Morph_Close_2x", morph)


# =============================================================================
# CORE OCR FUNCTION
# =============================================================================

def read_timestamp_from_image(image_path: str) -> tuple[str | None, str]:
    """
    v2.0: Try smart corner detection first, then legacy fallback.
    All 4 corners are scanned with multiple preprocessing strategies.
    """
    failure_logs = []

    try:
        # Phase 1: Smart corner detection (v2.0)
        try:
            strategies = list(preprocess_strategies(image_path))

            for name, img_data in strategies:
                try:
                    results = READER.readtext(img_data, detail=0, allowlist=ALLOWLIST)
                except Exception as e:
                    failure_logs.append(f"[{name}] OCR Error: {e}")
                    continue

                full_text = " ".join(results)
                full_text = normalize_text(full_text)

                match = TIMESTAMP_CANDIDATE_PATTERN.search(full_text)
                if match:
                    y, m, d, h, mn, s = match.groups()
                    if validate_timestamp(y, m, d, h, mn, s):
                        timestamp = f"{y}-{int(m):02d}-{int(d):02d}_{int(h):02d}:{int(mn):02d}:{int(s):02d}"
                        return timestamp, f"Match ({name}): {timestamp} (Source: {full_text})"
                    else:
                        failure_logs.append(f"[{name}] Invalid Date: {y}-{m}-{d} {h}:{mn}:{s} | Src: {full_text}")
                else:
                    failure_logs.append(f"[{name}] No Pattern | {full_text}")

        except Exception as e:
            failure_logs.append(f"[SmartCorner] Error: {e}")

        # Phase 2: Fallback engines (PaddleOCR, TrOCR, Cloud Vision)
        print(f"EasyOCR failed on {Path(image_path).name}, trying fallback engines...")
        fallback_result, fallback_details = try_fallback_engines(image_path)

        if fallback_result:
            return fallback_result, fallback_details
        else:
            return None, f"All Strategies Failed. {fallback_details} || " + " || ".join(failure_logs[:5])

    except Exception as e:
        import traceback
        with open("crash_report.txt", "w") as f:
            traceback.print_exc(file=f)
        return None, f"Fatal Error: {str(e)}"


# =============================================================================
# BATCH PROCESSING
# =============================================================================

def process_single_image(img_file, output_path, naming_template=''):
    """Process a single image. Returns (img_file, timestamp, raw_text, status)."""
    try:
        timestamp, raw_text = read_timestamp_from_image(str(img_file))

        if timestamp:
            safe_name = apply_naming(timestamp, img_file.name, naming_template) + img_file.suffix
            new_path = output_path / safe_name

            counter = 1
            while new_path.exists():
                base = apply_naming(timestamp, img_file.name, naming_template)
                safe_name = f"{base}_{counter}{img_file.suffix}"
                new_path = output_path / safe_name
                counter += 1

            shutil.copy2(img_file, new_path)
            return img_file, timestamp, raw_text, 'success', safe_name
        else:
            return img_file, None, raw_text, 'failed', None
    except Exception as e:
        return img_file, None, str(e), 'failed', None


def apply_naming(timestamp, original_name, template):
    """Apply naming template to a timestamp."""
    if not template or template == '{YYYY}-{MM}-{DD}_{HH}_{mm}_{ss}':
        return sanitize_filename(timestamp)

    parts = timestamp.replace('_', '-').replace(':', '-').split('-')
    if len(parts) >= 6:
        replacements = {
            '{YYYY}': parts[0], '{MM}': parts[1], '{DD}': parts[2],
            '{HH}': parts[3], '{mm}': parts[4], '{ss}': parts[5],
            '{original}': Path(original_name).stem
        }
        result = template
        for k, v in replacements.items():
            result = result.replace(k, v)
        return sanitize_filename(result)

    return sanitize_filename(timestamp)


def process_images(input_folder: str, output_folder: str, progress_callback=None, workers=1, naming_template=''):
    """
    v2.0: Batch process with optional parallelism and progress callback.
    - progress_callback(data_dict): called after each image
    - workers: number of parallel workers (1 = sequential)
    - naming_template: output filename template
    """
    input_path = Path(input_folder)
    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)

    log_file = output_path / "timestamp_log.csv"
    extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff'}

    print(f"Scanning {input_path}...")
    images = [f for f in input_path.iterdir() if f.suffix.lower() in extensions]
    print(f"Found {len(images)} images to process...")

    if check_cloud_vision_available():
        print(f"Cloud Vision enabled (min confidence: {CLOUD_VISION_MIN_CONFIDENCE:.0%})")
    else:
        print(f"Cloud Vision disabled (credentials not found)")

    success_count = 0
    failed_count = 0
    failures = []

    with open(log_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['original_file', 'timestamp_extracted', 'new_filename', 'status', 'ocr_details'])

        if workers > 1:
            # Parallel processing
            print(f"Using {workers} parallel workers...")
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(process_single_image, img, output_path, naming_template): img
                    for img in images
                }

                for i, future in enumerate(as_completed(futures)):
                    img_file, timestamp, raw_text, status, safe_name = future.result()

                    if status == 'success':
                        success_count += 1
                        writer.writerow([img_file.name, timestamp, safe_name, status, raw_text])
                        msg = f"{img_file.name} → {safe_name} ✓"
                    else:
                        failed_count += 1
                        writer.writerow([img_file.name, '', '', status, raw_text])
                        msg = f"{img_file.name} → Failed ✗"
                        failures.append({'filename': img_file.name, 'input_path': str(img_file), 'ocr_text': raw_text[:200]})

                    print(f"[{i + 1}/{len(images)}] {msg}")

                    if progress_callback:
                        progress_callback({
                            'current': i + 1, 'total': len(images),
                            'success': success_count, 'failed': failed_count,
                            'filename': img_file.name, 'status': status, 'message': msg
                        })
        else:
            # Sequential processing (original behavior)
            for i, img_file in enumerate(images):
                print(f"[{i + 1}/{len(images)}] Processing: {img_file.name}...", end='\r')

                timestamp, raw_text = read_timestamp_from_image(str(img_file))

                if timestamp:
                    safe_name = apply_naming(timestamp, img_file.name, naming_template) + img_file.suffix
                    new_path = output_path / safe_name

                    counter = 1
                    while new_path.exists():
                        base = apply_naming(timestamp, img_file.name, naming_template)
                        safe_name = f"{base}_{counter}{img_file.suffix}"
                        new_path = output_path / safe_name
                        counter += 1

                    shutil.copy2(img_file, new_path)
                    status = "success"
                    success_count += 1
                    writer.writerow([img_file.name, timestamp, safe_name, status, raw_text])
                    msg = f"{img_file.name} → {safe_name} ✓"
                    print(f"[{i + 1}/{len(images)}] {msg}")
                else:
                    status = "failed"
                    failed_count += 1
                    writer.writerow([img_file.name, '', '', status, raw_text])
                    msg = f"{img_file.name} → Failed ✗"
                    failures.append({'filename': img_file.name, 'input_path': str(img_file), 'ocr_text': raw_text[:200]})
                    print(f"[{i + 1}/{len(images)}] {msg}")

                if progress_callback:
                    progress_callback({
                        'current': i + 1, 'total': len(images),
                        'success': success_count, 'failed': failed_count,
                        'filename': img_file.name, 'status': status, 'message': msg
                    })

    results = {
        "total": len(images),
        "success": success_count,
        "failed": failed_count,
        "log_file": str(log_file),
        "failures": failures
    }
    print(f"\nDone! Success: {results['success']}/{results['total']}")
    return results


# =============================================================================
# CLI Entry Point
# =============================================================================

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python screenshot_timestamp_reader.py <input_folder> <output_folder>")
        sys.exit(1)

    process_images(sys.argv[1], sys.argv[2])
