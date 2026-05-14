# Web Intake Tool Research

> Date: 2026-05-14
> Scope: LifeHack DataHub public webpage intake, not core runtime.

## Decision

Use a layered web intake stack instead of choosing one universal crawler.

1. Keep the current DataHub connectors as the default for official files, known attachments, page images, Amap, SCS resources, and controlled manual intake.
2. Add a local static-page extraction layer first, preferably Trafilatura, for school news, local news, talent-market pages, recruitment fair announcements, and public research reports.
3. Use Firecrawl only as an optional managed adapter for pages where clean Markdown extraction is valuable and local tooling is too expensive to maintain.
4. Use Scrapy only when a source becomes a repeated site-level crawl with stable rules, many pages, throttling, retries, and feed exports.
5. Use Playwright directly, or Crawlee/Crawl4AI later, only for dynamic pages that cannot be captured through HTML, official attachments, or manual exports.

No crawler output may bypass DataHub review gates. Web tools produce raw snapshots, Markdown, HTML, metadata, screenshots, or candidate rows. Verified business facts still have to enter existing plans such as `career_source_plan`, `outcome_collection_plan`, `school_recruitment_event`, or later derived marts.

## Tool Findings

### Trafilatura

Best fit: local extraction from static or mostly static pages.

Why it fits this project:

- Python package and CLI, aligned with the current DataHub stack.
- Extracts main text, metadata, formatting, links, tables, and can output TXT, Markdown, CSV, JSON, HTML, XML, and TEI.
- Supports sitemaps, feeds, URL filtering, deduplication, and polite download queues.
- Current license is Apache 2.0; versions before 1.8.0 were GPLv3+, so dependency pinning should avoid older versions.

Use it for:

- 学校就业网通知、双选会公告、地方人才市场新闻、当地媒体应届生招聘专题、招聘平台公开研究报告页面。
- Turning HTML snapshots into clean evidence text before manual review.

Do not use it for:

- CAPTCHA pages, logged-in pages, protected recruitment platforms, or PDF/OFD reports already handled by existing report intake.

Sources checked:

- https://github.com/adbar/trafilatura
- https://www.contextractor.com/

### Firecrawl

Best fit: optional managed scrape adapter.

Why it fits:

- `/scrape` can return Markdown, cleaned HTML, raw HTML, screenshots, links, images, and structured JSON.
- It handles dynamic pages, JS-rendered sites, PDFs, images, caching, proxies, and rate limits as a service.
- The CLI and SDK use `FIRECRAWL_API_KEY`, which matches our environment-variable key policy.

Risks and constraints:

- API cost and third-party data processing make it unsuitable as the default for all pages.
- Firecrawl repository code is AGPL-3.0. Do not vendor or copy server code into DataHub without a license review. Treat the hosted API as an external service adapter.
- Its JSON/LLM extraction should not directly publish metrics. Keep the evidence quote and source URL, then pass through DataHub review.

Use it for:

- Hard-to-clean public pages where managed Markdown extraction reduces manual work.
- One-off or small-batch research pages before we know whether a source deserves a custom parser.

Sources checked:

- https://docs.firecrawl.dev/features/scrape
- https://docs.firecrawl.dev/cli
- https://github.com/firecrawl/firecrawl/blob/main/LICENSE

### Scrapy

Best fit: mature Python site crawler for repeated, structured crawls.

Why it fits:

- Official docs describe it as a Python application framework for crawling websites and extracting structured data.
- It has async request scheduling, CSS/XPath extraction, feed exports, encoding handling, concurrency controls, download delay, and auto-throttling.
- It is better for stable site-level crawlers than one-off evidence intake.

Use it for:

- A repeatable school employment-site crawler after page patterns are known.
- City talent-market pages with stable pagination and consistent announcement templates.

Do not use it first for:

- Small batches, ad hoc source checks, or dynamic pages that need browser execution.

Sources checked:

- https://docs.scrapy.org/en/master/intro/overview.html
- https://github.com/scrapy/scrapy

### Playwright

Best fit: deterministic browser rendering and authenticated/manual sessions.

Why it fits:

- Official Python library launches Chromium, Firefox, or WebKit and supports sync/async APIs.
- It is already consistent with the project's Chrome/Playwright-assisted manual intake direction.
- It should remain the tool for pages needing clicks, downloads, scroll, session cookies, or visible human CAPTCHA entry.

Use it for:

- Official school attachment pages where a human enters CAPTCHA and the browser session downloads the report.
- Dynamic pages where a static fetch or Trafilatura cannot see the content.

Do not use it for:

- Large-scale background crawling unless a queue/throttling layer is added.

Sources checked:

- https://playwright.dev/python/docs/library
- https://github.com/microsoft/playwright/blob/main/LICENSE

### Crawlee for Python

Best fit: crawler orchestration when Playwright plus queues, storage, sessions, throttling, and proxy configuration become recurring needs.

Why it may fit later:

- Python package with optional extras.
- Works with raw HTTP, Parsel, BeautifulSoup, and Playwright.
- Provides crawler queues, storage, session management, throttling, scaling, tracing, and browser-based crawling.

Constraint:

- Some project language emphasizes avoiding blocks and proxy rotation. For LifeHack, this must be interpreted as reliability and politeness for allowed public pages, not as bypassing site restrictions.

Use it for:

- A real crawling subsystem if DataHub needs repeated multi-source web crawling beyond a few configured URLs.

Sources checked:

- https://github.com/apify/crawlee-python
- https://crawlee.dev/python/docs/next/guides

### Crawl4AI

Best fit: local Markdown-oriented extraction for LLM/RAG workflows, potentially useful after a sandbox trial.

Why it may fit:

- Python async crawler focused on clean Markdown, structured extraction, browser control, deep crawling, and PDF parsing.
- Apache-2.0 repository and large community.

Constraints:

- Heavier and faster-moving than Trafilatura; recent docs mention security hotfixes and advanced anti-bot features.
- For this project, do not adopt stealth, proxy escalation, or CAPTCHA bypass workflows. If used, restrict it to public pages and raw snapshot generation.

Use it for:

- A local alternative to Firecrawl for Markdown extraction when we need no third-party API.

Sources checked:

- https://github.com/unclecode/crawl4ai
- https://docs.crawl4ai.com/

## Recommended Absorption Plan

Do not copy mature crawler code into the repository. Absorb mature projects by using them as optional dependencies or external adapters, while keeping LifeHack-specific governance in our own small layer.

Proposed sequence:

1. Add a generic `web_intake_plan` format:
   `source_key, url, source_tier, intended_target, source_date, availability_date, expected_content_type, notes`.
2. Add a static HTML snapshot and extraction adapter:
   use `urllib` for allowed pages and optional Trafilatura for Markdown/text extraction.
3. Store raw HTML, extracted Markdown/text, metadata, response hash, content hash, and fetch manifest under ignored `raw/web_intake/{source_key}/{source_date}/`.
4. Add an audit command that blocks missing source URL, missing dates, non-HTTP URLs, failed content hash, empty extraction, and disallowed targets.
5. Only after static extraction proves insufficient, add an optional Firecrawl adapter using `FIRECRAWL_API_KEY`.
6. Only after a source becomes high-volume and repeatable, promote it to a source-specific Scrapy/Crawlee crawler.

## Project Boundaries

- Core must never call scraping tools directly.
- API keys stay in environment variables, never in config, manifest, frontend, or GitHub.
- CAPTCHA and login walls require human action or controlled manual intake.
- Community scrapers, reverse-engineered APIs, and anti-bot bypass code are research-only and cannot enter raw packages.
- Every extracted fact must carry `source_url`, `source_title`, `evidence_quote`, `source_date`, `availability_date`, and review status before it can affect recommendation evidence.
