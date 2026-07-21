"""
内部数据检索工具 —— 占位实现。

这是四个能力里唯一没有现成 API 可以直接用的一个，因为"内部数据"是
什么、存在哪里，只有你自己知道。等你确定了具体的数据源（向量库、
Elasticsearch、内部检索服务等）之后，替换 _search_internal_knowledge_base
的实现即可，工具的名字、描述、输入输出格式保持不变，上层 agent 的组装
代码（agent/agent.py）不需要跟着改。
"""
from langchain_core.tools import tool


def _search_internal_knowledge_base(query: str) -> str:
    # TODO: 替换成真实的检索实现，例如：
    #   - 向量库检索：Chroma / FAISS / pgvector 等 + embedding 模型
    #   - 全文检索：Elasticsearch / Meilisearch
    #   - 调用现有的内部搜索 / 知识库 API
    return f"[占位实现] 尚未接入真实的内部知识库，查询词：{query}"


@tool
def search_internal_knowledge_base(query: str) -> str:
    """检索公司内部文档、知识库或专有数据源，返回相关内容片段。

    当问题涉及内部业务信息、公司专有数据，而不是公开的网络信息时，
    优先使用这个工具而不是网络搜索。
    """
    return _search_internal_knowledge_base(query)
