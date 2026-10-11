"""Persistent, read-only OPC UA client backed by asyncua.

Flask handlers remain synchronous while every asyncua object lives on one
dedicated asyncio event loop. One OPC UA Subscription can contain many
MonitoredItems, which avoids consuming one server subscription per point.
"""

import asyncio
import base64
import os
import threading
import time
from collections import deque
from copy import deepcopy
from datetime import date, datetime
from typing import Any, Dict, List, Optional


class OpcUaRuntimeError(RuntimeError):
    """An OPC UA error safe to return to the workbench."""


def _timestamp(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        if getattr(value, "tzinfo", None):
            return value.astimezone().isoformat(timespec="milliseconds")
        return value.isoformat(timespec="milliseconds")
    return str(value)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"encoding": "base64", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return str(value)


def _status_text(status: Any) -> str:
    if status is None:
        return "Unknown"
    name = getattr(status, "name", None)
    if name:
        return str(name)
    text = str(status)
    if text.startswith("StatusCode(") and text.endswith(")"):
        return text[11:-1]
    return text


class _SubscriptionHandler:
    def __init__(self, owner: "OpcUaService") -> None:
        self.owner = owner

    def datachange_notification(self, node: Any, value: Any, data: Any) -> None:
        self.owner._on_datachange(node, value, data)

    def status_change_notification(self, status: Any) -> None:
        self.owner._on_status_change(status)


class OpcUaService:
    """Synchronous facade around one persistent asyncua Session."""

    def __init__(self) -> None:
        self._io_lock = threading.RLock()
        self._data_lock = threading.RLock()
        self._client: Any = None
        self._subscription: Any = None
        self._settings: Dict[str, Any] = {}
        self._subscription_config: Dict[str, Any] = {}
        self._requested_items: List[Dict[str, Any]] = []
        self._items: Dict[str, Dict[str, Any]] = {}
        self._logs = deque(maxlen=200)
        self._connected = False
        self._desired_running = False
        self._subscription_id: Optional[int] = None
        self._reconnect_count = 0
        self._last_error = ""
        self._sequence = 0
        self._supervisor_started = False

        self._loop = asyncio.new_event_loop()
        self._loop_ready = threading.Event()
        self._loop_thread = threading.Thread(
            target=self._run_loop,
            name="moduboard-opcua",
            daemon=True,
        )
        self._loop_thread.start()
        self._loop_ready.wait(timeout=5)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop_ready.set()
        self._loop.run_forever()

    def _call(self, coroutine: Any, timeout: float = 70.0) -> Any:
        if not self._loop_ready.is_set():
            raise OpcUaRuntimeError("OPC UA 后台事件循环未就绪")
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            return future.result(timeout=timeout)
        except Exception as exc:
            future.cancel()
            if isinstance(exc, OpcUaRuntimeError):
                raise
            raise OpcUaRuntimeError(str(exc) or exc.__class__.__name__) from exc

    def _log(self, level: str, message: str) -> None:
        with self._data_lock:
            self._logs.append({
                "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                "level": level,
                "message": message,
            })

    def _set_connection(self, connected: bool, error: str = "") -> None:
        with self._data_lock:
            self._connected = connected
            self._last_error = error
            self._sequence += 1

    @staticmethod
    def _validated_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
        normalized = deepcopy(settings)
        endpoint = str(normalized.get("endpoint", "")).strip()
        if not endpoint.lower().startswith("opc.tcp://"):
            raise OpcUaRuntimeError("Endpoint URL 必须以 opc.tcp:// 开头")
        try:
            timeout = float(normalized.get("timeout", 5) or 5)
        except (TypeError, ValueError) as exc:
            raise OpcUaRuntimeError("Timeout 必须是数字") from exc
        if not 0.1 <= timeout <= 60:
            raise OpcUaRuntimeError("Timeout 必须在 0.1～60 秒之间")
        normalized["endpoint"] = endpoint
        normalized["timeout"] = timeout

        authentication = str(normalized.get("authentication", "Anonymous"))
        if authentication == "Username / Password" and not str(normalized.get("username", "")).strip():
            raise OpcUaRuntimeError("Username / Password 模式需要 Username")

        mode = str(normalized.get("security_mode", "None"))
        policy = str(normalized.get("security_policy", "None"))
        if mode == "None" and policy != "None":
            raise OpcUaRuntimeError("Security Mode=None 时 Security Policy 必须为 None")
        if mode != "None":
            if policy == "None":
                raise OpcUaRuntimeError("Sign / SignAndEncrypt 需要非 None Security Policy")
            certificate = os.path.abspath(str(normalized.get("certificate", "")).strip())
            private_key = os.path.abspath(str(normalized.get("private_key", "")).strip())
            if not os.path.isfile(certificate) or not os.path.isfile(private_key):
                raise OpcUaRuntimeError("安全连接需要可访问的 Client Certificate 和 Private Key 文件")
            normalized["certificate"] = certificate
            normalized["private_key"] = private_key
        return normalized

    async def _new_client(self, settings: Dict[str, Any]) -> Any:
        try:
            from asyncua import Client
        except ImportError as exc:
            raise OpcUaRuntimeError("未安装 asyncua，请先安装 requirements.txt") from exc

        client = Client(settings["endpoint"], timeout=settings["timeout"])
        client.application_uri = str(settings.get("application_uri") or "urn:moduboard:industrial:client")
        if str(settings.get("authentication", "Anonymous")) == "Username / Password":
            client.set_user(str(settings.get("username", "")))
            client.set_password(str(settings.get("password", "")))
        mode = str(settings.get("security_mode", "None"))
        if mode != "None":
            await client.set_security_string(
                f"{settings['security_policy']},{mode},{settings['certificate']},{settings['private_key']}"
            )
        return client

    async def _disconnect_async(self) -> None:
        subscription, self._subscription = self._subscription, None
        self._subscription_id = None
        if subscription is not None:
            try:
                await subscription.delete()
            except Exception:
                pass
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def _connect_async(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        await self._disconnect_async()
        started = time.perf_counter()
        client = await self._new_client(settings)
        try:
            await client.connect()
            self._client = client
            self._set_connection(True)
            latency = round((time.perf_counter() - started) * 1000, 2)
            self._log("INFO", f"Session connected · {settings['endpoint']} · {latency} ms")
            return {"ok": True, "connected": True, "endpoint": settings["endpoint"], "latency_ms": latency}
        except Exception:
            try:
                await client.disconnect()
            except Exception:
                pass
            raise

    def connect(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        normalized = self._validated_settings(settings)
        with self._io_lock:
            self._desired_running = False
            self._settings = normalized
            try:
                return self._call(self._connect_async(normalized), normalized["timeout"] + 10)
            except Exception as exc:
                self._set_connection(False, str(exc))
                self._log("ERROR", f"Connect failed · {exc}")
                if isinstance(exc, OpcUaRuntimeError):
                    raise
                raise OpcUaRuntimeError(str(exc)) from exc

    def disconnect(self) -> Dict[str, Any]:
        with self._io_lock:
            self._desired_running = False
            self._call(self._disconnect_async(), 15)
            self._set_connection(False)
            self._log("INFO", "Session disconnected")
            return {"ok": True, "connected": False}

    def _require_client(self) -> Any:
        if self._client is None or not self._connected:
            raise OpcUaRuntimeError("OPC UA Session 尚未连接")
        return self._client

    async def _browse_async(self, node_id: str, limit: int) -> Dict[str, Any]:
        node = self._require_client().get_node(node_id or "i=85")
        parent_id = None
        try:
            parent = await node.get_parent()
            if parent is not None:
                parent_id = parent.nodeid.to_string()
        except Exception:
            pass
        children = []
        for child in (await node.get_children())[:max(1, min(limit, 1000))]:
            try:
                node_class = await child.read_node_class()
                browse_name = await child.read_browse_name()
                display_name = await child.read_display_name()
                item: Dict[str, Any] = {
                    "node_id": child.nodeid.to_string(),
                    "browse_name": str(browse_name.Name),
                    "display_name": str(display_name.Text or browse_name.Name),
                    "node_class": str(getattr(node_class, "name", node_class)),
                    "namespace_index": int(browse_name.NamespaceIndex),
                    "data_type": "",
                    "access_level": [],
                }
                if item["node_class"] == "Variable":
                    try:
                        variant_type = await child.read_data_type_as_variant_type()
                        item["data_type"] = str(getattr(variant_type, "name", variant_type))
                    except Exception as exc:
                        item["data_type"] = f"Unknown ({exc})"
                    try:
                        item["access_level"] = [entry.name for entry in await child.get_access_level()]
                    except Exception:
                        item["access_level"] = []
                children.append(item)
            except Exception as exc:
                self._log("WARN", f"Browse child skipped · {exc}")
        self._log("INFO", f"Browse {node_id} · {len(children)} references")
        return {"ok": True, "node_id": node.nodeid.to_string(), "parent_id": parent_id, "children": children}

    def browse(self, node_id: str = "i=85", limit: int = 200) -> Dict[str, Any]:
        with self._io_lock:
            try:
                return self._call(self._browse_async(node_id or "i=85", int(limit)))
            except Exception as exc:
                self._log("ERROR", f"Browse failed · {node_id} · {exc}")
                if isinstance(exc, OpcUaRuntimeError):
                    raise
                raise OpcUaRuntimeError(str(exc)) from exc

    def _data_value_payload(self, node_id: str, data_value: Any) -> Dict[str, Any]:
        variant = getattr(data_value, "Value", None)
        value = getattr(variant, "Value", None)
        variant_type = getattr(variant, "VariantType", None)
        return {
            "node_id": node_id,
            "value": _json_value(value),
            "data_type": str(getattr(variant_type, "name", variant_type or "")),
            "status": _status_text(getattr(data_value, "StatusCode", None)),
            "source_timestamp": _timestamp(getattr(data_value, "SourceTimestamp", None)),
            "server_timestamp": _timestamp(getattr(data_value, "ServerTimestamp", None)),
            "receive_timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        }

    async def _read_async(self, node_id: str) -> Dict[str, Any]:
        if not node_id.strip():
            raise OpcUaRuntimeError("NodeId 不能为空")
        node = self._require_client().get_node(node_id)
        return self._data_value_payload(node_id, await node.read_data_value())

    def read(self, node_id: str) -> Dict[str, Any]:
        with self._io_lock:
            return self._call(self._read_async(node_id))

    def write(self, node_id: str, value: Any, variant_type: str) -> Dict[str, Any]:
        raise OpcUaRuntimeError("真实设备模式为只读：OPC UA Write 已禁用")

    @staticmethod
    def _subscription_values(config: Dict[str, Any]) -> tuple[float, int, int, int]:
        try:
            publishing = float(config.get("publishing_interval", 1000))
            keepalive = int(config.get("keep_alive_count", 10))
            lifetime = int(config.get("lifetime_count", 60))
            priority = int(config.get("priority", 0))
        except (TypeError, ValueError) as exc:
            raise OpcUaRuntimeError("Subscription 参数格式不正确") from exc
        if publishing <= 0:
            raise OpcUaRuntimeError("Publishing Interval 必须大于 0")
        if keepalive < 1 or lifetime < keepalive * 3:
            raise OpcUaRuntimeError("Lifetime Count 必须至少为 KeepAlive Count 的 3 倍")
        if not 0 <= priority <= 255:
            raise OpcUaRuntimeError("Priority 必须在 0～255 之间")
        return publishing, keepalive, lifetime, priority

    async def _delete_subscription_async(self) -> None:
        subscription, self._subscription = self._subscription, None
        self._subscription_id = None
        if subscription is not None:
            try:
                await subscription.delete()
            except Exception:
                pass

    async def _start_subscription_async(self) -> Dict[str, Any]:
        from asyncua import ua

        client = self._require_client()
        await self._delete_subscription_async()
        publishing, keepalive, lifetime, priority = self._subscription_values(self._subscription_config)
        params = ua.CreateSubscriptionParameters()
        params.RequestedPublishingInterval = publishing
        params.RequestedLifetimeCount = lifetime
        params.RequestedMaxKeepAliveCount = keepalive
        params.MaxNotificationsPerPublish = max(1000, len(self._requested_items) * 4)
        params.PublishingEnabled = True
        params.Priority = priority
        subscription = await client.create_subscription(params, _SubscriptionHandler(self))

        normalized_items = []
        accepted = 0
        for requested in self._requested_items:
            node_id = str(requested.get("node_id", "")).strip()
            if not node_id:
                await subscription.delete()
                raise OpcUaRuntimeError("MonitoredItem 缺少 NodeId")
            node = client.get_node(node_id)
            try:
                sampling = max(0.0, float(requested.get("sampling_interval", 1000)))
                queue_size = max(1, int(requested.get("queue_size", 10)))
                deadband = max(0.0, float(requested.get("deadband", 0) or 0))
            except (TypeError, ValueError) as exc:
                await subscription.delete()
                raise OpcUaRuntimeError(f"MonitoredItem 参数不正确：{node_id}") from exc

            if deadband > 0:
                handle = await subscription.deadband_monitor(node, deadband, queuesize=queue_size)
                if isinstance(handle, int):
                    await subscription.modify_monitored_item(handle, sampling, queue_size)
            else:
                handle = await subscription.subscribe_data_change(
                    node,
                    queuesize=queue_size,
                    sampling_interval=sampling,
                )
            good = isinstance(handle, int) or (hasattr(handle, "is_good") and handle.is_good())
            item = {
                "name": str(requested.get("name") or node_id),
                "node_id": node_id,
                "data_type": str(requested.get("data_type") or ""),
                "critical": bool(requested.get("critical", False)),
                "sampling_interval": sampling,
                "queue_size": queue_size,
                "deadband": deadband,
                "discard_oldest": bool(requested.get("discard_oldest", True)),
                "value": None,
                "status": "Waiting" if good else _status_text(handle),
                "source_timestamp": None,
                "server_timestamp": None,
                "receive_timestamp": None,
                "server_handle": int(handle) if isinstance(handle, int) else None,
            }
            normalized_items.append(item)
            accepted += int(good)

        if accepted == 0:
            await subscription.delete()
            raise OpcUaRuntimeError("Server 拒绝了全部 MonitoredItem")
        self._subscription = subscription
        self._subscription_id = int(subscription.subscription_id)
        with self._data_lock:
            self._items = {item["node_id"]: item for item in normalized_items}
            self._sequence += 1
        self._log(
            "INFO",
            f"Subscription #{self._subscription_id} created · {accepted}/{len(self._requested_items)} MonitoredItems",
        )
        return {
            "ok": True,
            "subscription_id": self._subscription_id,
            "accepted": accepted,
            "requested": len(self._requested_items),
        }

    def start_subscription(self, config: Dict[str, Any], items: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not items:
            raise OpcUaRuntimeError("Subscription 至少需要一个 MonitoredItem")
        with self._io_lock:
            self._subscription_config = deepcopy(config)
            self._requested_items = deepcopy(items)
            self._desired_running = True
            try:
                result = self._call(self._start_subscription_async())
                self._ensure_supervisor()
                return result
            except Exception as exc:
                self._desired_running = False
                self._log("ERROR", f"Subscription failed · {exc}")
                if isinstance(exc, OpcUaRuntimeError):
                    raise
                raise OpcUaRuntimeError(str(exc)) from exc

    async def _health_check_async(self) -> None:
        client = self._require_client()
        await client.get_node("i=2258").read_value()

    def _ensure_supervisor(self) -> None:
        if self._supervisor_started:
            return
        self._supervisor_started = True
        threading.Thread(target=self._supervisor_loop, name="opcua-reconnect", daemon=True).start()

    def _supervisor_loop(self) -> None:
        backoff = 1.0
        while True:
            time.sleep(3.0)
            if not self._desired_running:
                backoff = 1.0
                continue
            try:
                with self._io_lock:
                    self._call(self._health_check_async(), 10)
                backoff = 1.0
            except Exception as exc:
                self._set_connection(False, str(exc))
                self._log("WARN", f"Connection lost · {exc} · reconnecting")
                time.sleep(backoff)
                try:
                    with self._io_lock:
                        if not self._desired_running:
                            continue
                        self._call(self._connect_async(self._settings), self._settings.get("timeout", 5) + 10)
                        self._call(self._start_subscription_async())
                        self._reconnect_count += 1
                        self._log("INFO", f"Session and Subscription recreated · reconnect #{self._reconnect_count}")
                    backoff = 1.0
                except Exception as reconnect_error:
                    self._set_connection(False, str(reconnect_error))
                    self._log("ERROR", f"Reconnect failed · {reconnect_error}")
                    backoff = min(backoff * 2, 30.0)

    async def _stop_subscription_async(self) -> Optional[int]:
        subscription_id = self._subscription_id
        await self._delete_subscription_async()
        return subscription_id

    def stop_subscription(self) -> Dict[str, Any]:
        with self._io_lock:
            self._desired_running = False
            subscription_id = self._call(self._stop_subscription_async(), 15)
            self._log("INFO", f"Subscription #{subscription_id or '-'} stopped")
            with self._data_lock:
                self._sequence += 1
            return {"ok": True, "subscription_id": subscription_id}

    def _on_datachange(self, node: Any, value: Any, data: Any) -> None:
        try:
            node_id = node.nodeid.to_string()
            data_value = data.monitored_item.Value
            update = self._data_value_payload(node_id, data_value)
            with self._data_lock:
                item = self._items.get(node_id)
                if item is None:
                    return
                item.update(update)
                self._sequence += 1
        except Exception as exc:
            self._log("ERROR", f"DataChange callback error · {exc}")

    def _on_status_change(self, status: Any) -> None:
        text = _status_text(status)
        self._log("WARN", f"Subscription status · {text}")
        with self._data_lock:
            self._last_error = text
            self._sequence += 1

    def snapshot(self, since: int = 0) -> Dict[str, Any]:
        with self._data_lock:
            items = list(deepcopy(self._items).values()) if self._sequence != since else []
            return {
                "ok": True,
                "connected": self._connected,
                "running": self._desired_running and self._subscription_id is not None,
                "subscription_id": self._subscription_id,
                "sequence": self._sequence,
                "reconnect_count": self._reconnect_count,
                "last_error": self._last_error,
                "items": items,
                "logs": list(self._logs)[-30:],
            }


opcua_service = OpcUaService()
