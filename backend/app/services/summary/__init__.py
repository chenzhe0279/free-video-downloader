"""AI 视频总结：逐字稿获取、DeepSeek 总结、任务与缓存。

本包与现有下载/预览/去水印逻辑完全解耦；外部只通过
``app.services.summary.tasks.summary_manager`` 和 ``app.api.summary`` 使用。
"""
