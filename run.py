import subprocess
import sys
subprocess.run([sys.executable, "predict_modified.py", "model=ultralytics/runs/detect/train_model/weights/best.pt", "source=dataset/valid/images/video.mp4"])