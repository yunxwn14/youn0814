"""Instagram Graph API 로 캐러셀 게시물 발행."""

from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)


class InstagramError(Exception):
    pass


class Instagram:
    def __init__(self, user_id: str, token: str, host: str = "", version: str = "v23.0"):
        if not token:
            raise InstagramError("IG_ACCESS_TOKEN 이 설정되지 않았습니다.")
        self.token = token
        self.base = f"https://{host or self.host_for(token)}/{version}"
        self.user_id = user_id or self._lookup_user_id()

    @staticmethod
    def host_for(token: str) -> str:
        """'IG'로 시작하는 토큰은 인스타그램 로그인 방식, 그 외(EAA...)는 페이스북 로그인 방식."""
        return "graph.instagram.com" if token.startswith("IG") else "graph.facebook.com"

    def _lookup_user_id(self) -> str:
        if "graph.instagram.com" not in self.base:
            raise InstagramError("페이스북 로그인 토큰은 IG_USER_ID 를 직접 지정해야 합니다.")
        me = self._call("GET", "me", fields="user_id,username")
        log.info("인스타 계정: @%s (id=%s)", me.get("username"), me["user_id"])
        return me["user_id"]

    def _call(self, method: str, path: str, **params) -> dict:
        params["access_token"] = self.token
        resp = requests.request(method, f"{self.base}/{path}", data=params if method == "POST" else None,
                                params=params if method == "GET" else None, timeout=60)
        data = resp.json()
        if resp.status_code >= 400 or "error" in data:
            raise InstagramError(f"{path}: {data.get('error', data)}")
        return data

    def _wait_ready(self, container_id: str, timeout: int = 300) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self._call("GET", container_id, fields="status_code,status").get("status_code")
            if status == "FINISHED":
                return
            if status in {"ERROR", "EXPIRED"}:
                raise InstagramError(f"컨테이너 {container_id} 처리 실패: {status}")
            time.sleep(5)
        raise InstagramError(f"컨테이너 {container_id} 처리 시간 초과")

    def publish_carousel(self, image_urls: list[str], caption: str) -> str:
        if not 2 <= len(image_urls) <= 10:
            raise InstagramError("캐러셀은 이미지 2~10장이어야 합니다.")
        children = []
        for url in image_urls:
            child = self._call("POST", f"{self.user_id}/media", image_url=url, is_carousel_item="true")
            children.append(child["id"])
        for child in children:
            self._wait_ready(child)
        container = self._call(
            "POST", f"{self.user_id}/media",
            media_type="CAROUSEL", children=",".join(children), caption=caption,
        )
        self._wait_ready(container["id"])
        media = self._call("POST", f"{self.user_id}/media_publish", creation_id=container["id"])
        log.info("게시 완료: media_id=%s", media["id"])
        return media["id"]
