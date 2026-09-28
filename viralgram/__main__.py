"""실행: python -m viralgram [--dry-run]"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from .cards import Renderer
from .config import Settings
from .history import History
from .hosting import upload_all
from .instagram import Instagram
from .photos import find_photos
from .sources import fetch_candidates
from .writer import Writer, WriterRefusal, build_caption

log = logging.getLogger("viralgram")


def run(dry_run: bool) -> int:
    s = Settings.from_env()
    history = History(s.history_path)

    stories = fetch_candidates(exclude_ids=history.ids)
    if not stories:
        log.error("새 후보가 없습니다.")
        return 1

    writer = Writer(s.claude_model, web_research=s.web_research)
    ranked = writer.rank(stories[:60], history.recent_titles())

    for story in ranked:
        log.info("작성 중: [%s] %s (%s)", story.region, story.title, story.source)
        try:
            card = writer.write(story, writer.research(story))
        except WriterRefusal as exc:
            log.warning("건너뜀 (%s)", exc)
            continue
        photos = find_photos(card.photo_queries, s.pexels_api_key)
        if not any(photos):
            log.warning("건너뜀 (이야기에 맞는 사진을 못 찾음: %s)", card.photo_queries)
            continue
        break
    else:
        log.error("게시할 수 있는 이야기를 만들지 못했습니다.")
        return 1

    folder = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = s.output_dir / folder
    ig = Instagram(s.ig_user_id, s.ig_access_token, s.ig_graph_host, s.ig_graph_version) if s.ig_access_token else None
    brand = s.brand_handle or (ig.username if ig else "")
    images = Renderer(s.font_path, brand).render(card, out_dir, photos)
    caption = build_caption(card, [p.credit for p in photos if p])
    (out_dir / "caption.txt").write_text(caption, encoding="utf-8")

    if dry_run:
        print(f"\n[dry-run] 이미지와 캡션을 {out_dir} 에 저장했습니다. 게시하지 않았습니다.\n")
        print(caption)
        return 0

    if ig is None:
        log.error("IG_ACCESS_TOKEN 이 없어 게시할 수 없습니다.")
        return 1
    urls = upload_all(images, folder, s)
    media_id = ig.publish(urls, caption)

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
