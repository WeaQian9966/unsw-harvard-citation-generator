"""Generate UNSW Harvard-style references from BibTeX.

This script accepts BibTeX on stdin or from a file and prints copy-pasteable
output with:
- a full reference list entry
- parenthetical in-text citation
- narrative in-text citation

The formatter aims to cover the most common BibTeX entry types used in student
work: article, book, inproceedings/incollection, thesis, misc, and online-like
records with URL or access date metadata.
"""

from __future__ import annotations

import argparse
from datetime import date
from html import unescape
from html.parser import HTMLParser
import re
import sys
import ssl
from dataclasses import dataclass
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

try:
    import tkinter as tk
    from tkinter import font as tkfont
    from tkinter import filedialog, messagebox, ttk
except Exception:  # pragma: no cover - GUI is optional
    tk = None
    tkfont = None
    filedialog = None
    messagebox = None
    ttk = None


MONTH_NAMES = {
    "jan": "January",
    "feb": "February",
    "mar": "March",
    "apr": "April",
    "may": "May",
    "jun": "June",
    "jul": "July",
    "aug": "August",
    "sep": "September",
    "oct": "October",
    "nov": "November",
    "dec": "December",
}


@dataclass
class BibEntry:
    entry_type: str
    key: str
    fields: dict[str, str]


@dataclass
class WebPageMetadata:
    title: str
    author: str
    site_name: str
    published_date: str
    url: str


@dataclass
class ArxivPaperMetadata:
    title: str
    authors: list[str]
    published_date: str
    url: str
    arxiv_id: str
    arxiv_version: str
    primary_category: str


def clean_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def strip_outer_braces(value: str) -> str:
    value = value.strip()
    if len(value) >= 2:
        if (value.startswith("{") and value.endswith("}")) or (
            value.startswith('"') and value.endswith('"')
        ):
            return value[1:-1].strip()
    return value


def normalize_value(value: str) -> str:
    value = strip_outer_braces(value)
    value = value.replace("~", " ")
    value = re.sub(r"\s*\n\s*", " ", value)
    return clean_whitespace(value)


def bibtex_to_text(text: str) -> str:
    lines = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("%"):
            continue
        lines.append(raw_line)
    return "\n".join(lines)


def find_entries(text: str) -> list[str]:
    entries = []
    i = 0
    length = len(text)
    while i < length:
        if text[i] != "@":
            i += 1
            continue
        start = i
        i += 1
        while i < length and text[i].isalpha():
            i += 1
        while i < length and text[i].isspace():
            i += 1
        if i >= length or text[i] not in "{(":
            continue
        opener = text[i]
        closer = "}" if opener == "{" else ")"
        depth = 1
        i += 1
        while i < length and depth > 0:
            char = text[i]
            if char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
            elif char == '"':
                i += 1
                while i < length:
                    if text[i] == "\\":
                        i += 2
                        continue
                    if text[i] == '"':
                        break
                    i += 1
            i += 1
        entries.append(text[start:i])
    return entries


def split_top_level_commas(text: str) -> list[str]:
    parts = []
    current = []
    brace_depth = 0
    quote_depth = False
    i = 0
    while i < len(text):
        char = text[i]
        if char == '"' and brace_depth == 0:
            quote_depth = not quote_depth
            current.append(char)
        elif char == "{" and not quote_depth:
            brace_depth += 1
            current.append(char)
        elif char == "}" and not quote_depth and brace_depth > 0:
            brace_depth -= 1
            current.append(char)
        elif char == "," and not quote_depth and brace_depth == 0:
            part = clean_whitespace("".join(current))
            if part:
                parts.append(part)
            current = []
        else:
            current.append(char)
        i += 1
    tail = clean_whitespace("".join(current))
    if tail:
        parts.append(tail)
    return parts


def parse_bibtex_entry(entry_text: str) -> BibEntry:
    head_match = re.match(r"@\s*([A-Za-z]+)\s*[\{(]\s*", entry_text)
    if not head_match:
        raise ValueError(f"Invalid BibTeX entry: {entry_text[:40]}")
    entry_type = head_match.group(1).lower()
    body = entry_text[head_match.end() :].rstrip().rstrip("}").rstrip(")").strip()
    parts = split_top_level_commas(body)
    if not parts:
        raise ValueError(f"Missing key in BibTeX entry: {entry_text[:40]}")
    key = parts[0]
    fields = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        field, value = part.split("=", 1)
        field = field.strip().lower()
        fields[field] = normalize_value(value)
    return BibEntry(entry_type=entry_type, key=key, fields=fields)


def parse_bibtex(text: str) -> list[BibEntry]:
    entries = []
    cleaned = bibtex_to_text(text)
    for raw_entry in find_entries(cleaned):
        try:
            entries.append(parse_bibtex_entry(raw_entry))
        except ValueError:
            continue
    return entries


def split_name(name: str) -> tuple[str, str]:
    name = clean_whitespace(name.replace("{", "").replace("}", ""))
    if "," in name:
        last, first = [part.strip() for part in name.split(",", 1)]
        return last, first
    parts = name.split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[-1], " ".join(parts[:-1])


def initials_from_given(given: str) -> str:
    pieces = [piece for piece in re.split(r"\s+", given) if piece]
    initials = []
    for piece in pieces:
        if "." in piece and len(piece) <= 4:
            initials.append(piece if piece.endswith(".") else f"{piece}.")
        else:
            initials.append(f"{piece[0].upper()}.")
    return " ".join(initials)


def format_person_name(name: str) -> str:
    last, given = split_name(name)
    if not last:
        return clean_whitespace(name)
    initials = initials_from_given(given) if given else ""
    if initials:
        return f"{last}, {initials}"
    return last


def parse_authors(entry: BibEntry) -> list[str]:
    authors = entry.fields.get("author") or entry.fields.get("editor") or ""
    if not authors:
        return []
    splitter = re.split(r"\s+and\s+", authors, flags=re.IGNORECASE)
    return [format_person_name(author) for author in splitter if clean_whitespace(author)]


def intext_author_label(entry: BibEntry) -> str:
    authors = parse_authors(entry)
    if not authors:
        organization = entry.fields.get("organization") or entry.fields.get("institution") or entry.fields.get("publisher")
        return organization or entry.fields.get("title", "Untitled")
    surnames = [author.split(",", 1)[0].strip() for author in authors]
    if len(surnames) == 1:
        return surnames[0]
    if len(surnames) == 2:
        return f"{surnames[0]} and {surnames[1]}"
    return f"{surnames[0]} et al."


def citation_year(entry: BibEntry) -> str:
    year = entry.fields.get("year")
    if year:
        return year
    date = entry.fields.get("date")
    if date and re.match(r"\d{4}", date):
        return date[:4]
    return "n.d."


def title_case(value: str) -> str:
    value = clean_whitespace(value)
    return value[:1].upper() + value[1:] if value else value


def formatted_title(entry: BibEntry) -> str:
    title = entry.fields.get("title") or "Untitled"
    return title_case(title)


def italicize(value: str) -> str:
    return f"*{value}*"


def joined_authors_for_reference(entry: BibEntry) -> str:
    authors = parse_authors(entry)
    if not authors:
        organization = entry.fields.get("organization") or entry.fields.get("institution") or entry.fields.get("publisher")
        return organization or "Anonymous"
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f"{authors[0]} and {authors[1]}"
    return ", ".join(authors[:-1]) + f" and {authors[-1]}"


def reference_sort_key(entry: BibEntry) -> tuple[str, str, str]:
    authors = parse_authors(entry)
    if authors:
        first_author = authors[0]
        surname = first_author.split(",", 1)[0].strip()
    else:
        surname = (
            entry.fields.get("organization")
            or entry.fields.get("institution")
            or entry.fields.get("publisher")
            or entry.fields.get("title")
            or ""
        )
    return (clean_whitespace(surname).casefold(), citation_year(entry).casefold(), formatted_title(entry).casefold())


def format_pages(entry: BibEntry) -> str:
    pages = entry.fields.get("pages", "")
    if not pages:
        return ""
    pages = pages.replace("--", "-")
    return f", pp. {pages}"


def format_volume_issue(entry: BibEntry) -> str:
    volume = entry.fields.get("volume", "")
    number = entry.fields.get("number", "")
    bits = []
    if volume:
        bits.append(f"vol. {volume}")
    if number:
        bits.append(f"no. {number}")
    if bits:
        return ", " + ", ".join(bits)
    return ""


def format_access_info(entry: BibEntry) -> str:
    access_date = entry.fields.get("urldate") or entry.fields.get("accessed") or entry.fields.get("accessdate")
    url = entry.fields.get("url") or entry.fields.get("howpublished") or entry.fields.get("doi")
    parts = []
    if access_date:
        access_date = access_date.replace("/", "-")
        parts.append(f", accessed {access_date}")
    if url:
        parts.append(f", {url}")
    return "".join(parts)


def parse_arxiv_identifier(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    match = re.search(r"/abs/([0-9]{4}\.[0-9]{4,5})(v\d+)?$", parsed.path.rstrip("/"))
    if not match:
        return "", ""
    return match.group(1), match.group(2) or ""


class MetadataHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.title_chunks: list[str] = []
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attr_map = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "title":
            self.in_title = True
        if tag.lower() == "meta":
            key = attr_map.get("name") or attr_map.get("property") or attr_map.get("itemprop")
            content = attr_map.get("content", "")
            if key and content:
                self.meta[key.lower()] = clean_whitespace(unescape(content))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_chunks.append(data)


def make_reference_sortable(entry: BibEntry) -> BibEntry:
    return entry


def build_webpage_entry(metadata: WebPageMetadata) -> BibEntry:
    fields = {
        "title": metadata.title or metadata.site_name or metadata.url,
        "url": metadata.url,
        "accessed": date.today().strftime("%d %B %Y"),
    }
    if metadata.author:
        fields["author"] = metadata.author
    elif metadata.site_name:
        fields["organization"] = metadata.site_name
    else:
        fields["organization"] = urlparse(metadata.url).netloc or metadata.url
    if metadata.published_date:
        fields["year"] = metadata.published_date[:4]
    return BibEntry(entry_type="webpage", key=metadata.url, fields=fields)


def build_arxiv_entry(metadata: ArxivPaperMetadata) -> BibEntry:
    fields = {
        "title": metadata.title,
        "author": " and ".join(metadata.authors),
        "year": metadata.published_date[:4] if metadata.published_date else "",
        "url": metadata.url,
        "note": f"arXiv preprint arXiv:{metadata.arxiv_id}{metadata.arxiv_version}" if metadata.arxiv_id else "arXiv preprint",
    }
    if metadata.primary_category:
        fields["organization"] = f"arXiv ({metadata.primary_category})"
    else:
        fields["organization"] = "arXiv"
    if metadata.published_date:
        fields["accessed"] = date.today().strftime("%d %B %Y")
    return BibEntry(entry_type="arxiv", key=metadata.url, fields=fields)


def extract_metadata_from_html(html_text: str, url: str) -> WebPageMetadata:
    parser = MetadataHTMLParser()
    parser.feed(html_text)
    title = clean_whitespace(unescape(" ".join(parser.title_chunks)))
    meta = parser.meta
    title = title or meta.get("og:title") or meta.get("twitter:title") or meta.get("citation_title") or ""
    author = meta.get("author") or meta.get("article:author") or meta.get("citation_author") or ""
    site_name = meta.get("og:site_name") or meta.get("application-name") or urlparse(url).netloc
    published_date = (
        meta.get("article:published_time")
        or meta.get("citation_publication_date")
        or meta.get("date")
        or meta.get("dc.date")
        or ""
    )
    return WebPageMetadata(
        title=title,
        author=author,
        site_name=site_name,
        published_date=published_date,
        url=url,
    )


def fetch_webpage_metadata(url: str, timeout: int = 12) -> WebPageMetadata:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=timeout) as response:
        payload = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    metadata = extract_metadata_from_html(payload, url)
    if not metadata.title:
        metadata.title = urlparse(url).netloc or url
    return metadata


def extract_arxiv_metadata_from_api(xml_text: str, url: str, arxiv_id: str, arxiv_version: str) -> ArxivPaperMetadata:
    root = ET.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    entry = root.find("atom:entry", ns)
    if entry is None:
        raise ValueError("No arXiv entry found")

    title = clean_whitespace(unescape(entry.findtext("atom:title", default="", namespaces=ns) or ""))
    published_date = (entry.findtext("atom:published", default="", namespaces=ns) or "").strip()[:10]
    authors: list[str] = []
    for author_node in entry.findall("atom:author", ns):
        name = clean_whitespace(author_node.findtext("atom:name", default="", namespaces=ns) or "")
        if name:
            authors.append(name)

    category_node = entry.find("arxiv:primary_category", ns)
    primary_category = category_node.attrib.get("term", "") if category_node is not None else ""

    if not arxiv_version:
        entry_id = entry.findtext("atom:id", default="", namespaces=ns) or ""
        version_match = re.search(r"v(\d+)$", entry_id)
        arxiv_version = f"v{version_match.group(1)}" if version_match else ""

    return ArxivPaperMetadata(
        title=title or arxiv_id,
        authors=authors,
        published_date=published_date,
        url=url,
        arxiv_id=arxiv_id,
        arxiv_version=arxiv_version,
        primary_category=primary_category,
    )


def fetch_arxiv_metadata(url: str, timeout: int = 12) -> ArxivPaperMetadata:
    arxiv_id, arxiv_version = parse_arxiv_identifier(url)
    if not arxiv_id:
        raise ValueError("Not an arXiv abs URL")
    api_url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
    insecure_context = ssl._create_unverified_context()
    try:
        request = Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=timeout, context=insecure_context) as response:
            xml_text = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        return extract_arxiv_metadata_from_api(xml_text, url, arxiv_id, arxiv_version)
    except Exception:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=timeout, context=insecure_context) as response:
            html_text = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        html_meta = extract_metadata_from_html(html_text, url)
        authors_text = html_meta.author or ""
        authors = [part.strip() for part in re.split(r"\s+and\s+|,\s*", authors_text) if part.strip()]
        return ArxivPaperMetadata(
            title=html_meta.title or arxiv_id,
            authors=authors,
            published_date=html_meta.published_date or "",
            url=url,
            arxiv_id=arxiv_id,
            arxiv_version=arxiv_version,
            primary_category=html_meta.site_name or "",
        )


def parse_url_list(raw_text: str) -> list[str]:
    urls = []
    for line in raw_text.splitlines():
        line = line.strip().strip(",;")
        if not line:
            continue
        if line.startswith("<") and line.endswith(">"):
            line = line[1:-1].strip()
        if re.match(r"^https?://", line, flags=re.IGNORECASE):
            urls.append(line)
    return urls


def build_entries_from_urls(urls: Iterable[str]) -> list[BibEntry]:
    entries = []
    for url in urls:
        try:
            arxiv_id, _ = parse_arxiv_identifier(url)
            if arxiv_id:
                entries.append(build_arxiv_entry(fetch_arxiv_metadata(url)))
                continue
            metadata = fetch_webpage_metadata(url)
        except Exception:
            metadata = WebPageMetadata(
                title=urlparse(url).netloc or url,
                author="",
                site_name=urlparse(url).netloc or url,
                published_date="",
                url=url,
            )
        entries.append(build_webpage_entry(metadata))
    return entries


def format_reference(entry: BibEntry) -> str:
    authors = joined_authors_for_reference(entry)
    year = citation_year(entry)
    title = formatted_title(entry)
    entry_type = entry.entry_type

    if entry_type == "arxiv":
        note = entry.fields.get("note", "arXiv preprint")
        return f"{authors} {year}, {italicize(title)}, {note}{format_access_info(entry)}."

    if entry_type == "article":
        journal = entry.fields.get("journal", "")
        first_line = f"{authors} {year}, {italicize(title)},"
        second_line = f"    {italicize(journal)}{format_volume_issue(entry)}{format_pages(entry)}." if journal else f"    {format_volume_issue(entry).lstrip(', ')}{format_pages(entry)}."
        return f"{first_line}\n{second_line}"

    if entry_type in {"book", "mvbook"}:
        edition = entry.fields.get("edition", "")
        place = entry.fields.get("address") or entry.fields.get("location") or ""
        publisher = entry.fields.get("publisher", "")
        details = []
        if edition:
            details.append(f"{edition} edn")
        if place:
            details.append(place)
        if publisher:
            details.append(publisher)
        first_line = f"{authors} {year}, {italicize(title)},"
        second_line = f"    {', '.join(details)}." if details else "    ."
        return f"{first_line}\n{second_line}"

    if entry_type in {"inproceedings", "conference", "incollection"}:
        booktitle = entry.fields.get("booktitle") or entry.fields.get("title") or ""
        editor = entry.fields.get("editor", "")
        place = entry.fields.get("address") or entry.fields.get("location") or ""
        publisher = entry.fields.get("publisher", "")
        details = []
        if editor:
            details.append(f"edited by {editor}")
        if booktitle:
            details.append(italicize(booktitle))
        if place:
            details.append(place)
        if publisher:
            details.append(publisher)
        if pages := format_pages(entry):
            details.append(pages.lstrip(", "))
        first_line = f"{authors} {year}, {italicize(title)},"
        second_line = f"    {', '.join(details)}." if details else "    ."
        return f"{first_line}\n{second_line}"

    if entry_type in {"thesis", "phdthesis", "mastersthesis"}:
        school = entry.fields.get("school") or entry.fields.get("institution") or ""
        thesis_type = entry.fields.get("type", "thesis")
        first_line = f"{authors} {year}, {italicize(title)},"
        second_line = f"    {thesis_type}, {school}." if school else f"    {thesis_type}."
        return f"{first_line}\n{second_line}"

    if entry_type in {"misc", "online", "webpage"}:
        note = entry.fields.get("note", "")
        if not note:
            archive_prefix = (entry.fields.get("archiveprefix") or "").strip().lower()
            eprint = (entry.fields.get("eprint") or "").strip()
            if archive_prefix == "arxiv" and eprint:
                note = f"arXiv preprint arXiv:{eprint}"
        base = f"{authors} {year}, {italicize(title)}"
        if note:
            base += f", {note}"
        access_info = format_access_info(entry)
        if access_info:
            return f"{base},\n    {access_info.lstrip(', ')}."
        return f"{base}."

    organization = entry.fields.get("organization", "")
    publisher = entry.fields.get("publisher", "")
    container = organization or publisher
    first_line = f"{authors} {year}, {italicize(title)},"
    details = []
    if container:
        details.append(container)
    if pages := format_pages(entry):
        details.append(pages.lstrip(", "))
    if access_info := format_access_info(entry):
        details.append(access_info.lstrip(", "))
    second_line = f"    {', '.join(details)}." if details else "    ."
    return f"{first_line}\n{second_line}"


def format_parenthetical(entry: BibEntry, page: Optional[str] = None) -> str:
    author_label = intext_author_label(entry)
    year = citation_year(entry)
    if page:
        return f"({author_label}, {year}, p. {page})"
    return f"({author_label}, {year})"


def format_narrative(entry: BibEntry, page: Optional[str] = None) -> str:
    author_label = intext_author_label(entry)
    year = citation_year(entry)
    if page:
        return f"{author_label} ({year}, p. {page})"
    return f"{author_label} ({year})"


def render_entry(entry: BibEntry, page: Optional[str] = None) -> str:
    lines = [f"Key: {entry.key}", f"Reference: {format_reference(entry)}"]
    lines.append(f"In-text (parenthetical): {format_parenthetical(entry, page)}")
    lines.append(f"In-text (narrative): {format_narrative(entry, page)}")
    return "\n".join(lines)


def read_input(path: Optional[str]) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    return sys.stdin.read()


def build_output(entries: Iterable[BibEntry], page: Optional[str] = None) -> str:
    sections = build_sections(entries, page=page)
    return (
        "Reference list\n"
        f"{sections['reference']}\n\n"
        "In-text citations (parenthetical)\n"
        f"{sections['parenthetical']}\n\n"
        "In-text citations (narrative)\n"
        f"{sections['narrative']}"
    )


def build_rich_output(entries: Iterable[BibEntry], page: Optional[str] = None) -> dict[str, list[str]]:
    sections = build_sections(entries, page=page)
    return {
        "reference": ["Reference list", sections["reference"]],
        "parenthetical": ["In-text citations (parenthetical)", sections["parenthetical"]],
        "narrative": ["In-text citations (narrative)", sections["narrative"]],
    }


def build_sections(entries: Iterable[BibEntry], page: Optional[str] = None) -> dict[str, str]:
    entries = sorted(list(entries), key=reference_sort_key)
    reference_lines = [format_reference(entry) for entry in entries]
    parenthetical_lines = [format_parenthetical(entry, page) for entry in entries]
    narrative_lines = [format_narrative(entry, page) for entry in entries]
    return {
        "reference": "\n".join(reference_lines),
        "parenthetical": "\n".join(parenthetical_lines),
        "narrative": "\n".join(narrative_lines),
    }


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert BibTeX entries into UNSW Harvard-style references and in-text citations."
    )
    parser.add_argument(
        "input",
        nargs="?",
        help="Path to a .bib file. If omitted, BibTeX is read from stdin.",
    )
    parser.add_argument(
        "--page",
        help="Optional page number to include in the in-text citations.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Open a simple desktop interface instead of using the terminal.",
    )
    return parser.parse_args(argv)


def launch_gui() -> None:
    if tk is None:
        raise RuntimeError("Tkinter is not available in this Python installation.")

    def fill_text_widget(widget: Any, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def render_rich_text(widget: Any, text: str) -> None:
        widget.configure(state="normal")
        italic_on = False
        buffer = []

        def flush(tag: Optional[str] = None) -> None:
            if not buffer:
                return
            chunk = "".join(buffer)
            if tag:
                widget.insert(tk.END, chunk, tag)
            else:
                widget.insert(tk.END, chunk)
            buffer.clear()

        for char in text:
            if char == "*":
                flush("italic" if italic_on else None)
                italic_on = not italic_on
                continue
            buffer.append(char)
        flush("italic" if italic_on else None)
        widget.configure(state="disabled")

    def set_rich_text(widget: Any, text: str) -> None:
        fill_text_widget(widget, "")
        render_rich_text(widget, text)

    def populate_output(entries: list[BibEntry], page_value: Optional[str]) -> None:
        if not entries:
            fill_text_widget(reference_text, "No BibTeX entries found.")
            fill_text_widget(parenthetical_text, "No BibTeX entries found.")
            fill_text_widget(narrative_text, "No BibTeX entries found.")
            return
        rich_sections = build_rich_output(entries, page=page_value)
        set_rich_text(reference_text, rich_sections["reference"][0] + "\n" + rich_sections["reference"][1])
        set_rich_text(parenthetical_text, rich_sections["parenthetical"][0] + "\n" + rich_sections["parenthetical"][1])
        set_rich_text(narrative_text, rich_sections["narrative"][0] + "\n" + rich_sections["narrative"][1])

    def generate_output() -> None:
        bibtex_text = input_text.get("1.0", tk.END).strip()
        if not bibtex_text:
            messagebox.showinfo("UNSW Harvard Generator", "Paste BibTeX into the input box first.")
            return
        page_value = page_var.get().strip() or None
        entries = parse_bibtex(bibtex_text)
        populate_output(entries, page_value)

    def generate_link_output() -> None:
        raw_urls = url_text.get("1.0", tk.END).strip()
        urls = parse_url_list(raw_urls)
        if not urls:
            messagebox.showinfo("UNSW Harvard Generator", "Paste one or more http/https links first.")
            return
        entries = build_entries_from_urls(urls)
        populate_output(entries, None)

    def copy_output(widget: Any) -> None:
        text = widget.get("1.0", tk.END).strip()
        if not text:
            return
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        messagebox.showinfo("UNSW Harvard Generator", "Text copied to clipboard.")

    def open_file() -> None:
        path = filedialog.askopenfilename(
            title="Open BibTeX file",
            filetypes=[("BibTeX files", "*.bib *.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        input_text.delete("1.0", tk.END)
        input_text.insert("1.0", Path(path).read_text(encoding="utf-8"))

    root = tk.Tk()
    root.title("UNSW Harvard Citation Generator")
    root.geometry("1200x760")
    root.minsize(980, 640)

    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
        
    root.columnconfigure(0, weight=1)
    root.rowconfigure(1, weight=1)

    header = ttk.Frame(root, padding=16)
    header.grid(row=0, column=0, sticky="ew")
    header.columnconfigure(0, weight=1)

    title = ttk.Label(header, text="UNSW Harvard Citation Generator", font=("Helvetica", 20, "bold"))
    title.grid(row=0, column=0, sticky="w")
    subtitle = ttk.Label(
        header,
        text="Paste BibTeX on the left, then generate a copy-ready reference list and in-text citations on the right.",
    )
    subtitle.grid(row=1, column=0, sticky="w", pady=(6, 0))

    controls = ttk.Frame(root, padding=(16, 0, 16, 12))
    controls.grid(row=1, column=0, sticky="nsew")
    controls.columnconfigure(0, weight=1)
    controls.columnconfigure(1, weight=1)
    controls.rowconfigure(1, weight=1)

    input_frame = ttk.Labelframe(controls, text="BibTeX input", padding=12)
    input_frame.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 8))
    input_frame.columnconfigure(0, weight=1)
    input_frame.rowconfigure(1, weight=1)

    input_notebook = ttk.Notebook(input_frame)
    input_notebook.grid(row=0, column=0, sticky="nsew")

    bibtex_tab = ttk.Frame(input_notebook, padding=4)
    url_tab = ttk.Frame(input_notebook, padding=4)
    input_notebook.add(bibtex_tab, text="BibTeX")
    input_notebook.add(url_tab, text="Links")

    bibtex_tab.columnconfigure(0, weight=1)
    bibtex_tab.rowconfigure(1, weight=1)
    url_tab.columnconfigure(0, weight=1)
    url_tab.rowconfigure(1, weight=1)

    page_var = tk.StringVar()

    bibtex_toolbar = ttk.Frame(bibtex_tab)
    bibtex_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    bibtex_toolbar.columnconfigure(0, weight=1)

    page_entry = ttk.Entry(bibtex_toolbar, textvariable=page_var, width=16)
    page_entry.grid(row=0, column=0, sticky="w")
    page_label = ttk.Label(bibtex_toolbar, text="Page number (optional)")
    page_label.grid(row=0, column=1, sticky="w", padx=(8, 16))

    open_button = ttk.Button(bibtex_toolbar, text="Open .bib file", command=open_file)
    open_button.grid(row=0, column=2, sticky="e", padx=(0, 8))
    generate_button = ttk.Button(bibtex_toolbar, text="Generate", command=generate_output)
    generate_button.grid(row=0, column=3, sticky="e")

    input_text = tk.Text(bibtex_tab, wrap="word", undo=True)
    input_scrollbar = ttk.Scrollbar(bibtex_tab, orient="vertical", command=input_text.yview)
    input_text.configure(yscrollcommand=input_scrollbar.set)
    input_text.grid(row=1, column=0, sticky="nsew")
    input_scrollbar.grid(row=1, column=1, sticky="ns")

    url_toolbar = ttk.Frame(url_tab)
    url_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    url_toolbar.columnconfigure(0, weight=1)
    url_hint = ttk.Label(url_toolbar, text="Paste one URL per line. The tool will fetch titles and generate citations.")
    url_hint.grid(row=0, column=0, sticky="w")
    generate_links_button = ttk.Button(url_toolbar, text="Fetch & generate", command=generate_link_output)
    generate_links_button.grid(row=0, column=1, sticky="e")

    url_text = tk.Text(url_tab, wrap="word", undo=True)
    url_scrollbar = ttk.Scrollbar(url_tab, orient="vertical", command=url_text.yview)
    url_text.configure(yscrollcommand=url_scrollbar.set)
    url_text.grid(row=1, column=0, sticky="nsew")
    url_scrollbar.grid(row=1, column=1, sticky="ns")

    output_frame = ttk.Labelframe(controls, text="Copy-ready output", padding=12)
    output_frame.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(8, 0))
    output_frame.columnconfigure(0, weight=1)
    output_frame.rowconfigure(0, weight=1)

    notebook = ttk.Notebook(output_frame)
    notebook.grid(row=0, column=0, sticky="nsew")

    reference_tab = ttk.Frame(notebook, padding=4)
    parenthetical_tab = ttk.Frame(notebook, padding=4)
    narrative_tab = ttk.Frame(notebook, padding=4)
    notebook.add(reference_tab, text="Reference list")
    notebook.add(parenthetical_tab, text="In-text: parenthetical")
    notebook.add(narrative_tab, text="In-text: narrative")

    reference_tab.columnconfigure(0, weight=1)
    reference_tab.rowconfigure(1, weight=1)
    parenthetical_tab.columnconfigure(0, weight=1)
    parenthetical_tab.rowconfigure(1, weight=1)
    narrative_tab.columnconfigure(0, weight=1)
    narrative_tab.rowconfigure(1, weight=1)

    def make_output_tab(parent: Any, label: str):
        toolbar = ttk.Frame(parent)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar.columnconfigure(0, weight=1)
        button = ttk.Button(toolbar, text=f"Copy {label}")
        button.grid(row=0, column=0, sticky="w")
        text_widget = tk.Text(parent, wrap="word")
        text_widget.configure(state="disabled")
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)
        text_widget.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")
        return text_widget, button

    reference_text, reference_copy_button = make_output_tab(reference_tab, "reference list")
    parenthetical_text, parenthetical_copy_button = make_output_tab(parenthetical_tab, "parenthetical citations")
    narrative_text, narrative_copy_button = make_output_tab(narrative_tab, "narrative citations")

    reference_copy_button.configure(command=lambda: copy_output(reference_text))
    parenthetical_copy_button.configure(command=lambda: copy_output(parenthetical_text))
    narrative_copy_button.configure(command=lambda: copy_output(narrative_text))

    if tkfont is not None:
        italic_font = tkfont.Font(font=reference_text.cget("font"))
        italic_font.configure(slant="italic")
        for widget in (reference_text, parenthetical_text, narrative_text):
            widget.tag_configure("italic", font=italic_font)
            widget.tag_configure("heading", font=("Helvetica", 12, "bold"))
            widget.tag_configure("indent", lmargin1=24, lmargin2=24)

    def make_rich_output(widget: Any, title: str, body: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", title + "\n", ("heading",))
        for line in body.splitlines():
            start_index = widget.index(tk.END)
            render_rich_text(widget, line + "\n")
            line_start = f"{start_index} linestart"
            line_end = f"{start_index} lineend"
            if line.startswith("    "):
                widget.tag_add("indent", line_start, line_end)
        widget.configure(state="disabled")

    def populate_output(entries: list[BibEntry], page_value: Optional[str]) -> None:
        if not entries:
            fill_text_widget(reference_text, "No BibTeX entries found.")
            fill_text_widget(parenthetical_text, "No BibTeX entries found.")
            fill_text_widget(narrative_text, "No BibTeX entries found.")
            return
        rich_sections = build_rich_output(entries, page=page_value)
        make_rich_output(reference_text, rich_sections["reference"][0], rich_sections["reference"][1])
        make_rich_output(parenthetical_text, rich_sections["parenthetical"][0], rich_sections["parenthetical"][1])
        make_rich_output(narrative_text, rich_sections["narrative"][0], rich_sections["narrative"][1])

    footer = ttk.Frame(root, padding=(16, 0, 16, 16))
    footer.grid(row=2, column=0, sticky="ew")
    footer.columnconfigure(0, weight=1)
    hint = ttk.Label(
        footer,
        text="If you only need terminal use, run: python unsw_harvard_cite_generator.py input.bib",
    )
    hint.grid(row=0, column=0, sticky="w")

    root.mainloop()


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if args.gui:
        launch_gui()
        return 0
    raw_text = read_input(args.input)
    entries = parse_bibtex(raw_text)
    if not entries:
        print("No BibTeX entries found.", file=sys.stderr)
        return 1
    print(build_output(entries, page=args.page))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())