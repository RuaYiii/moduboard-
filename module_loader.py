"""
ModuBoard 模块加载器
负责动态发现、加载、热重载用户模块，并提供统一的调用接口。
"""

import os
import sys
import time
import importlib
import importlib.util
import logging
import traceback
from typing import Any, Optional

# 配置日志
logger = logging.getLogger(__name__)


class ModuleLoader:
    """
    模块加载器：扫描 modules/ 目录，动态导入 .py 模块，
    支持热重载（基于文件修改时间），并对外提供 render / on_action 调用。
    """

    def __init__(self, modules_dir: str) -> None:
        """
        初始化模块加载器。

        Args:
            modules_dir: 模块目录的绝对路径
        """
        self.modules_dir: str = os.path.abspath(modules_dir)
        # 已加载的模块对象  {type_name: module}
        self._modules: dict[str, Any] = {}
        # 每个模块文件的上次修改时间  {type_name: mtime}
        self._mtimes: dict[str, float] = {}
        # 上次检查文件修改时间的时间戳 {type_name: timestamp}
        self._last_checks: dict[str, float] = {}

        # 确保模块目录存在
        os.makedirs(self.modules_dir, exist_ok=True)

        # 把模块目录的父目录加入 sys.path，方便 importlib 找到
        parent = os.path.dirname(self.modules_dir)
        if parent not in sys.path:
            sys.path.insert(0, parent)

        logger.info("模块加载器初始化完成，模块目录: %s", self.modules_dir)

    # ------------------------------------------------------------------ #
    #  公开接口
    # ------------------------------------------------------------------ #

    def discover_modules(self) -> dict[str, dict]:
        """
        扫描模块目录，返回所有可用模块的 META 信息。

        Returns:
            {type_name: META_dict, ...}
        """
        result: dict[str, dict] = {}

        if not os.path.isdir(self.modules_dir):
            logger.warning("模块目录不存在: %s", self.modules_dir)
            return result

        for filename in os.listdir(self.modules_dir):
            # 跳过非 .py 文件和 __init__.py
            if not filename.endswith(".py") or filename.startswith("__"):
                continue

            type_name = filename[:-3]  # 去掉 .py 后缀
            try:
                self._check_reload(type_name)
                module = self._modules.get(type_name)
                if module and hasattr(module, "META"):
                    result[type_name] = module.META
                else:
                    logger.warning("模块 '%s' 缺少 META 定义，已跳过", type_name)
            except Exception:
                logger.error("发现模块 '%s' 时出错:\n%s", type_name, traceback.format_exc())

        return result

    def render_module(self, type_name: str, config: dict, state: dict) -> dict:
        """
        调用指定模块的 render() 函数。

        Args:
            type_name: 模块类型名（即文件名去 .py）
            config:    模块配置
            state:     模块状态

        Returns:
            render() 的返回值（通常包含 html 字段）
        """
        module = self._get_module(type_name)
        if module is None:
            return {"error": f"模块 '{type_name}' 未找到或加载失败"}

        if not hasattr(module, "render"):
            return {"error": f"模块 '{type_name}' 未定义 render() 函数"}

        try:
            return module.render(config, state)
        except Exception:
            error_msg = traceback.format_exc()
            logger.error("模块 '%s' render() 出错:\n%s", type_name, error_msg)
            return {"error": f"模块 '{type_name}' 渲染出错", "detail": error_msg}

    def call_action(
        self,
        type_name: str,
        action: str,
        payload: dict,
        config: dict,
        state: dict,
    ) -> dict:
        """
        调用指定模块的 on_action() 函数。

        Args:
            type_name: 模块类型名
            action:    动作名称
            payload:   动作携带的数据
            config:    模块配置
            state:     模块状态

        Returns:
            on_action() 的返回值（通常包含更新后的 state）
        """
        module = self._get_module(type_name)
        if module is None:
            return {"error": f"模块 '{type_name}' 未找到或加载失败"}

        if not hasattr(module, "on_action"):
            return {"error": f"模块 '{type_name}' 未定义 on_action() 函数"}

        try:
            return module.on_action(action, payload, config, state)
        except Exception:
            error_msg = traceback.format_exc()
            logger.error(
                "模块 '%s' on_action('%s') 出错:\n%s", type_name, action, error_msg
            )
            return {"error": f"模块 '{type_name}' 处理动作出错", "detail": error_msg}

    # ------------------------------------------------------------------ #
    #  内部方法
    # ------------------------------------------------------------------ #

    def _get_module(self, type_name: str) -> Optional[Any]:
        """
        获取模块对象，必要时自动加载或热重载。
        """
        self._check_reload(type_name)
        return self._modules.get(type_name)

    def _check_reload(self, module_name: str) -> None:
        """
        检查模块文件是否有变动，如果 mtime 改变则重新加载。
        节流策略：1秒内重复检查直接跳过磁盘 stat 避开无用 I/O。

        Args:
            module_name: 模块名（不含 .py）
        """
        now = time.time()
        cached_mtime = self._mtimes.get(module_name)
        last_check = self._last_checks.get(module_name, 0.0)

        # 如果已有缓存且 1 秒内刚检查过，直接跳过 getmtime 磁盘 I/O
        if cached_mtime is not None and (now - last_check) < 1.0:
            return

        self._last_checks[module_name] = now
        filepath = os.path.join(self.modules_dir, f"{module_name}.py")

        if not os.path.isfile(filepath):
            # 文件不存在，如果之前加载过则清理
            if module_name in self._modules:
                logger.info("模块文件已删除，卸载模块: %s", module_name)
                del self._modules[module_name]
                del self._mtimes[module_name]
                del self._last_checks[module_name]
            return

        current_mtime = os.path.getmtime(filepath)

        if cached_mtime is None or current_mtime != cached_mtime:
            # 首次加载 或 文件已更新 → (重新)加载
            if cached_mtime is not None:
                logger.info("检测到模块文件变更，热重载: %s", module_name)
            self._load_module(module_name)

    def _load_module(self, module_name: str) -> None:
        """
        使用 importlib 动态加载（或重新加载）模块。

        Args:
            module_name: 模块名（不含 .py）
        """
        filepath = os.path.join(self.modules_dir, f"{module_name}.py")
        # 使用 "moduboard_modules.{name}" 作为模块的完全限定名，避免命名冲突
        qualified_name = f"moduboard_modules.{module_name}"

        try:
            spec = importlib.util.spec_from_file_location(qualified_name, filepath)
            if spec is None or spec.loader is None:
                logger.error("无法为 '%s' 创建模块规格", filepath)
                return

            module = importlib.util.module_from_spec(spec)
            # 注册到 sys.modules 以便模块内部的相对引用正常工作
            sys.modules[qualified_name] = module
            spec.loader.exec_module(module)

            self._modules[module_name] = module
            self._mtimes[module_name] = os.path.getmtime(filepath)
            logger.info("模块加载成功: %s (%s)", module_name, filepath)

        except Exception:
            logger.error("模块 '%s' 加载失败:\n%s", module_name, traceback.format_exc())
            # 加载失败不会让整个程序崩溃，只记录错误
            # 如果之前有旧版本，保留旧版本
            if module_name not in self._modules:
                # 完全没加载过，清除 mtime 让下次重试
                self._mtimes.pop(module_name, None)
