import os
import uuid
import shutil
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client
from plate_detector import detect_plates_from_image, detect_plates_from_video

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env file
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

try:
    db = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"Supabase init error: {e}")
    db = None

app = FastAPI(title="ANPR Gate API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


def upload_image_to_supabase(image_path: str):
    """Uploads a cropped plate image to Supabase storage."""
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        file_name = f"{uuid.uuid4()}.jpg"
        with open(image_path, "rb") as f:
            db.storage.from_("plate-images").upload(file_name, f.read(), {"content-type": "image/jpeg"})
        return db.storage.from_("plate-images").get_public_url(file_name)
    except Exception as e:
        print(f"Crop upload error: {e}")
        return None


def handle_entry(detections: list):
    """Saves vehicles entering if not already inside."""
    if not db:
        raise HTTPException(status_code=500, detail="Database connection failed.")

    saved, skipped = 0, 0
    for item in detections:
        plate = item["plate"]
        try:
            existing = db.table("vehicle_logs").select("id").eq("plate", plate).eq("status", "Inside").execute()
            if existing.data:
                skipped += 1
                continue

            image_path = item.get("image_path")
            image_url = upload_image_to_supabase(image_path)
            if image_path and os.path.exists(image_path):
                os.remove(image_path)

            db.table("vehicle_logs").insert({
                "plate": plate,
                "status": "Inside",
                "image_url": image_url,
            }).execute()
            saved += 1
        except Exception as e:
            print(f"Database error on entry: {e}")
            raise HTTPException(status_code=500, detail=f"Database entry error for plate {plate}: {str(e)}")

    if not detections:
        return {"message": "No license plate detected in image/video."}

    return {"message": "Entry processed."}


def handle_exit(detections: list):
    """Marks inside vehicles as exited."""
    if not db:
        raise HTTPException(status_code=500, detail="Database connection failed.")

    saved, skipped = 0, 0
    now = datetime.now(timezone.utc).isoformat()

    for item in detections:
        plate = item["plate"]
        try:
            result = db.table("vehicle_logs").select("id").eq("plate", plate).eq("status", "Inside").order("entry_time", desc=True).limit(1).execute()
            if not result.data:
                skipped += 1
                continue

            row_id = result.data[0]["id"]
            db.table("vehicle_logs").update({"exit_time": now, "status": "Exited"}).eq("id", row_id).execute()
            saved += 1
        except Exception as e:
            print(f"Database error on exit: {e}")
            raise HTTPException(status_code=500, detail=f"Database exit error for plate {plate}: {str(e)}")

    if not detections:
        return {"message": "No license plate detected in image/video."}

    if saved == 0:
        return {"message": "Vehicle exit not recorded: entry record not found in database."}
    elif skipped > 0:
        return {"message": "Exit processed. Note: Some vehicle(s) were not found inside."}
    return {"message": "Exit processed."}


def save_and_process(file: UploadFile, is_video: bool):
    """Saves temporary file, runs YOLO/OCR detection, and cleans up."""
    suffix = Path(file.filename).suffix or (".mp4" if is_video else ".jpg")
    temp_path = UPLOAD_DIR / f"{uuid.uuid4()}{suffix}"

    try:
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        if is_video:
            detections = detect_plates_from_video(str(temp_path))
        else:
            detections = detect_plates_from_image(str(temp_path))
    except Exception as e:
        print(f"Processing error: {e}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")
    finally:
        if temp_path.exists():
            temp_path.unlink()

    return detections


# --- GET LOGS ENDPOINT ---

@app.get("/api/logs")
def get_logs():
    """Returns all vehicle logs from Supabase."""
    if not db:
        raise HTTPException(status_code=500, detail="Database connection failed.")
    try:
        res = db.table("vehicle_logs").select("*").order("entry_time", desc=False).execute()
        return res.data or []
    except Exception as e:
        print(f"Error fetching logs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch logs: {str(e)}")


# --- 4 Endpoints for Photo & Video of Entry & Exit ---

@app.post("/api/entry/photo")
def entry_photo(file: UploadFile = File(...)):
    detections = save_and_process(file, is_video=False)
    return handle_entry(detections)


@app.post("/api/entry/video")
def entry_video(file: UploadFile = File(...)):
    detections = save_and_process(file, is_video=True)
    return handle_entry(detections)


@app.post("/api/exit/photo")
def exit_photo(file: UploadFile = File(...)):
    detections = save_and_process(file, is_video=False)
    return handle_exit(detections)


@app.post("/api/exit/video")
def exit_video(file: UploadFile = File(...)):
    detections = save_and_process(file, is_video=True)
    return handle_exit(detections)
