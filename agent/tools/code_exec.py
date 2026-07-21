"""
代码执行工具 —— 自建 Docker 沙箱（免费，不需要注册任何第三方服务）。

每次调用起一个隔离的、禁用网络访问的临时容器执行代码，执行完自动删除
容器。需要本机装好 Docker 并且 daemon 处于运行状态。

跟 E2B 的权衡：免费、不用注册、没有第三方依赖；代价是隔离强度、稳定性、
运维责任都在本机——容器跑在你自己的机器上，不是托管在别处的独立云沙箱，
如果这台机器同时要给 OpenClaw 之类的东西用，资源是共享的。
"""
from langchain_core.tools import tool

DOCKER_IMAGE = "python:3.11-slim"
CONTAINER_TIMEOUT_SECONDS = 30
MEMORY_LIMIT = "256m"


@tool
def execute_python_code(code: str) -> str:
    """在隔离的 Docker 沙箱中执行一段 Python 代码，并返回执行结果。

    适用于需要真正运行代码才能得到答案的场景：数值计算、数据处理、
    验证一个算法等。传入完整可执行的 Python 代码字符串。注意：沙箱
    禁用了网络访问，不能用来联网下载东西或访问外部服务。
    """
    try:
        import docker
        from docker.errors import DockerException
    except ImportError:
        return "执行出错：缺少 docker 这个 Python 包，请先 pip install docker"

    try:
        client = docker.from_env()
        client.ping()
    except Exception as e:
        return f"执行出错：连不上本机 Docker，请确认 Docker（或 OrbStack）已经启动。({e})"

    container = None
    try:
        container = client.containers.run(
            DOCKER_IMAGE,
            ["python", "-c", code],
            detach=True,
            mem_limit=MEMORY_LIMIT,
            network_disabled=True,
        )
        result = container.wait(timeout=CONTAINER_TIMEOUT_SECONDS)
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
        exit_code = result.get("StatusCode", -1)

        if exit_code != 0:
            return f"执行出错（退出码 {exit_code}）：\n{logs}"
        return logs if logs.strip() else "(代码执行完成，无输出)"
    except DockerException as e:
        return f"执行出错：{e}"
    except Exception as e:
        return f"执行超时或出错：{e}"
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass
