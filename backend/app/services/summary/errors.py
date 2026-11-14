from __future__ import annotations


class SummaryError(Exception):
    """AI 总结业务错误基类。"""


class SummaryValidationError(SummaryError):
    """输入视频不符合总结条件（时长、合集、无音频等）。"""


class SummaryDisabledError(SummaryError):
    """功能未启用或缺少 API Key。"""


class SummaryQuotaError(SummaryError):
    """超过每日额度。"""


class SummaryBusyError(SummaryError):
    """同时进行的总结任务过多。"""
