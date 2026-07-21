"""
第三方业务 API 工具 —— 占位实现。

目前用一个笼统的 call_third_party_api 作为占位符。等确定了具体要接入
哪些第三方服务（CRM、工单系统、邮件、日历……）之后，建议把这个笼统
的工具拆成每个服务各自独立的、有明确输入 schema 的工具（例如
create_crm_ticket(title, description) 而不是 call_third_party_api(action,
payload)），这样模型调用时出错率更低，也更方便做权限控制。
"""
from langchain_core.tools import tool


@tool
def call_third_party_api(action: str, payload: str) -> str:
    """调用第三方业务 API 执行具体操作。

    action 是要执行的操作名（例如 "create_ticket"、"send_email"），
    payload 是该操作需要的参数，用 JSON 字符串表示。

    注意：这是一个占位实现，实际接入真实第三方服务后应该拆分成多个
    独立的工具，而不是长期依赖这一个笼统的调用入口。
    """
    return f"[占位实现] action={action}, payload={payload} 尚未接入真实的第三方 API"
