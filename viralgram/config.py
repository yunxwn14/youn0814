"""환경 변수 기반 설정."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    """의존성 없이 .env 파일을 읽어 os.environ 에 채운다 (이미 설정된 값은 유지)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    claude_model: str = "claude-opus-5"
    web_research: bool = True

    ig_user_id: str = ""
    ig_access_token: str = ""
    ig_graph_host: str = ""  # 비우면 토큰 종류로 자동 결정
    ig_graph_version: str = "v23.0"

    image_host: str = "imgbb"
    imgbb_api_key: str = ""
    github_token: str = ""
    github_repository: str = ""
    github_image_branch: str = "images"

    pexels_api_key: str = ""
    openai_api_key: str = ""  # AI 이미지 생성용 (없으면 AI 이미지 대신 무료 사진)
    image_model: str = "gpt-image-1"

    font_path: str = ""
    brand_handle: str = ""
    caption_signoff: str = "탐정냥의 사건 보고 끝 🐾"

    history_path: Path = Path("data/posted.json")
    output_dir: Path = Path("output")

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        env = os.environ.get
        return cls(
            claude_model=env("CLAUDE_MODEL") or "claude-opus-5",
            web_research=_bool("WEB_RESEARCH", True),
            ig_user_id=env("IG_USER_ID", ""),
            ig_access_token=env("IG_ACCESS_TOKEN", ""),
            ig_graph_host=env("IG_GRAPH_HOST", ""),
            ig_graph_version=env("IG_GRAPH_VERSION") or "v23.0",
            image_host=(env("IMAGE_HOST") or "imgbb").lower(),
            imgbb_api_key=env("IMGBB_API_KEY", ""),
            github_token=env("GITHUB_TOKEN", ""),
            github_repository=env("GITHUB_REPOSITORY", ""),
            github_image_branch=env("GITHUB_IMAGE_BRANCH") or "images",
            pexels_api_key=env("PEXELS_API_KEY", ""),
            openai_api_key=env("OPENAI_API_KEY", ""),
            image_model=env("IMAGE_MODEL") or "gpt-image-1",
            font_path=env("FONT_PATH", ""),
            brand_handle=env("BRAND_HANDLE", ""),
            caption_signoff=env("CAPTION_SIGNOFF") or "탐정냥의 사건 보고 끝 🐾",
            history_path=Path(env("HISTORY_PATH") or "data/posted.json"),
            output_dir=Path(env("OUTPUT_DIR") or "output"),
        )
