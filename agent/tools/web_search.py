"""
网络搜索 / 信息获取工具，基于 Brave Search API。

需要在环境变量里配置 BRAVE_SEARCH_API_KEY（见项目根目录 .env / .env.example）。
"""
import os

import requests
from langchain_core.tools import tool

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """在互联网上搜索信息，返回相关网页的标题、链接和摘要。

    当问题涉及最新的、模型训练数据里可能没有的公开信息时使用这个工具。
    """
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not api_key:
        raise RuntimeError(
            "BRAVE_SEARCH_API_KEY 未设置，请在 .env 中配置后再使用网络搜索工具"
        )

    response = requests.get(
        BRAVE_SEARCH_URL,
        params={"q": query, "count": max_results},
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    results = data.get("web", {}).get("results", [])
    if not results:
        return f"没有搜到跟「{query}」相关的结果"

    formatted = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "(无标题)")
        url = r.get("url", "")
        description = r.get("description", "")
        formatted.append(f"{i}. {title}\n   {url}\n   {description}")

    return "\n\n".join(formatted)


def get_web_search_tool():
    """保留工厂函数形式，方便以后需要按调用方配置不同参数时扩展。"""
    return web_search
