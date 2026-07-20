"""Step 2 of the pipeline: turn extracted material into an LLM-Wiki markdown doc.

Takes the gathered material from ``extract`` and asks the LLM (no tools) to
write a clean, well-structured wiki page, then prepends YAML front-matter
recording provenance (sources, date range, the original query).
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

from .agent import make_openai
from .config import SOURCES

_WRITER_SYSTEM_PROMPT = """You are a senior technical writer maintaining an internal engineering knowledge wiki ("LLM Wiki").
Turn the supplied raw material (messages / emails already gathered from Teams and Mail) into a single, polished Markdown wiki page.

Rules:
- Start with a single H1 title line: `# <concise descriptive title>`.
- Write in the same language as the source material (Korean if the material is Korean).
- Organise into clear sections with H2/H3 headings (e.g. 개요, 배경, 방법/절차, 예시, 주의사항, 참고).
- Preserve technical accuracy: quote commands, code, configs verbatim inside fenced code blocks.
- Synthesize and de-duplicate; do not just copy the raw log. Remove chatter and PII where not essential.
- Do NOT invent facts. If the material is thin, keep the page short and note what is missing.
- End with a `## 출처` section that lists each source item (source type, author, date, and ID) used.
- Output ONLY the Markdown document — no preamble, no code fence around the whole thing."""


def _slugify(title: str) -> str:
    text = title.strip().lower()
    # keep unicode word chars (incl. Hangul), replace runs of others with '-'
    text = re.sub(r"[^\w가-힣]+", "-", text, flags=re.UNICODE)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "untitled"


def _extract_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        m = re.match(r"^#\s+(.+?)\s*$", line)
        if m:
            return m.group(1).strip()
    return fallback


def _yaml_escape(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_front_matter(meta: dict) -> str:
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, (list, tuple)):
            rendered = "[" + ", ".join(_yaml_escape(v) for v in value) + "]"
            lines.append(f"{key}: {rendered}")
        else:
            lines.append(f"{key}: {_yaml_escape(value)}")
    lines.append("---")
    return "\n".join(lines)


def assemble_document(body_markdown: str, meta: dict) -> str:
    return f"{build_front_matter(meta)}\n\n{body_markdown.strip()}\n"


async def to_markdown(extract_result: dict, extra_meta: dict | None = None, progress=None) -> dict:
    """Generate a wiki markdown document from an extraction result.

    Returns ``{"title", "slug", "markdown", "meta", "body"}``.
    """
    oa = make_openai()
    if oa is None:
        raise RuntimeError("LLM_NOT_CONFIGURED")

    query = extract_result.get("query", "")
    material = extract_result.get("answer", "")
    source_labels = [
        SOURCES[k].label for k in extract_result.get("sources", []) if k in SOURCES
    ]

    user_content = (
        f"원본 추출 요청(질의): {query}\n"
        f"데이터 범위: {extract_result.get('start')} .. {extract_result.get('end')}\n"
        f"출처: {', '.join(source_labels)}\n\n"
        "=== 수집된 원본 자료 ===\n"
        f"{material}"
    )

    if progress:
        try:
            progress("위키 문서 생성 중… (LLM 작성)")
        except Exception:  # noqa: BLE001
            pass

    completion = await asyncio.to_thread(
        oa["client"].chat.completions.create,
        model=oa["model"],
        messages=[
            {"role": "system", "content": _WRITER_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
    )
    body = completion.choices[0].message.content or ""

    title = _extract_title(body, fallback=query or "제목 없음")
    slug = _slugify(title)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    meta = {
        "title": title,
        "generated": generated_at,
        "sources": source_labels,
        "date_range": f"{extract_result.get('start')}..{extract_result.get('end')}",
        "query": query,
        "generator": "llmwiki-pipeline",
    }
    if extra_meta:
        meta.update(extra_meta)

    markdown = assemble_document(body, meta)
    return {"title": title, "slug": slug, "markdown": markdown, "meta": meta, "body": body}
