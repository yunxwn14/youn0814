"""실행: python -m viralgram [--dry-run]"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from .cards import Renderer
from .config import Settings, resolve_mode
from .history import History
from .hosting import upload_all, upload_catbox, upload_github
from .instagram import Instagram, InstagramError
from .reels import make_reel, pick_music
from .photos import fetch_article_image, resolve
from .sources import feeds_for, fetch_candidates
from .writer import Writer, WriterRefusal, build_caption

log = logging.getLogger("viralgram")


def gather_images(card, s: Settings, source_urls: list[str], cover, used: set[str]):
    """썸네일은 항상 기사 사진(cover). 비교 레이아웃의 두 번째 이미지(b)와 둘째 장(extra)을 확보한다."""
    source_name = card.source_credit.replace("출처:", "").strip() or "원문 기사"
    article_urls = list(dict.fromkeys([card.article_url, *source_urls]))
    opts = dict(article_url=article_urls, article_credit=source_name, pexels_key=s.pexels_api_key,
                openai_key=s.openai_api_key, image_model=s.image_model, used=used)
    b = resolve(card.image_b, **opts) if card.image_b and card.layout != "single" else None
    if card.image_b and card.layout != "single" and b is None:
        log.info("두 번째 이미지를 못 구해 single 레이아웃으로 대체")
    # 둘째 장: 같은 사건을 다룬 다른 기사의 사진만 쓴다. 없으면 억지로 채우지 않고 1장으로 게시.
    extra = fetch_article_image(article_urls, source_name, used)
    log.info("이미지: layout=%s a=%s b=%s extra=%s", card.layout,
             cover.credit, b and b.credit, extra and extra.credit)
    return cover, b, extra


def post_reel(ig: Instagram, images, cover_url: str, folder: str, caption: str, s: Settings) -> None:
    """같은 이미지로 슬라이드쇼 영상을 만들어 릴스로 올린다. 실패해도 사진 게시물은 이미 올라간 상태."""
    try:
        video = make_reel(images, images[0].parent / "reel.mp4", pick_music())
        candidates = []
        if s.image_host == "github" and s.github_token:
            candidates.append(lambda: upload_github(video, f"posts/{folder}/reel.mp4", s))
        candidates.append(lambda: upload_catbox(video))
        for get_url in candidates:
            try:
                ig.publish_reel(get_url(), caption, cover_url=cover_url)
                return
            except (InstagramError, RuntimeError, OSError) as exc:
                log.warning("릴스 업로드 실패, 다른 호스팅으로 재시도: %s", exc)
        log.error("릴스 게시 실패 (사진 게시물은 정상 게시됨)")
    except Exception as exc:  # 릴스는 부가 기능이라 전체 실행을 멈추지 않는다
        log.error("릴스 생성 실패 (사진 게시물은 정상 게시됨): %s", exc)


def run(dry_run: bool) -> int:
    s = Settings.from_env()
    history = History(s.history_path)

    mode = resolve_mode(s.post_mode)
    log.info("게시 모드: %s", "웃긴 이야기" if mode == "funny" else "이슈")
    stories = fetch_candidates(feeds_for(mode), exclude_ids=history.ids)
    if not stories:
        log.error("새 후보가 없습니다.")
        return 1

    writer = Writer(s.claude_model, web_research=s.web_research, rank_model=s.rank_model)
    ranked = writer.rank(stories[:100], history.recent_titles(), mode)

    for story in ranked:
        log.info("작성 중: [%s] %s (%s)", story.region, story.title, story.source)
        try:
            notes = writer.research(story)
        except WriterRefusal as exc:
            log.warning("건너뜀 (%s)", exc)
            continue
        # 기사 사진이 구해지는 이야기만 쓴다 (원고 쓰기 전에 확인해 비용 절약)
        used: set[str] = set()
        cover = fetch_article_image(writer.source_urls, story.source or "원문 기사", used)
        if cover is None:
            log.warning("건너뜀 (기사 사진을 구하지 못함): %s", story.title)
            continue
        try:
            card = writer.write(story, notes)
        except WriterRefusal as exc:
            log.warning("건너뜀 (%s)", exc)
            continue
        a, b, extra = gather_images(card, s, writer.source_urls, cover, used)
        break
    else:
        log.error("게시할 수 있는 이야기를 만들지 못했습니다.")
        return 1

    folder = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = s.output_dir / folder
    ig = Instagram(s.ig_user_id, s.ig_access_token, s.ig_graph_host, s.ig_graph_version) if s.ig_access_token else None
    brand = s.brand_handle or (ig.username if ig else "")
    images = Renderer(s.font_path, brand).render(card, out_dir, a, b, [extra])
    used = [p for p in (a, b, extra) if p]
    caption = build_caption(card, [p.credit for p in used], s.caption_signoff)
    (out_dir / "caption.txt").write_text(caption, encoding="utf-8")

    if dry_run:
        print(f"\n[dry-run] 이미지와 캡션을 {out_dir} 에 저장했습니다. 게시하지 않았습니다.\n")
        if s.image_host == "github" and s.github_token:
            # 미리보기도 링크로 볼 수 있게 images 브랜치의 previews/ 에 올린다
            for url in upload_all(images, folder, s, prefix="previews"):
                print(f"미리보기: {url}")
            if s.post_reels:
                video = make_reel(images, images[0].parent / "reel.mp4", pick_music())
                print(f"미리보기 릴스: {upload_github(video, f'previews/{folder}/reel.mp4', s)}")
        print(caption)
        return 0

    if ig is None:
        log.error("IG_ACCESS_TOKEN 이 없어 게시할 수 없습니다.")
        return 1
    urls = upload_all(images, folder, s)
    media_id = ig.publish(urls, caption)
    if s.post_reels:
        post_reel(ig, images, urls[0], folder, caption, s)

    history.add(story.id, story.title, story.link, media_id)
    history.save()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="국내/해외 화제 이야기를 인스타그램에 자동 게시")
    parser.add_argument("--dry-run", action="store_true", help="이미지·캡션만 만들고 게시하지 않음")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sys.exit(run(args.dry_run))


if __name__ == "__main__":
    main()
