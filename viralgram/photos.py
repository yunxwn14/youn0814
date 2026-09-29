"""썸네일에 넣을 이미지 확보.

이미지마다 출처를 고른다 (Claude 가 이야기에 맞춰 지정):
- article: 원문 기사의 대표 이미지(og:image). 실제 인물·SNS 캡처·현장 사진용
- ai: 이미지 생성. OPENAI_API_KEY 가 있으면 OpenAI, 없으면 무료 Pollinations(키 불필요). 무료 사진으로 표현 못 하는 장면용
- stock: 무료 사진. PEXELS_API_KEY 가 있으면 Pexels, 없으면 Openverse
article·ai 가 실패하면 stock 으로 대체한다.
"""

from __future__ import annotations

import base64
import html
import io
import logging
import re
from dataclasses import dataclass
import random
from urllib.parse import quote, urljoin

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
    ai: bool = False  # AI 생성 이미지면 썸네일에 표시한다


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
        # 글씨를 얹는 것도 변형이므로 상업적 이용 + 수정 허용(ND 제외) 라이선스만
        params={"q": query, "license_type": "commercial,modification", "page_size": 8, "mature": "false"},
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


def _download_one(url: str, min_side: int = MIN_SIDE) -> Image.Image | None:
    try:
        resp = requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=120 if "pollinations" in url else 30)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    except (requests.RequestException, OSError) as exc:
        log.warning("사진 다운로드 실패 (%s): %s", url, exc)
        return None
    if min(img.size) < min_side:
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


def find_photos(queries: list[str], pexels_key: str = "") -> list[Photo | None]:
    """검색어마다 무료 사진 한 장씩, 같은 사진은 중복 없이. 못 찾은 자리는 None. 예외는 던지지 않는다."""
    used: set[str] = set()
    photos = [_pick_stock(q, pexels_key, used) for q in queries if q.strip()]
    log.info("사진 %d장 확보 (검색어 %d개)", sum(1 for p in photos if p), len(queries))
    return photos


_OG_IMAGE = re.compile(
    r"""<meta[^>]+(?:property|name)=["'](?:og:image|twitter:image)(?::src)?["'][^>]*content=["']([^"']+)["']"""
    r"""|<meta[^>]+content=["']([^"']+)["'][^>]*(?:property|name)=["'](?:og:image|twitter:image)["']""",
    re.I,
)


def fetch_article_image(article_url: str, credit: str) -> Photo | None:
    """원문 기사 페이지의 대표 이미지(og:image)를 가져온다."""
    if not article_url.startswith("http"):
        return None
    try:
        resp = requests.get(article_url, headers={"User-Agent": BROWSER_UA}, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("기사 페이지 접속 실패 (%s): %s", article_url, exc)
        return None
    m = _OG_IMAGE.search(resp.text)
    if not m:
        log.info("기사 대표 이미지 없음: %s", article_url)
        return None
    img_url = urljoin(resp.url, html.unescape(m.group(1) or m.group(2)))
    img = _download_one(img_url, min_side=400)
    return Photo(img, credit) if img else None


def generate_ai_image(prompt: str, api_key: str, model: str = "gpt-image-1") -> Photo | None:
    """세로형 이미지를 생성한다. OpenAI 키가 있으면 OpenAI, 없거나 실패하면 무료 Pollinations."""
    if not prompt.strip():
        return None
    if api_key:
        photo = _generate_openai(prompt, api_key, model)
        if photo:
            return photo
    return _generate_pollinations(prompt)


def _generate_pollinations(prompt: str) -> Photo | None:
    """pollinations.ai 무료 이미지 생성 (가입·키 불필요, 느리거나 실패할 수 있음)."""
    url = (f"https://image.pollinations.ai/prompt/{quote(prompt)}"
           f"?width=1024&height=1344&nologo=true&model=flux&seed={random.randint(1, 10**6)}")
    img = _download_one(url, min_side=700) if prompt else None
    if img is None:
        return None
    log.info("AI 이미지 생성 (Pollinations): %s", prompt[:80])
    return Photo(img, "AI 생성 이미지", ai=True)


def _generate_openai(prompt: str, api_key: str, model: str) -> Photo | None:
    try:
        resp = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "prompt": prompt, "size": "1024x1536", "n": 1},
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()["data"][0]
        raw = base64.b64decode(data["b64_json"]) if data.get("b64_json") else requests.get(data["url"], timeout=60).content
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except (requests.RequestException, KeyError, IndexError, ValueError, OSError) as exc:
        log.warning("AI 이미지 생성 실패: %s", exc)
        return None
    log.info("AI 이미지 생성 (OpenAI): %s", prompt[:80])
    return Photo(img, "AI 생성 이미지", ai=True)


def resolve(spec, *, article_url: str, article_credit: str, pexels_key: str,
            openai_key: str, image_model: str, used: set[str]) -> Photo | None:
    """ImageSpec 하나를 실제 이미지로. article/ai 가 안 되면 stock 으로 대체."""
    photo = None
    if spec.source == "article":
        photo = fetch_article_image(article_url, article_credit)
    elif spec.source == "ai":
        photo = generate_ai_image(spec.ai_prompt, openai_key, image_model)
    if photo is None:
        if spec.source != "stock":
            log.info("%s 이미지 실패 → 무료 사진으로 대체 (%s)", spec.source, spec.stock_query)
        photo = _pick_stock(spec.stock_query, pexels_key, used)
    return photo


def _pick_stock(query: str, pexels_key: str, used: set[str]) -> Photo | None:
    if not query.strip():
        return None
    for urls, credit in _search(query, pexels_key):
        if urls[-1] in used:
            continue
        img = _download(urls)
        if img:
            used.add(urls[-1])
            return Photo(img, credit)
    return None
