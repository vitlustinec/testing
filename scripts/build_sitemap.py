#!/usr/bin/env python3
"""Generate a detailed site map for mmhk.cz.

This script combines sitemap XML discovery with on-site crawling to build the
most complete map possible. It outputs both JSON and Markdown reports.
"""

from __future__ import annotations

import argparse
import collections
import html.parser
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

DEFAULT_START_URL = "https://www.mmhk.cz/"
DEFAULT_MAX_PAGES = 20000
DEFAULT_DELAY = 0.2
USER_AGENT = "mmhk-sitemap-mapper/1.0 (+https://www.mmhk.cz/)"


class LinkParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: set[str] = set()
        self.title: str | None = None
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            for key, value in attrs:
                if key.lower() == "href" and value:
                    self.links.add(value)
        elif tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            if self.title:
                self.title += data
            else:
                self.title = data


def normalize_url(url: str, base_url: str | None = None) -> str | None:
    if base_url:
        url = urllib.parse.urljoin(base_url, url)
    parsed = urllib.parse.urlsplit(url)
    if not parsed.scheme:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    normalized = urllib.parse.urlunsplit(
        (parsed.scheme, netloc, path, parsed.query, "")
    )
    return normalized


def is_mmhk(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    return parsed.netloc.endswith("mmhk.cz")


def fetch_url(url: str) -> tuple[int | None, str | None, bytes | None]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            status = getattr(resp, "status", None)
            content_type = resp.headers.get("Content-Type")
            return status, content_type, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type"), exc.read()
    except Exception:
        return None, None, None


def parse_sitemap_xml(xml_bytes: bytes) -> list[str]:
    urls: list[str] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return urls

    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    if root.tag.endswith("sitemapindex"):
        for sitemap in root.findall(f"{ns}sitemap"):
            loc = sitemap.find(f"{ns}loc")
            if loc is not None and loc.text:
                urls.append(loc.text.strip())
    elif root.tag.endswith("urlset"):
        for url in root.findall(f"{ns}url"):
            loc = url.find(f"{ns}loc")
            if loc is not None and loc.text:
                urls.append(loc.text.strip())
    return urls


def discover_sitemaps(start_url: str) -> list[str]:
    parsed = urllib.parse.urlsplit(start_url)
    robots_url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, "/robots.txt", "", "")
    )
    sitemap_urls: list[str] = []
    status, _, body = fetch_url(robots_url)
    if status and body:
        for line in body.decode("utf-8", errors="ignore").splitlines():
            if line.lower().startswith("sitemap:"):
                sitemap_urls.append(line.split(":", 1)[1].strip())
    if not sitemap_urls:
        sitemap_urls.append(urllib.parse.urljoin(start_url, "/sitemap.xml"))
    return sitemap_urls


def collect_sitemap_urls(sitemap_urls: list[str]) -> set[str]:
    collected: set[str] = set()
    queue = collections.deque(sitemap_urls)
    seen = set()
    while queue:
        sitemap = queue.popleft()
        if sitemap in seen:
            continue
        seen.add(sitemap)
        status, content_type, body = fetch_url(sitemap)
        if not body:
            logging.debug("No sitemap body for %s (status=%s)", sitemap, status)
            continue
        if content_type and "xml" not in content_type:
            logging.debug("Skipping non-xml sitemap %s", sitemap)
            continue
        urls = parse_sitemap_xml(body)
        if not urls:
            continue
        if any(url.endswith(".xml") for url in urls):
            for url in urls:
                if url.endswith(".xml"):
                    queue.append(url)
                else:
                    collected.add(url)
        else:
            collected.update(urls)
    return collected


def crawl_site(
    start_urls: set[str],
    max_pages: int,
    delay: float,
    on_progress: collections.abc.Callable[[dict], None] | None = None,
) -> tuple[dict[str, dict], dict[str, set[str]]]:
    pages: dict[str, dict] = {}
    edges: dict[str, set[str]] = collections.defaultdict(set)
    queue = collections.deque(start_urls)
    seen: set[str] = set()

    while queue and len(seen) < max_pages:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)

        status, content_type, body = fetch_url(current)
        page_info = {
            "status": status,
            "content_type": content_type,
            "title": None,
            "discovered": [],
        }
        if body and content_type and "text/html" in content_type:
            parser = LinkParser()
            parser.feed(body.decode("utf-8", errors="ignore"))
            if parser.title:
                page_info["title"] = parser.title.strip()
            for link in parser.links:
                normalized = normalize_url(link, current)
                if not normalized or not is_mmhk(normalized):
                    continue
                edges[current].add(normalized)
                if normalized not in seen:
                    queue.append(normalized)
        pages[current] = page_info
        if on_progress:
            on_progress(
                {
                    "type": "page",
                    "url": current,
                    "count": len(seen),
                    "status": status,
                }
            )
        if delay:
            time.sleep(delay)

    return pages, edges


def run_crawl(
    start_url: str,
    max_pages: int,
    delay: float,
    output_dir: str,
    on_progress: collections.abc.Callable[[dict], None] | None = None,
) -> dict[str, dict]:
    if on_progress:
        on_progress({"type": "status", "message": "Hledám sitemap..."})
    sitemap_roots = discover_sitemaps(start_url)
    sitemap_urls = collect_sitemap_urls(sitemap_roots)
    if on_progress:
        on_progress(
            {
                "type": "status",
                "message": f"Nalezeno URL v sitemap: {len(sitemap_urls)}",
            }
        )

    start_urls = {start_url} | {normalize_url(url) for url in sitemap_urls if url}
    start_urls = {url for url in start_urls if url and is_mmhk(url)}

    if on_progress:
        on_progress(
            {
                "type": "status",
                "message": f"Spouštím crawler pro {len(start_urls)} URL.",
            }
        )
    pages, edges = crawl_site(start_urls, max_pages, delay, on_progress)
    if on_progress:
        on_progress(
            {
                "type": "status",
                "message": f"Zpracováno stránek: {len(pages)}",
            }
        )

    write_reports(output_dir, pages, edges, sitemap_urls)
    if on_progress:
        on_progress(
            {
                "type": "status",
                "message": f"Výstupy zapsány do {output_dir}",
            }
        )
    return pages


def build_tree(urls: list[str]) -> dict:
    tree: dict[str, dict] = {}
    for url in sorted(urls):
        parsed = urllib.parse.urlsplit(url)
        host = parsed.netloc
        path = parsed.path or "/"
        parts = [host] + [p for p in path.split("/") if p]
        if parsed.query:
            parts[-1] = f"{parts[-1]}?{parsed.query}"
        node = tree
        for part in parts:
            node = node.setdefault(part, {})
    return tree


def render_tree(node: dict, indent: int = 0) -> list[str]:
    lines: list[str] = []
    for key, child in node.items():
        lines.append("  " * indent + f"- {key}")
        if child:
            lines.extend(render_tree(child, indent + 1))
    return lines


def write_reports(
    output_dir: str,
    pages: dict[str, dict],
    edges: dict[str, set[str]],
    sitemap_urls: set[str],
) -> None:
    os.makedirs(output_dir, exist_ok=True)
    urls = sorted(pages.keys())
    tree = build_tree(urls)

    json_path = os.path.join(output_dir, "mmhk_sitemap.json")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "total_pages": len(pages),
                "sitemap_urls": sorted(sitemap_urls),
                "pages": pages,
                "edges": {key: sorted(values) for key, values in edges.items()},
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )

    md_path = os.path.join(output_dir, "mmhk_sitemap.md")
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write("# Mapa stránek mmhk.cz\n\n")
        handle.write(f"Celkem stránek: **{len(pages)}**\n\n")
        handle.write("## Zdroje sitemap\n\n")
        for url in sorted(sitemap_urls):
            handle.write(f"- {url}\n")
        handle.write("\n## Strom URL\n\n")
        for line in render_tree(tree):
            handle.write(f"{line}\n")
        handle.write("\n## Detailní seznam stránek\n\n")
        handle.write("| URL | Titulek | Status | Content-Type |\n")
        handle.write("| --- | --- | --- | --- |\n")
        for url in urls:
            info = pages[url]
            title = (info.get("title") or "").replace("|", "\\|")
            status = info.get("status")
            content_type = info.get("content_type")
            handle.write(
                f"| {url} | {title} | {status} | {content_type} |\n"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Vytvoř maximálně podrobnou mapu stránek webu mmhk.cz."
    )
    parser.add_argument(
        "--start-url",
        default=DEFAULT_START_URL,
        help="Počáteční URL pro procházení.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help="Maximální počet stránek ke zpracování.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_DELAY,
        help="Prodleva mezi požadavky (v sekundách).",
    )
    parser.add_argument(
        "--output",
        default="output",
        help="Výstupní složka.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    start_url = normalize_url(args.start_url)
    if not start_url:
        raise SystemExit("Neplatná start URL.")

    def log_progress(payload: dict) -> None:
        if payload.get("type") == "status":
            logging.info(payload.get("message"))

    run_crawl(
        start_url=start_url,
        max_pages=args.max_pages,
        delay=args.delay,
        output_dir=args.output,
        on_progress=log_progress,
    )


if __name__ == "__main__":
    main()
