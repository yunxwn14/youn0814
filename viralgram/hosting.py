"""Instagram Graph API 는 공개 URL 의 이미지만 받으므로, 이미지를 외부에 올려 URL 을 얻는다."""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import requests

from .config import Settings

log = logging.getLogger(__name__)


def upload_imgbb(path: Path, api_key: str) -> str:
    resp = requests.post(
        "https://api.imgbb.com/1/upload",
        data={"key": api_key, "image": base64.b64encode(path.read_bytes()).decode()},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["data"]["url"]


def upload_github(path: Path, remote_path: str, s: Settings) -> str:
    """공개 저장소의 별도 브랜치에 이미지를 커밋하고 raw URL 을 반환."""
    api = f"https://api.github.com/repos/{s.github_repository}"
    headers = {"Authorization": f"Bearer {s.github_token}", "Accept": "application/vnd.github+json"}
    _ensure_branch(api, headers, s.github_image_branch)
    resp = requests.put(
        f"{api}/contents/{remote_path}",
        headers=headers,
        json={
            "message": f"image: {remote_path}",
            "content": base64.b64encode(path.read_bytes()).decode(),
            "branch": s.github_image_branch,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return f"https://raw.githubusercontent.com/{s.github_repository}/{s.github_image_branch}/{remote_path}"


def _ensure_branch(api: str, headers: dict, branch: str) -> None:
    if requests.get(f"{api}/branches/{branch}", headers=headers, timeout=30).status_code == 200:
        return
    repo = requests.get(api, headers=headers, timeout=30)
    repo.raise_for_status()
    default = repo.json()["default_branch"]
    ref = requests.get(f"{api}/git/ref/heads/{default}", headers=headers, timeout=30)
    ref.raise_for_status()
    requests.post(
        f"{api}/git/refs",
        headers=headers,
        json={"ref": f"refs/heads/{branch}", "sha": ref.json()["object"]["sha"]},
        timeout=30,
    ).raise_for_status()


def upload_all(paths: list[Path], folder: str, s: Settings, prefix: str = "posts") -> list[str]:
    urls = []
    for path in paths:
        if s.image_host == "imgbb":
            url = upload_imgbb(path, s.imgbb_api_key)
        elif s.image_host == "github":
            url = upload_github(path, f"{prefix}/{folder}/{path.name}", s)
        else:
            raise ValueError(f"알 수 없는 IMAGE_HOST: {s.image_host}")
        log.info("업로드: %s", url)
        urls.append(url)
    return urls
