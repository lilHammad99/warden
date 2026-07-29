"""Open webcams (OpenCV index) and IP cameras (RTSP URL) by name."""

import cv2


class CameraManager:
    def __init__(self, cameras: dict, default: str):
        self.cameras = cameras  # name -> int index or rtsp url
        self.default = default if default in cameras else next(iter(cameras))

    def names(self) -> list[str]:
        return list(self.cameras.keys())

    def resolve(self, name: str | None) -> str:
        if not name or name.lower() in ("default", "camera"):
            return self.default
        key = name.strip().lower()
        for cam in self.cameras:
            if cam.lower() == key:
                return cam
        raise KeyError(f"No camera named '{name}'. Available: {', '.join(self.names())}")

    def open(self, name: str | None = None) -> "cv2.VideoCapture":
        cam = self.resolve(name)
        source = self.cameras[cam]
        if isinstance(source, int) or (isinstance(source, str) and source.isdigit()):
            cap = cv2.VideoCapture(int(source), cv2.CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(str(source))
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"Could not open camera '{cam}' (source: {source}).")
        return cap

    def grab_frame(self, name: str | None = None):
        """One-shot frame grab. Reads a few frames so exposure settles."""
        cap = self.open(name)
        try:
            frame = None
            for _ in range(5):
                ok, f = cap.read()
                if ok:
                    frame = f
            if frame is None:
                raise RuntimeError("Camera opened but returned no frames.")
            return frame
        finally:
            cap.release()


def to_jpeg(frame) -> bytes:
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise RuntimeError("Could not encode frame as JPEG.")
    return buf.tobytes()
