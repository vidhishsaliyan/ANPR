import os
import sys
import uuid
import cv2
import easyocr
import torch
import numpy as np
from pathlib import Path
from difflib import SequenceMatcher

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ultralytics import YOLO
from image_preprocess import process

MODEL_PATH = PROJECT_ROOT / "ultralytics" / "runs" / "detect" / "train_model" / "weights" / "best.pt"
model = YOLO(str(MODEL_PATH))
reader = easyocr.Reader(['en'], gpu=True)

TEMP_DIR = PROJECT_ROOT / "backend" / "temp_crops"
os.makedirs(TEMP_DIR, exist_ok=True)

DIGIT_TO_CHAR = {'0': 'O', '1': 'I', '2': 'Z', '4': 'A', '5': 'S', '8': 'B', '6': 'G'}
CHAR_TO_DIGIT = {'O': '0', 'D': '0', 'Q': '0', 'I': '1', 'L': '1', 'Z': '2', 'A': '4', 'S': '5', 'G': '6', 'B': '8'}

# --- QUALITY FILTERS ---
MIN_PLATE_WIDTH = 40
MIN_PLATE_HEIGHT = 15
MIN_BLUR_THRESHOLD = 15.0
MIN_OCR_CONFIDENCE = 0.25


def clean_plate_text(raw_text: str) -> str:
    text = ''.join(c for c in raw_text if c.isalnum()).upper()
    if len(text) >= 2:
        text = DIGIT_TO_CHAR.get(text[0], text[0]) + DIGIT_TO_CHAR.get(text[1], text[1]) + text[2:]
    if len(text) >= 6:
        last4 = [CHAR_TO_DIGIT.get(c, c) for c in text[-4:]]
        text = text[:-4] + ''.join(last4)
    return text


def parse_yolo_detections(results):
    boxes = []
    for item in results:
        if isinstance(item, torch.Tensor) and len(item) > 0:
            for row in item:
                x1, y1, x2, y2, conf, cls = row[:6].tolist()
                boxes.append((int(x1), int(y1), int(x2), int(y2), float(conf)))
    return boxes


def is_sharp_and_close(crop_img):
    h, w = crop_img.shape[:2]
    if w < MIN_PLATE_WIDTH or h < MIN_PLATE_HEIGHT:
        return False

    gray = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY) if len(crop_img.shape) == 3 else crop_img
    variance = cv2.Laplacian(gray, cv2.CV_64F).var()
    if variance < MIN_BLUR_THRESHOLD:
        return False

    return True


def extract_plate_from_frame(frame):
    temp_frame_path = str(TEMP_DIR / f"frame_{uuid.uuid4().hex[:8]}.jpg")
    cv2.imwrite(temp_frame_path, frame)

    detections = []
    try:
        results = model.predict(source=temp_frame_path, conf=0.25, verbose=False)
        boxes = parse_yolo_detections(results)

        for x1, y1, x2, y2, _ in boxes:
            box_w = abs(x2 - x1)
            box_h = abs(y2 - y1)

            if box_w < MIN_PLATE_WIDTH or box_h < MIN_PLATE_HEIGHT:
                continue

            raw_crop = frame[y1:y2, x1:x2]
            if raw_crop.size == 0 or not is_sharp_and_close(raw_crop):
                continue

            enhanced = process(frame, [x1, y1, x2, y2])
            ocr_res = reader.readtext(enhanced)

            for item in ocr_res:
                raw_text, conf = item[1], item[2]
                cleaned = clean_plate_text(raw_text)

                if len(cleaned) >= 7 and conf >= MIN_OCR_CONFIDENCE:
                    unique_id = uuid.uuid4().hex

                    # 1. Save the cropped plate in backend/temp_crops (kept permanently on backend)
                    crop_filename = f"crop_{unique_id}.jpg"
                    crop_path = str(TEMP_DIR / crop_filename)
                    cv2.imwrite(crop_path, enhanced)

                    # 2. Save the full car photo with the green box and plate number annotated
                    annotated_frame = frame.copy()
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    label = cleaned
                    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                    cv2.rectangle(annotated_frame, (x1, max(0, y1 - th - 10)), (x1 + tw + 10, y1), (0, 255, 0), cv2.FILLED)
                    cv2.putText(annotated_frame, label, (x1 + 5, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)

                    car_filename = f"car_{unique_id}.jpg"
                    car_path = str(TEMP_DIR / car_filename)
                    cv2.imwrite(car_path, annotated_frame)

                    detections.append({
                        "plate": cleaned,
                        "crop_path": crop_path,      # Kept in backend
                        "image_path": car_path,     # Uploaded to Supabase as the full car photo
                        "confidence": float(conf)
                    })
    finally:
        if os.path.exists(temp_frame_path):
            os.remove(temp_frame_path)

    return detections


def detect_plates_from_image(image_path: str):
    """Process a single image file."""
    frame = cv2.imread(image_path)
    if frame is None:
        return []
    return extract_plate_from_frame(frame)


def are_plates_similar(p1: str, p2: str) -> bool:
    if p1 == p2:
        return True
    return SequenceMatcher(None, p1, p2).ratio() >= 0.75


def detect_plates_from_video(video_path: str):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_stride = max(1, int(fps / 2.5))

    raw_detections = []
    frame_count = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        frame_count += 1
        if frame_count % frame_stride != 0:
            continue

        for det in extract_plate_from_frame(frame):
            raw_detections.append(det)

    cap.release()

    if not raw_detections:
        return []

    clusters = []
    for det in raw_detections:
        matched = False
        for cluster in clusters:
            rep = max(cluster, key=lambda x: x["confidence"])
            if are_plates_similar(det["plate"], rep["plate"]):
                cluster.append(det)
                matched = True
                break
        if not matched:
            clusters.append([det])

    final_vehicles = []
    for cluster in clusters:
        best_det = max(cluster, key=lambda x: x["confidence"])
        if len(cluster) >= 2 or best_det["confidence"] >= 0.45:
            final_vehicles.append(best_det)

    return final_vehicles
