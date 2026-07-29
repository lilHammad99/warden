"""Watch mode: background thread that monitors a camera.

Cheap motion gate (frame differencing) first; only when there is motion do
we run YOLO person detection. On a person: alert callback + snapshot,
then a cooldown so Jarvis doesn't spam.
"""

import datetime
import threading
import time
from pathlib import Path

import cv2


class Watcher(threading.Thread):
    def __init__(self, manager, camera_name: str, cfg: dict, alert):
        super().__init__(daemon=True, name=f"watcher-{camera_name}")
        self.manager = manager
        self.camera_name = camera_name
        self.cfg = cfg
        self.alert = alert  # callback(text, frame)
        self.stop_event = threading.Event()
        self.error: str | None = None
        self._yolo = None

    def _person_in(self, frame) -> bool:
        if self._yolo is None:
            from ultralytics import YOLO

            self._yolo = YOLO("yolov8n.pt")
        results = self._yolo.predict(
            frame, classes=[0], conf=self.cfg["person_confidence"], verbose=False
        )
        return any(len(r.boxes) > 0 for r in results)

    def _save_snapshot(self, frame) -> Path:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path(self.cfg["snapshot_dir"]) / f"{self.camera_name}_{ts}.jpg"
        cv2.imwrite(str(path), frame)
        return path

    def run(self):
        try:
            cap = self.manager.open(self.camera_name)
        except Exception as e:
            self.error = str(e)
            self.alert(f"Watch mode failed to start on {self.camera_name}: {e}", None)
            return
        prev_gray = None
        last_alert = 0.0
        cooldown = self.cfg["alert_cooldown_seconds"]
        try:
            while not self.stop_event.is_set():
                ok, frame = cap.read()
                if not ok:
                    time.sleep(1)
                    cap.release()
                    try:
                        cap = self.manager.open(self.camera_name)
                    except Exception:
                        pass
                    continue
                small = cv2.resize(frame, (320, 180))
                gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (7, 7), 0)
                motion = False
                if prev_gray is not None:
                    diff = cv2.absdiff(prev_gray, gray)
                    motion = (cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)[1] > 0).sum() > 300
                prev_gray = gray
                now = time.time()
                if motion and now - last_alert > cooldown and self._person_in(frame):
                    last_alert = now
                    path = self._save_snapshot(frame)
                    self.alert(
                        f"Sir, I see someone on the {self.camera_name} camera. "
                        f"Snapshot saved.", frame,
                    )
                    print(f"  [watch] person detected -> {path}")
                self.stop_event.wait(0.4)  # ~2 fps analysis
        finally:
            cap.release()

    def stop(self):
        self.stop_event.set()
