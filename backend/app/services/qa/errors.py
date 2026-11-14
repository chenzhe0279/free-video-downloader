from __future__ import annotations


class QaError(Exception):
    """AI 问答业务错误基类。"""


class QaDisabledError(QaError):
    """Q&A 关闭或缺少 API Key。"""


class QaQuotaError(QaError):
    """超过每日额度。"""


class QaValidationError(QaError):
    """问题或历史不合法。"""


class QaGateError(QaError):
    """相关性判定失败。"""
