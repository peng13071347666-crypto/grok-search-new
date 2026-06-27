#!/usr/bin/env python3
"""
grok-search — AI-agent web research CLI with multi-source supplementation.

Architecture:
  - Simple search:    direct Grok API call via smart_search module
  - Deep search:      3-way parallel (Grok + Brave + Intent provider)
  - Individual APIs:  direct httpx calls with 1-retry on network errors
  - Planner:          direct call via smart_search module

Config:  env GROK_SEARCH_<KEY>  >  ~/.config/grok-search/config.json  >  defaults
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

# Import smart_search directly (self-contained, no subprocess)
import smart_search.service as ss_service
import smart_search.config as ss_config

# ============================================================================
# Constants
# ============================================================================

CONFIG_DIR = Path.home() / ".config" / "grok-search"
CONFIG_FILE = CONFIG_DIR / "config.json"

CONFIG_KEYS = {
    "BRAVE_API_KEY",
    "BRAVE_API_URL",
    "BAIDU_API_KEY",
    "BAIDU_SECRET_KEY",
    "BAIDU_API_URL",
    "NEWS_API_KEY",
    "NEWS_API_URL",
    "SERPER_API_KEY",
    "SERPER_API_URL",
    "TAVILY_API_KEY",
    "TAVILY_API_URL",
}

DEFAULT_VALUES: dict[str, str] = {
    "BRAVE_API_URL": "https://api.search.brave.com/res/v1",
    "BAIDU_API_URL": "https://qianfan.baidubce.com/v2/ai_search/web_search",
    "NEWS_API_URL": "https://newsapi.org/v2",
    "SERPER_API_URL": "https://google.serper.dev/search",
    "TAVILY_API_URL": "https://api.tavily.com",
}

EXIT_CODES: dict[str, int] = {
    "config_error": 3,
    "parameter_error": 2,
    "network_error": 4,
    "timeout": 4,
    "rate_limited": 5,
}

SMART_SEARCH_CONFIG = Path.home() / ".config" / "smart-search" / "config.json"


# ============================================================================
# Config
# ============================================================================

class Config:
    """JSON-file config with env-var override.  Reads ~/.config/grok-search/config.json."""

    _data: dict[str, Any] = {}

    @classmethod
    def load(cls) -> None:
        if CONFIG_FILE.exists():
            try:
                cls._data = json.loads(CONFIG_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                cls._data = {}
        else:
            cls._data = {}

    @classmethod
    def save(cls) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cls._data, indent=2, ensure_ascii=False))
        CONFIG_FILE.chmod(0o600)

    @classmethod
    def get(cls, key: str) -> str:
        env_val = os.environ.get(f"GROK_SEARCH_{key}")
        if env_val is not None:
            return env_val
        val = cls._data.get(key)
        if val is not None:
            return val
        return DEFAULT_VALUES.get(key, "")

    @classmethod
    def set(cls, key: str, value: str) -> None:
        cls._data[key] = value
        cls.save()

    @classmethod
    def unset(cls, key: str) -> None:
        cls._data.pop(key, None)
        cls.save()

    @classmethod
    def get_all(cls) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key in sorted(CONFIG_KEYS):
            val = cls.get(key)
            result[key] = cls._mask(key, val)
        return result

    @classmethod
    def get_masked(cls, key: str) -> str:
        return cls._mask(key, cls.get(key))

    @staticmethod
    def _mask(key: str, value: str) -> str:
        if not value:
            return ""
        if ("KEY" in key or "SECRET" in key) and len(value) > 8:
            return value[:4] + "****" + value[-4:]
        return value


# ============================================================================
# Retry helper
# ============================================================================

async def _retry(
    fn, *args: Any, max_retries: int = 1, retry_delay: float = 1.0, **kwargs: Any
) -> Any:
    """Call an async function with retry on network/timeout errors.

    Only retries on httpx.TimeoutException and 5xx/429 HTTP errors.
    Does NOT retry on 4xx (except 429) or config errors.
    """
    last_error: Any = None
    for attempt in range(max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except httpx.TimeoutException:
            last_error = sys.exc_info()[1]
            if attempt < max_retries:
                print(f"  ⚠ {fn.__name__}: 超时，{retry_delay}s 后重试 ({attempt + 1}/{max_retries})...", file=sys.stderr)
                await asyncio.sleep(retry_delay)
        except httpx.HTTPStatusError as e:
            last_error = e
            if e.response.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                print(f"  ⚠ {fn.__name__}: HTTP {e.response.status_code}，{retry_delay}s 后重试 ({attempt + 1}/{max_retries})...", file=sys.stderr)
                await asyncio.sleep(retry_delay)
            else:
                raise
        except Exception:
            raise  # config errors, etc. — no retry
    raise last_error  # type: ignore[misc]


# ============================================================================
# Helpers
# ============================================================================

def ok_result(
    provider: str, query: str, results: list[dict], elapsed_ms: float, **extra: Any
) -> dict:
    return {
        "ok": True,
        "provider": provider,
        "query": query,
        "results": results,
        "total": len(results),
        "elapsed_ms": round(elapsed_ms, 2),
        **extra,
    }


def error_result(
    provider: str,
    query: str,
    error_type: str,
    error: str,
    elapsed_ms: float = 0,
) -> dict:
    return {
        "ok": False,
        "provider": provider,
        "query": query,
        "results": [],
        "total": 0,
        "elapsed_ms": round(elapsed_ms, 2),
        "error_type": error_type,
        "error": error,
    }


def normalize_url(url: str) -> str:
    """Normalize URL for dedup: lowercase scheme+host, strip www & trailing slash & fragment."""
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = parsed.path.rstrip("/") or "/"
        return urlunparse((scheme, netloc, path, parsed.params, parsed.query, ""))
    except Exception:
        print(f"  ⚠ normalize_url: 无法解析 URL '{url[:100]}'", file=sys.stderr)
        return url


def merge_source_lists(*lists: list[dict]) -> list[dict]:
    """Merge multiple source lists, deduplicating by normalized URL.

    Items without a URL are always included. First occurrence wins (primary_sources priority).
    """
    seen: set[str] = set()
    merged: list[dict] = []
    for src_list in lists:
        for item in src_list:
            url = item.get("url", "") or item.get("link", "")
            if url:
                norm = normalize_url(url)
                if norm in seen:
                    continue
                seen.add(norm)
            merged.append(item)
    return merged


def _get_tavily_key_from_smart_search() -> str:
    """Try to read Tavily API key from smart-search config as fallback."""
    if not SMART_SEARCH_CONFIG.exists():
        return ""
    try:
        data = json.loads(SMART_SEARCH_CONFIG.read_text())
        return data.get("TAVILY_API_KEY", "")
    except Exception:
        print("  ⚠ 无法读取 smart-search 配置文件", file=sys.stderr)
        return ""


# ============================================================================
# Provider: Brave Search
# ============================================================================

async def _brave_search_impl(query: str, count: int = 5) -> dict:
    api_key = Config.get("BRAVE_API_KEY")
    if not api_key:
        return error_result("brave", query, "config_error", "BRAVE_API_KEY 未配置")

    api_url = Config.get("BRAVE_API_URL").rstrip("/")
    url = f"{api_url}/web/search"
    headers = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
    }
    params = {"q": query, "count": min(count, 20), "extra_snippets": True}

    t0 = time.time()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("web", {}).get("results", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "description": (item.get("description", "") or "")[:300],
            "provider": "brave",
        })
    return ok_result("brave", query, results, (time.time() - t0) * 1000)


async def brave_search(query: str, count: int = 5) -> dict:
    try:
        return await _retry(_brave_search_impl, query, count)
    except httpx.HTTPStatusError as e:
        t0 = time.time()
        et = "rate_limited" if e.response.status_code == 429 else "network_error"
        return error_result("brave", query, et, f"Brave API HTTP {e.response.status_code}", 0)
    except httpx.TimeoutException:
        return error_result("brave", query, "timeout", "Brave API 超时", 0)
    except Exception as e:
        print(f"  ⚠ brave_search: {e}", file=sys.stderr)
        return error_result("brave", query, "network_error", f"Brave API: {e}", 0)


# ============================================================================
# Provider: Baidu (千帆 AI Search)
# ============================================================================

async def _baidu_search_impl(query: str, count: int = 5) -> dict:
    api_key = Config.get("BAIDU_API_KEY")
    if not api_key:
        return error_result("baidu", query, "config_error", "BAIDU_API_KEY 未配置")

    api_url = Config.get("BAIDU_API_URL")
    headers = {
        "X-Appbuilder-Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "messages": [{"role": "user", "content": query}],
        "search_source": "baidu_search_v2",
        "resource_type_filter": [{"type": "web", "top_k": count}],
    }

    t0 = time.time()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(api_url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("references", []):
        content = item.get("content", "") or ""
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "description": content[:300],
            "provider": "baidu",
        })
    return ok_result("baidu", query, results, (time.time() - t0) * 1000)


async def baidu_search(query: str, count: int = 5) -> dict:
    try:
        return await _retry(_baidu_search_impl, query, count)
    except httpx.HTTPStatusError as e:
        et = "rate_limited" if e.response.status_code == 429 else "network_error"
        return error_result("baidu", query, et, f"百度 API HTTP {e.response.status_code}", 0)
    except httpx.TimeoutException:
        return error_result("baidu", query, "timeout", "百度 API 超时", 0)
    except Exception as e:
        print(f"  ⚠ baidu_search: {e}", file=sys.stderr)
        return error_result("baidu", query, "network_error", f"百度 API: {e}", 0)


# ============================================================================
# Provider: News API
# ============================================================================

async def _news_search_impl(query: str, count: int = 5) -> dict:
    api_key = Config.get("NEWS_API_KEY")
    if not api_key:
        return error_result("news", query, "config_error", "NEWS_API_KEY 未配置")

    api_url = Config.get("NEWS_API_URL").rstrip("/")
    url = f"{api_url}/everything"
    params = {
        "q": query,
        "pageSize": min(count, 100),
        "sortBy": "publishedAt",
        "apiKey": api_key,
    }

    t0 = time.time()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("articles", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "description": (item.get("description", "") or "")[:300],
            "provider": "news",
        })
    return ok_result("news", query, results, (time.time() - t0) * 1000)


async def news_search(query: str, count: int = 5) -> dict:
    try:
        return await _retry(_news_search_impl, query, count)
    except httpx.HTTPStatusError as e:
        et = "rate_limited" if e.response.status_code == 429 else "network_error"
        return error_result("news", query, et, f"News API HTTP {e.response.status_code}", 0)
    except httpx.TimeoutException:
        return error_result("news", query, "timeout", "News API 超时", 0)
    except Exception as e:
        print(f"  ⚠ news_search: {e}", file=sys.stderr)
        return error_result("news", query, "network_error", f"News API: {e}", 0)


# ============================================================================
# Provider: Serper (Google)
# ============================================================================

async def _serper_search_impl(query: str, count: int = 5) -> dict:
    api_key = Config.get("SERPER_API_KEY")
    if not api_key:
        return error_result("serper", query, "config_error", "SERPER_API_KEY 未配置")

    api_url = Config.get("SERPER_API_URL")
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    body = {"q": query, "num": min(count, 25)}

    t0 = time.time()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(api_url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("organic", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "description": (item.get("snippet", "") or "")[:300],
            "provider": "serper",
        })
    return ok_result("serper", query, results, (time.time() - t0) * 1000)


async def serper_search(query: str, count: int = 5) -> dict:
    try:
        return await _retry(_serper_search_impl, query, count)
    except httpx.HTTPStatusError as e:
        et = "rate_limited" if e.response.status_code == 429 else "network_error"
        return error_result("serper", query, et, f"Serper API HTTP {e.response.status_code}", 0)
    except httpx.TimeoutException:
        return error_result("serper", query, "timeout", "Serper API 超时", 0)
    except Exception as e:
        print(f"  ⚠ serper_search: {e}", file=sys.stderr)
        return error_result("serper", query, "network_error", f"Serper API: {e}", 0)


# ============================================================================
# Provider: Tavily (Brave fallback)
# ============================================================================

async def _tavily_search_impl(query: str, count: int = 5) -> dict:
    api_key = Config.get("TAVILY_API_KEY")
    if not api_key:
        api_key = _get_tavily_key_from_smart_search()
    if not api_key:
        return error_result("tavily", query, "config_error", "TAVILY_API_KEY 未配置")

    api_url = Config.get("TAVILY_API_URL").rstrip("/")
    url = f"{api_url}/search"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "query": query,
        "max_results": count,
        "search_depth": "advanced",
        "include_raw_content": False,
        "include_answer": False,
    }

    t0 = time.time()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("results", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "description": (item.get("content", "") or "")[:300],
            "provider": "tavily",
        })
    return ok_result("tavily", query, results, (time.time() - t0) * 1000)


async def tavily_search(query: str, count: int = 5) -> dict:
    try:
        return await _retry(_tavily_search_impl, query, count)
    except httpx.HTTPStatusError as e:
        et = "rate_limited" if e.response.status_code == 429 else "network_error"
        return error_result("tavily", query, et, f"Tavily API HTTP {e.response.status_code}", 0)
    except httpx.TimeoutException:
        return error_result("tavily", query, "timeout", "Tavily API 超时", 0)
    except Exception as e:
        print(f"  ⚠ tavily_search: {e}", file=sys.stderr)
        return error_result("tavily", query, "network_error", f"Tavily API: {e}", 0)


# ============================================================================
# Smart-search integration (direct import, no subprocess)
# ============================================================================

async def _call_grok_search(query: str, timeout: int = 120, model: str = "") -> dict:
    """Call Grok main search via smart_search.service."""
    try:
        result = await asyncio.wait_for(
            ss_service.search(query, model=model or "", validation="balanced"),
            timeout=timeout + 30,
        )
        return result
    except asyncio.TimeoutError:
        return {"ok": False, "error_type": "timeout", "error": f"Grok 搜索超时 ({timeout}s)"}
    except Exception as e:
        print(f"  ⚠ Grok 搜索失败: {e}", file=sys.stderr)
        return {"ok": False, "error_type": "network_error", "error": f"Grok 搜索失败: {e}"}


async def _call_grok_fetch(url: str) -> dict:
    """Call fetch via smart_search.service."""
    try:
        return await asyncio.wait_for(ss_service.fetch(url), 90)
    except asyncio.TimeoutError:
        return {"ok": False, "error_type": "timeout", "error": "Fetch 超时 (90s)"}
    except Exception as e:
        return {"ok": False, "error_type": "network_error", "error": f"Fetch 失败: {e}"}


def _call_grok_deep(query: str) -> dict:
    """Call deep research planner via smart_search.service."""
    try:
        return ss_service.build_deep_research_plan(query)
    except Exception as e:
        return {"ok": False, "error_type": "runtime_error", "error": f"Deep planner 失败: {e}"}


# ============================================================================
# Deep Search — 3-way parallel orchestration
# ============================================================================

INTENT_API_MAP = {
    "chinese": baidu_search,
    "news": news_search,
    "general": serper_search,
}


async def deep_search(
    grok_query: str,
    short_query: str,
    intent: str,
    model: str = "",
    timeout: int = 180,
    count: int = 5,
) -> dict:
    """
    Three-way parallel deep search:

      1. Grok main search   (direct smart_search.service call)
      2. Brave search        (with Tavily fallback)
      3. Intent search       (baidu / news / serper)

    All three run concurrently via asyncio.gather.
    """
    t0 = time.time()

    intent_api = INTENT_API_MAP.get(intent, serper_search)

    # ---- task definitions ----

    async def _run_grok() -> dict:
        return await _call_grok_search(grok_query, timeout, model)

    async def _run_brave() -> tuple[dict, str]:
        r = await brave_search(short_query, count)
        if r.get("ok") and r.get("results"):
            return r, "brave"
        t = await tavily_search(short_query, count)
        return t, "tavily"

    async def _run_intent() -> dict:
        return await intent_api(short_query, count)

    # ---- parallel execution ----

    try:
        results = await asyncio.gather(
            _run_grok(), _run_brave(), _run_intent(),
            return_exceptions=True,
        )
    except KeyboardInterrupt:
        raise

    def _unwrap(val: Any, fallback: dict) -> dict:
        if isinstance(val, Exception):
            print(f"  ⚠ deep_search 并行任务异常: {val}", file=sys.stderr)
            return {"ok": False, "error_type": "runtime_error", "error": str(val)}
        return val

    grok_data = _unwrap(results[0], {})
    brave_tuple = results[1]
    if isinstance(brave_tuple, Exception):
        print(f"  ⚠ deep_search Brave 异常: {brave_tuple}", file=sys.stderr)
        brave_data, brave_source = {"ok": False, "error_type": "runtime_error", "error": str(brave_tuple)}, "error"
    else:
        brave_data, brave_source = brave_tuple
    intent_data = _unwrap(results[2], {})

    total_elapsed = (time.time() - t0) * 1000

    # ---- extract results ----

    grok_ok = grok_data.get("ok", False)
    content = grok_data.get("content", "")
    primary_sources = grok_data.get("primary_sources", [])
    if not primary_sources:
        primary_sources = grok_data.get("sources", [])

    brave_ok = brave_data.get("ok", False)
    brave_results = brave_data.get("results", []) if brave_ok else []

    intent_ok = intent_data.get("ok", False)
    intent_results = intent_data.get("results", []) if intent_ok else []

    # ---- merge & dedup ----

    extra_sources = merge_source_lists(brave_results, intent_results)
    all_sources = merge_source_lists(primary_sources, extra_sources)

    # ---- status ----

    supplements_ok = brave_ok or intent_ok
    degraded = (not grok_ok) and supplements_ok
    overall_ok = grok_ok or degraded

    if supplements_ok and extra_sources:
        source_warning = f"补源找到 {len(extra_sources)} 个候选来源，建议通过 fetch 核实关键链接"
    elif supplements_ok and not extra_sources:
        source_warning = "补源完成但未找到额外结果"
    else:
        source_warning = "补源全部失败，结果仅来自 Grok 主搜索"

    return {
        "ok": overall_ok,
        "degraded": degraded,
        "grok_ok": grok_ok,
        "brave_ok": brave_ok,
        "brave_provider": brave_source,
        "intent_ok": intent_ok,
        "content": content,
        "sources": all_sources,
        "sources_count": len(all_sources),
        "primary_sources": primary_sources,
        "primary_sources_count": len(primary_sources),
        "extra_sources": extra_sources,
        "extra_sources_count": len(extra_sources),
        "brave_sources": brave_results,
        "intent_sources": intent_results,
        "source_warning": source_warning,
        "deep_mode": True,
        "provider": "grok-search",
        "intent": intent,
        "grok_command": (
            f"grok-search search --deep \"{grok_query}\" --keywords \"{short_query}\" --intent {intent} --timeout {timeout}"
            + (f" --model {model}" if model else "")
        ),
        "elapsed_ms": round(total_elapsed, 2),
        "grok_elapsed_ms": grok_data.get("elapsed_ms", 0),
        "brave_elapsed_ms": brave_data.get("elapsed_ms", 0),
        "intent_elapsed_ms": intent_data.get("elapsed_ms", 0),
    }


# ============================================================================
# Doctor — configuration check
# ============================================================================

def doctor_check() -> dict:
    checks: dict[str, Any] = {}
    for key in sorted(CONFIG_KEYS):
        val = Config.get(key)
        is_secret = "KEY" in key or "SECRET" in key
        if is_secret:
            checks[key] = {"configured": bool(val), "value": Config.get_masked(key)}
        else:
            checks[key] = {"value": val or "未设置（使用默认值）"}

    # Check smart_search config (embedded, no subprocess)
    ss_info: dict[str, Any] = {"available": True, "version": "embedded", "error": ""}
    try:
        ss_cfg = ss_config.Config()
        ss_info["config_file"] = str(ss_cfg.config_file)
        ss_info["config_exists"] = ss_cfg.config_file.exists()
        ss_info["primary_api_mode"] = ss_cfg.get_saved_config().get("primary_api_mode", "chat-completions")
    except Exception as e:
        ss_info["error"] = str(e)

    core_ok = bool(Config.get("BRAVE_API_KEY")) and bool(
        Config.get("TAVILY_API_KEY") or _get_tavily_key_from_smart_search()
    )

    return {
        "ok": True,
        "config_file": str(CONFIG_FILE),
        "config_exists": CONFIG_FILE.exists(),
        "smart_search": ss_info,
        "core_providers_configured": core_ok,
        "checks": checks,
    }


# ============================================================================
# Config subcommand
# ============================================================================

def config_command(args: argparse.Namespace) -> dict:
    action = getattr(args, "action", None)

    if action == "list":
        return {
            "ok": True,
            "config_file": str(CONFIG_FILE),
            "config": Config.get_all(),
        }

    if action in ("get", "set", "unset"):
        key = args.key.upper()
        if key not in CONFIG_KEYS:
            return {"ok": False, "error_type": "parameter_error", "error": f"未知配置键: {key}"}

    if action == "get":
        return {
            "ok": True,
            "key": key,
            "value": Config.get_masked(key),
            "configured": bool(Config.get(key)),
        }

    if action == "set":
        Config.set(key, args.value)
        return {"ok": True, "key": key, "action": "set", "value": Config.get_masked(key)}

    if action == "unset":
        Config.unset(key)
        return {"ok": True, "key": key, "action": "unset"}

    return {"ok": False, "error_type": "parameter_error", "error": "未知 config 操作，可用: list | get | set | unset"}


# ============================================================================
# Output formatting
# ============================================================================

def _format_sources_block(lines: list[str], sources: list[dict], heading: str) -> None:
    if not sources:
        return
    lines.append(f"## {heading}")
    lines.append("")
    for i, src in enumerate(sources, 1):
        title = src.get("title", "Untitled")
        url = src.get("url", "") or src.get("link", "")
        desc = src.get("description", "") or src.get("snippet", "")
        lines.append(f"{i}. **{title}**")
        if url:
            lines.append(f"   {url}")
        if desc:
            lines.append(f"   > {desc[:200]}")
    lines.append("")


def format_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def format_markdown(data: dict) -> str:
    lines: list[str] = []

    content = data.get("content", "")
    if content:
        lines.append(content)
        lines.append("")

    results = data.get("results", [])
    provider = data.get("provider", "")
    if results and not data.get("deep_mode"):
        lines.append(f"## {provider.title()} Results ({len(results)})")
        lines.append("")
        for i, r in enumerate(results, 1):
            title = r.get("title", "Untitled")
            url = r.get("url", "")
            desc = r.get("description", "")
            lines.append(f"{i}. **{title}**")
            if url:
                lines.append(f"   {url}")
            if desc:
                lines.append(f"   > {desc[:200]}")
        lines.append("")

    if data.get("deep_mode"):
        _format_sources_block(lines, data.get("primary_sources", []), "Primary Sources")
        _format_sources_block(lines, data.get("brave_sources", []), "Brave Sources")
        _format_sources_block(lines, data.get("intent_sources", []), f"{data.get('intent', 'Intent').title()} Sources")

        warning = data.get("source_warning", "")
        if warning:
            lines.append(f"> ⚠️ {warning}")
            lines.append("")

    if not data.get("deep_mode") and not results:
        _format_sources_block(lines, data.get("primary_sources", []), "Primary Sources")
        extra = data.get("extra_sources", [])
        _format_sources_block(lines, extra, "Extra Sources")

    if not data.get("ok"):
        error = data.get("error", "Unknown error")
        lines.append("## Error")
        lines.append("```")
        lines.append(error)
        lines.append("```")
        lines.append("")

    if data.get("deep_mode"):
        lines.append("---")
        grok_mark = "✓" if data.get("grok_ok") else "✗"
        brave_mark = "✓" if data.get("brave_ok") else "✗"
        intent_mark = "✓" if data.get("intent_ok") else "✗"
        lines.append(
            f"*Deep search · intent={data.get('intent', 'N/A')} · "
            f"{data.get('elapsed_ms', 0):.0f}ms*"
        )
        lines.append(f"*Grok: {grok_mark} · Brave: {brave_mark} · Intent: {intent_mark}*")

    if not lines:
        lines.append(f"# {data.get('provider', 'Result')}")
        lines.append("")
        for k, v in data.items():
            if k in ("ok", "provider", "error_type"):
                continue
            if isinstance(v, dict):
                lines.append(f"## {k}")
                lines.append("```json")
                lines.append(json.dumps(v, ensure_ascii=False, indent=2))
                lines.append("```")
                lines.append("")
            elif isinstance(v, list):
                lines.append(f"## {k} ({len(v)})")
                lines.append("```json")
                lines.append(json.dumps(v, ensure_ascii=False, indent=2))
                lines.append("```")
                lines.append("")
            elif v:
                lines.append(f"- **{k}**: {v}")
        if lines:
            lines.append("")

    return "\n".join(lines)


# ============================================================================
# CLI
# ============================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grok-search",
        description="AI-agent web research CLI with multi-source supplementation.",
    )
    parser.add_argument(
        "--format", choices=["json", "markdown"], default="json", help="输出格式 (默认: json)"
    )

    sub = parser.add_subparsers(dest="command", help="子命令")

    # ---- search ----
    p_search = sub.add_parser("search", help="Grok 搜索（简单）或深度搜索（--deep）")
    p_search.add_argument("query", help="搜索查询")
    p_search.add_argument("--deep", action="store_true", help="启用深度搜索（三路并行补源）")
    p_search.add_argument(
        "--short", help="补源搜索关键词，建议 3-8 个词（--deep 时必填）"
    )
    p_search.add_argument(
        "--keywords", help=argparse.SUPPRESS, dest="short"
    )
    p_search.add_argument(
        "--intent",
        choices=["chinese", "news", "general"],
        default="general",
        help="补源意图路由 (默认: general)",
    )
    p_search.add_argument("--model", default="", help="Grok 模型名")
    p_search.add_argument(
        "--timeout", type=int, default=180, help="Grok 超时秒数 (默认: 180)"
    )
    p_search.add_argument(
        "--count", type=int, default=5, help="补源结果数 (默认: 5)"
    )

    # ---- individual providers ----
    for name in ["brave", "baidu", "news", "serper", "tavily"]:
        p = sub.add_parser(name, help=f"{name.title()} 搜索")
        p.add_argument("query", help="搜索查询")
        p.add_argument("--count", type=int, default=5, help="结果数 (默认: 5)")

    # ---- fetch ----
    p_fetch = sub.add_parser("fetch", help="网页抓取核实")
    p_fetch.add_argument("url", help="要抓取的 URL")

    # ---- deep (planner) ----
    p_deep = sub.add_parser("deep", help="Deep Research 规划器（质检参考）")
    p_deep.add_argument("query", help="查询")

    # ---- config ----
    p_config = sub.add_parser("config", help="配置管理")
    p_csub = p_config.add_subparsers(dest="action")
    p_csub.add_parser("list", help="列出所有配置")
    p_cget = p_csub.add_parser("get", help="获取配置值")
    p_cget.add_argument("key", help="配置键名")
    p_cset = p_csub.add_parser("set", help="设置配置值")
    p_cset.add_argument("key", help="配置键名")
    p_cset.add_argument("value", help="配置值")
    p_cunset = p_csub.add_parser("unset", help="删除配置")
    p_cunset.add_argument("key", help="配置键名")

    # ---- doctor ----
    sub.add_parser("doctor", help="配置检查")

    return parser


def _exit_code_for(error_type: str) -> int:
    return EXIT_CODES.get(error_type, 1)


def main() -> None:
    Config.load()
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    result: dict = {}

    # ---- dispatch ----

    if args.command == "search":
        if args.deep:
            if not args.short:
                result = {
                    "ok": False,
                    "error_type": "parameter_error",
                    "error": "--deep 模式需要 --short 参数（补源搜索关键词）",
                }
            else:
                result = asyncio.run(
                    deep_search(
                        grok_query=args.query,
                        short_query=args.short,
                        intent=args.intent,
                        model=args.model,
                        timeout=args.timeout,
                        count=args.count,
                    )
                )
        else:
            result = asyncio.run(_call_grok_search(args.query, args.timeout, args.model))

    elif args.command in ("brave", "baidu", "news", "serper", "tavily"):
        provider_map = {
            "brave": brave_search,
            "baidu": baidu_search,
            "news": news_search,
            "serper": serper_search,
            "tavily": tavily_search,
        }
        result = asyncio.run(provider_map[args.command](args.query, args.count))

    elif args.command == "fetch":
        result = asyncio.run(_call_grok_fetch(args.url))

    elif args.command == "deep":
        result = _call_grok_deep(args.query)

    elif args.command == "config":
        result = config_command(args)

    elif args.command == "doctor":
        result = doctor_check()

    # ---- output ----

    if args.format == "markdown":
        sys.stdout.write(format_markdown(result))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(format_json(result))
        sys.stdout.write("\n")

    if not result.get("ok"):
        sys.exit(_exit_code_for(result.get("error_type", "")))


if __name__ == "__main__":
    main()