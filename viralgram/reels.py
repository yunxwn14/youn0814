"""게시물 이미지로 릴스용 세로 영상(1080x1920, 9:16) 만들기.

인스타 앱은 사진만으로 릴스를 만들 수 있지만 API 는 영상 파일만 받으므로,
각 이미지를 흐린 배경 위에 올리고 천천히 확대되는 슬라이드쇼 MP4 로 변환한다.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

log = logging.getLogger(__name__)

W, H = 1080, 1920
FPS = 30
FIRST_SECONDS = 4.0  # 썸네일(첫 장)은 조금 더 길게
OTHER_SECONDS = 3.0


def vertical_frame(src: Path, dst: Path) -> Path:
    """4:5 이미지를 9:16 화면 가운데에 두고, 위아래는 같은 이미지를 흐리게 채운다."""
    img = Image.open(src).convert("RGB")
    bg = ImageOps.fit(img, (W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(40))
    bg = ImageEnhance.Brightness(bg).enhance(0.45)
    fg = ImageOps.contain(img, (W, H), Image.LANCZOS)
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    bg.save(dst, "PNG")
    return dst


def _zoom_frames(frame: Image.Image, n: int, zoom_to: float = 1.06):
    """가운데 기준으로 천천히 확대되는 프레임들.
    ffmpeg zoompan 은 위치를 정수 픽셀로 반올림해 화면이 떨리므로, 소수점 좌표로 잘라 확대한다."""
    for i in range(n):
        z = 1 + (zoom_to - 1) * (i / max(n - 1, 1))
        w, h = W / z, H / z
        x0, y0 = (W - w) / 2, (H - h) / 2
        yield frame.resize((W, H), Image.BICUBIC, box=(x0, y0, x0 + w, y0 + h))


def make_reel(pages: list[Path], out: Path) -> Path:
    """이미지들을 순서대로 이어 붙인 MP4 를 만든다 (무음 오디오 트랙 포함)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    frames = [vertical_frame(p, out.parent / f"reel_{i:02d}.png") for i, p in enumerate(pages)]
    durations = [FIRST_SECONDS] + [OTHER_SECONDS] * (len(frames) - 1)
    total = sum(durations)

    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-f", "lavfi", "-t", f"{total}", "-i", "anullsrc=r=44100:cl=stereo",
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart",
        str(out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for frame_path, seconds in zip(frames, durations):
            base = Image.open(frame_path).convert("RGB")
            for img in _zoom_frames(base, int(seconds * FPS)):
                proc.stdin.write(img.tobytes())
    finally:
        proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg 영상 인코딩 실패")
    log.info("릴스 영상 생성: %s (%.1f초)", out, total)
    return out
