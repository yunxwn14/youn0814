"""카드에 넣을 무료 사진 검색·다운로드.

기사 사진은 언론사 저작권이 있어 쓰지 않고, 상업적 이용이 가능한 무료 사진만 쓴다.
- PEXELS_API_KEY 가 있으면 Pexels (출처 표기 의무 없음, 품질 좋음)
- 없으면 Openverse (키 불필요, CC0/CC BY/CC BY-SA — 출처 표기 필요)
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

import requests
from PIL import Image

log = logging.getLogger(__name__)

USER_AGENT = "viralgram/1.0 (instagram card news bot)"
MIN_SIDE = 700


@dataclass
class Photo:
    image: Image.Image
    credit: str  # 캡션에 넣을 출처 표기


def _search_pexels(query: str, api_key: str) -> list[tuple[str, str]]:
    resp = requests.get(
        "https://api.pexels.com/v1/search",
        headers={"Authorization": api_key},
        params={"query": query, "per_page": 5, "orientation": "portrait"},
        timeout=20,
    )
    resp.raise_for_status()
    return [(p["src"]["large2x"], f"{p['photographer']} / Pexels") for p in resp.json().get("photos", [])]


def _search_openverse(query: str) -> list[tuple[str, str]]:
    resp = requests.get(
        "https://api.openverse.org/v1/images/",
        headers={"User-Agent": USER_AGENT},
        params={"q": query, "license_type": "commercial", "page_size": 8, "mature": "false"},
        timeout=20,
    )
    resp.raise_for_status()
    results = []
    for r in resp.json().get("results", []):
        w, h = r.get("width"), r.get("height")
        if w and h and min(w, h) < MIN_SIDE:  # 크기 정보가 없으면 받아본 뒤 판단
            continue
        license_ = f"CC {r.get('license', '').upper()}".replace("CC CC0", "CC0")
        results.append((r["url"], f"{r.get('creator') or 'Unknown'} ({license_}) / Openverse"))
    return results


def _download(url: str) -> Image.Image | None:
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    except (requests.RequestException, OSError) as exc:
        log.warning("사진 다운로드 실패 (%s): %s", url, exc)
        return None
    if min(img.size) < MIN_SIDE:
        log.info("사진이 너무 작아 제외 (%s, %s)", url, img.size)
        return None
    return img


def find_photos(queries: list[str], pexels_key: str = "", limit: int = 3) -> list[Photo]:
    """검색어마다 한 장씩, 중복 없이 최대 limit 장. 실패해도 예외 없이 빈 목록을 반환한다."""
    photos: list[Photo] = []
    used: set[str] = set()
    for query in queries:
        if len(photos) >= limit:
            break
        try:
            candidates = _search_pexels(query, pexels_key) if pexels_key else _search_openverse(query)
        except requests.RequestException as exc:
            log.warning("사진 검색 실패 (%s): %s", query, exc)
            continue
        log.info("사진 검색 '%s': 후보 %d개", query, len(candidates))
        for url, credit in candidates:
            if url in used:
                continue
            img = _download(url)
            if img:
                used.add(url)
                photos.append(Photo(img, credit))
                break
    log.info("사진 %d장 확보", len(photos))
    return photos
