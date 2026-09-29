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


def make_reel(pages: list[Path], out: Path) -> Path:
    """이미지들을 순서대로 이어 붙인 MP4 를 만든다 (무음 오디오 트랙 포함)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    frames = [vertical_frame(p, out.parent / f"reel_{i:02d}.png") for i, p in enumerate(pages)]
    durations = [FIRST_SECONDS] + [OTHER_SECONDS] * (len(frames) - 1)
    total = sum(durations)

    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error"]
    for frame in frames:
        cmd += ["-i", str(frame)]
    cmd += ["-f", "lavfi", "-t", f"{total}", "-i", "anullsrc=r=44100:cl=stereo"]

    filters, labels = [], []
    for i, seconds in enumerate(durations):
        n = int(seconds * FPS)
        # 살짝 크게 키운 뒤 가운데 기준으로 천천히 확대 (켄 번즈 효과)
        filters.append(
            f"[{i}:v]scale={int(W * 1.1)}:{int(H * 1.1)},"
            f"zoompan=z='min(zoom+0.0007,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={n}:s={W}x{H}:fps={FPS},setsar=1[v{i}]"
        )
        labels.append(f"[v{i}]")
    filters.append(f"{''.join(labels)}concat=n={len(frames)}:v=1:a=0,format=yuv420p[v]")

    cmd += [
        "-filter_complex", ";".join(filters),
        "-map", "[v]", "-map", f"{len(frames)}:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart",
        str(out),
    ]
    subprocess.run(cmd, check=True)
    log.info("릴스 영상 생성: %s (%.1f초)", out, total)
    return out
