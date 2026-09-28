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
# Flickr 등 원본 호스트는 봇 UA 를 403 으로 막아서, 다운로드는 브라우저 UA 로 한다.
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
MIN_SIDE = 700


@dataclass
class Photo:
    image: Image.Image
    credit: str  # 캡션에 넣을 출처 표기


def _search_pexels(query: str, api_key: str) -> list[tuple[list[str], str]]:
    resp = requests.get(
        "https://api.pexels.com/v1/search",
        headers={"Authorization": api_key},
        params={"query": query, "per_page": 5, "orientation": "portrait"},
        timeout=20,
    )
    resp.raise_for_status()
    return [([p["src"]["large2x"]], f"{p['photographer']} / Pexels") for p in resp.json().get("photos", [])]


def _search_openverse(query: str) -> list[tuple[list[str], str]]:
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
        # Openverse 가 대신 전달해 주는 원본 크기 이미지를 먼저, 실패하면 원본 주소로
        urls = [f"{r['thumbnail']}?full_size=true"] if r.get("thumbnail") else []
        results.append((urls + [r["url"]], f"{r.get('creator') or 'Unknown'} ({license_}) / Openverse"))
    return results


def _download(urls: list[str]) -> Image.Image | None:
    for url in urls:
        img = _download_one(url)
        if img:
            return img
    return None


def _download_one(url: str) -> Image.Image | None:
    try:
        resp = requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=30)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    except (requests.RequestException, OSError) as exc:
        log.warning("사진 다운로드 실패 (%s): %s", url, exc)
        return None
    if min(img.size) < MIN_SIDE:
        log.info("사진이 너무 작아 제외 (%s, %s)", url, img.size)
        return None
    return img


def _search(query: str, pexels_key: str) -> list[tuple[list[str], str]]:
    """결과가 없으면 뒤에서부터 단어를 줄여가며 다시 검색 ('empty fashion runway' → 'empty fashion' → 'empty')."""
    words = query.split()
    for n in range(len(words), 0, -1):
        q = " ".join(words[:n]) if n < len(words) else query
        try:
            candidates = _search_pexels(q, pexels_key) if pexels_key else _search_openverse(q)
        except requests.RequestException as exc:
            log.warning("사진 검색 실패 (%s): %s", q, exc)
            return []
        log.info("사진 검색 '%s': 후보 %d개", q, len(candidates))
        if candidates:
            return candidates
    return []


FALLBACK_QUERIES = ["city", "people", "street", "sky"]


def find_photos(queries: list[str], pexels_key: str = "") -> list[Photo | None]:
    """검색어(=페이지)마다 한 장씩, 같은 사진은 중복 없이. 못 찾은 자리는 None.
    하나도 못 찾으면 일반적인 검색어로 한 장이라도 확보한다. 예외는 던지지 않는다."""
    used: set[str] = set()

    def pick(query: str) -> Photo | None:
        for urls, credit in _search(query, pexels_key):
            if urls[-1] in used:
                continue
            img = _download(urls)
            if img:
                used.add(urls[-1])
                return Photo(img, credit)
        return None

    photos = [pick(q) for q in queries]
    if not any(photos):
        for q in FALLBACK_QUERIES:
            if (p := pick(q)) is not None:
                photos = [p]
                break
    log.info("사진 %d장 확보 (페이지 %d개)", sum(1 for p in photos if p), len(queries))
    return photos
