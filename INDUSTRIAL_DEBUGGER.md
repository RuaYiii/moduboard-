# 工业协议调试器模板

## 定位

首版是 ModuBoard 内的安全、极简工业协议工作台。看板界面拆分为“工业通信请求”和“工业数据解析器”两张可独立拖动、缩放的模块卡片；全屏界面则按协议采用不同交互：Modbus 使用请求流程，OPC UA 使用 Subscription Builder。全部继承 ModuBoard 日间/夜间主题变量。默认只执行模拟通信，不会向真实设备发送读写指令。

启动 ModuBoard 后，可加载 `industrial_lab` 工作台，或从模块面板添加“工业协议调试器”。全屏工作台路径为 `/industrial`，单模块预览路径为 `/preview/industrial_debugger`。

## 当前项目审计

| 层 | 原项目位置 | 审计结论 |
|---|---|---|
| UI | `static/`、模块返回的 HTML | 无限画布、模块容器和动作转发可复用 |
| Module / Application | `modules/`、`module_loader.py` | 具有热加载和结构化错误边界，可增量接入 |
| Modbus | 无 | 未实现；不能假定 FC03、Float32 或 Big Endian |
| OPC | 无 | 未实现；需要区分 UA 与 DA |
| Data Model | 各模块自由字典 | 工业协议需要独立 Enum / dataclass 模型 |
| Worker | 无通用协议 Worker | 接真实 SDK 时必须新增可取消的后台任务 |
| Log | `log_store.py`、模块内状态 | 系统日志可复用；协议 TX/RX 需要保留在模块状态 |
| Config | `configs/*.json` | 工作台配置可复用；设备 Profile 后续应独立建模 |

## 已实现能力

| 能力 | 状态 |
|---|---|
| 协议族 → 传输/版本 → 操作级联选取 | 已实现 |
| Modbus TCP / RTU 参数模板 | 已实现 |
| FC01/02/03/04/05/06/0F/10 选择与数据区联动 | 已实现 |
| Raw / One Based / 3xxxx / 4xxxx 地址换算 | 已实现并有测试 |
| Bool、Bit、BitField、整数、浮点、String、HEX | 已实现离线解析 |
| ABCD / BADC / CDAB / DCBA | 已实现并有测试 |
| Scale / Offset / Unit | 已实现 |
| 原始字节、解析结果、地址映射、操作日志 | 已实现 |
| OPC UA Session、地址空间筛选与多 MonitoredItem Subscription | 已实现全屏模拟工作台 |
| Publishing / KeepAlive / Lifetime / Priority | 已实现配置及约束校验 |
| 每个 MonitoredItem 的 Sampling / Queue / Deadband | 已实现独立配置 |
| 关键测点标记与 Subscription Profile 本地保存 | 已实现，作为 Mini BMS 点表基础 |
| 真实 Modbus TCP / RTU over TCP / RTU（FC01/02/03/04） | 已实现，只读 |
| 真实 OPC UA Session / Browse / Subscription | 已实现 |
| OPC UA 自动重连并重建 Subscription | 已实现 |
| 断网环境离线安装与协议自测 | 已实现 |
| Polling、重连、点表导入、日志导出 | 后续增量 |
| OPC DA | 仅展示独立后端占位 |

## 代码边界

```text
modules/industrial_debugger.py       连接、请求、地址与简要日志
modules/industrial_decoder.py        独立原始数据解析卡片
            ↓
industrial_protocol/models.py        Enum / dataclass domain model
industrial_protocol/addressing.py    explicit address conversion
industrial_protocol/decoder.py       protocol-independent decoder
            ↓
industrial_protocol/modbus_service.py  PyModbus real read service
industrial_protocol/opcua_service.py   asyncua Session / Subscription worker
industrial_protocol/service.py         simulator backend boundary
            ↓
Real services / SimulatorBackend     explicit runtime selection
```

通信 SDK 不直接导入 UI 模块。真实 I/O 由独立 Service 执行，OPC UA 对象固定运行在专用 asyncio event loop，回调只更新线程安全缓存，再由 UI 轮询结构化状态。

## 增量路线

1. 增加 Modbus 点表轮询、CSV 导入、连续地址批量优化和日志导出。
2. 如需写控制，另建有角色权限、二次确认和审计日志的操作面板；现场调试版继续只读。
3. 为要求 AES Security Policy 的环境升级独立 Python 运行时与 OPC UA SDK。
4. 增加版本化的 Mini BMS Profile、报警规则、趋势与只读应急大屏。
5. 最后单独实现 Windows OPC DA Backend，避免与 UA SDK 耦合。

## Mini BMS 演进边界

当前只沉淀 Mini BMS 所需的“关键测点清单”，不在调试工具中提前堆入完整 BMS 功能。后续建议沿用现有 Subscription Profile，逐步增加：设备与区域分组、报警等级/延时/抑制、断线质量与数据新鲜度、历史趋势、应急只读大屏，以及主 BMS 失效时的独立连接配置。

调试层和运行层需要保持分离：调试工作台允许快速改 Subscription；Mini BMS 运行态使用已发布、版本化且只读优先的 Profile，控制写入必须独立授权和审计。

## 安全约束

- UI 必须持续显示地址模式及换算后的 PDU Offset。
- Raw Data、功能码、Unit ID、耗时和错误不得丢弃。
- 现场版本在 UI 与服务端双重阻断 FC05/06/0F/10 和 OPC Write。
- 网络、串口及订阅回调不得阻塞 UI 线程。
- 底层协议栈交给成熟 SDK，项目只负责配置、编排、解析和透明日志。
