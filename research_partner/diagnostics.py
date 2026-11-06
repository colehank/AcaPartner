"""内部错误的可关联诊断，不记录异常文本、源码行或请求内容。"""

import logging
import secrets
from collections import deque


logger = logging.getLogger(__name__)


def record_internal_error(error: Exception) -> str:
    error_id = secrets.token_hex(8)
    frames: deque[str] = deque(maxlen=24)
    traceback = error.__traceback__
    while traceback is not None:
        frame = traceback.tb_frame
        frames.append(
            f"{frame.f_globals.get('__name__', '<unknown>')}:"
            f"{frame.f_code.co_name}:{traceback.tb_lineno}"
        )
        traceback = traceback.tb_next
    # exc_info 和格式化 traceback 会附带异常文本，可能包含凭据或科研内容。
    logger.error(
        "internal_error id=%s type=%s frames=%s",
        error_id,
        type(error).__name__,
        " > ".join(frames),
    )
    return error_id
