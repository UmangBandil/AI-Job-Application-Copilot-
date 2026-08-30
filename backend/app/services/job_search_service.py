"""Job search API integration — Adzuna + RemoteOK."""

import httpx


async def search_adzuna(
    query: str,
    location: str = "",
    page: int = 1,
    app_id: str = "",
    app_key: str = "",
) -> list[dict]:
    """Search Adzuna job board API."""
    if not app_id or not app_key:
        return []

    params = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": 20,
        "page": page,
        "what": query,
        "content-type": "application/json",
    }
    if location:
        params["where"] = location

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                "https://api.adzuna.com/v1/api/jobs/in/search",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

    results = []
    for item in data.get("results", []):
        results.append({
            "title": item.get("title", ""),
            "company": item.get("company", {}).get("display_name", ""),
            "location": item.get("location", {}).get("display_name", ""),
            "description": item.get("description", ""),
            "url": item.get("redirect_url", ""),
            "source": "adzuna",
            "salary_min": item.get("salary_min"),
            "salary_max": item.get("salary_max"),
            "raw_data": item,
        })

    return results


async def search_remoteok(
    query: str = "",
    page: int = 1,
) -> list[dict]:
    """Search RemoteOK job board (free API, no key needed)."""
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                "https://remoteok.com/api",
                headers={"User-Agent": "JobCopilot/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

    # RemoteOK returns all jobs; filter client-side
    results = []
    query_lower = query.lower()

    for item in data:
        if not isinstance(item, dict) or "id" not in item:
            continue

        title = item.get("position", "")
        tags = " ".join(item.get("tags", [])).lower()
        desc = item.get("description", "").lower()

        if query and query_lower not in title.lower() and query_lower not in tags and query_lower not in desc:
            continue

        results.append({
            "title": title,
            "company": item.get("company", ""),
            "location": item.get("location", "Remote"),
            "description": item.get("description", ""),
            "url": f"https://remoteok.com/remote-jobs/{item.get('slug', item.get('id', ''))}",
            "source": "remoteok",
            "salary_min": None,
            "salary_max": None,
            "raw_data": item,
        })

    # Simple pagination (RemoteOK returns all, we slice)
    start = (page - 1) * 20
    return results[start : start + 20]


async def search_jobs(
    query: str,
    location: str = "",
    page: int = 1,
    source: str = "all",
    adzuna_app_id: str = "",
    adzuna_app_key: str = "",
) -> list[dict]:
    """Unified job search across available sources."""
    results = []

    if source in ("all", "adzuna"):
        adzuna_results = await search_adzuna(
            query, location, page, adzuna_app_id, adzuna_app_key
        )
        results.extend(adzuna_results)

    if source in ("all", "remoteok"):
        remoteok_results = await search_remoteok(query, page)
        results.extend(remoteok_results)

    return results
