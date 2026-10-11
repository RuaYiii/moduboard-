# ModuBoard 工业通信工作台：现场使用单页指南

## 出发前必须做

1. 将整个 `moduboard` 目录复制到测试电脑，必须包含 `offline/wheels`。
2. 测试电脑安装 **Windows x64 Python 3.9**。协议运行库不需要联网。
3. 双击 `INSTALL_OFFLINE.cmd`，等待显示 `Result: READY FOR FIELD CONNECTION`。
4. 双击 `PROTOCOL_SELF_TEST.cmd`。必须同时看到 Modbus TCP 与 OPC UA 的 `[OK]`，最后显示 `[PASS]`。
5. 双击 `START_INDUSTRIAL.cmd`，浏览器会打开 `http://127.0.0.1:5000/industrial`。

页面默认是 **真实设备**。只有显式切换到“离线模拟”时才会产生模拟数据。

## OPC UA Subscription 现场步骤

1. 确认测试电脑与 Server 在同一可达网络；Windows 可先运行：

   ```powershell
   Test-NetConnection 10.1.1.20 -Port 4840
   ```

2. 填写完整 `Endpoint URL`，包括 Server 要求的路径，例如 `opc.tcp://10.1.1.20:4840/UA/Server`。
3. 按 Server 配置选择 `Security Mode`、`Security Policy` 与 `Authentication`。
4. Username 模式填写账号密码；Sign/SignAndEncrypt 模式填写客户端证书和私钥的绝对路径。首次连接通常还需要在 OPC Server 端信任客户端证书。
5. 点击“连接 Server”。连接成功后会自动从 `Objects (i=85)` Browse。
6. 双击 Object 继续向下浏览；勾选多个 Variable，点击“添加选中测点”。也可以手动录入准确 NodeId。
7. 为每个 MonitoredItem 设置 `Sampling`、`Queue`、`Deadband`；设置 Subscription 的 `Publishing`、`KeepAlive`、`Lifetime`、`Priority`。
8. 点击“开始订阅”。表格应显示真实的 `Value`、`StatusCode`、`SourceTimestamp`、`ServerTimestamp` 与 `ReceiveTime`。
9. 点击“保存配置”，浏览器会在本机保存当前连接与点表；密码不会被保存。

如果网络断开或 Server 重启，后台会按 1～30 秒退避自动重连，并重建 Session、Subscription 和 MonitoredItems。连接状态中的 `R1/R2` 表示已重连次数。

## Modbus TCP / RTU 现场步骤

1. 选择 Transport：TCP 填 IP/Port；RTU 填 COM、Baud、Parity、Stop Bits。RTU 串口一次只能被一个程序占用。
2. 明确填写 `Unit ID`、Function、Address Mode、Address 与 Quantity。
3. `40001` 形式的厂家地址必须选择 `4xxxx Reference`；如果厂家给的是 PDU offset，则选择 `Raw / Zero Based`。
4. Register 读取选择正确的 Data Type 和 Byte/Word Order。结果会同时显示 Raw Bytes、TX PDU、RX PDU、协议 Offset 和 Latency。
5. 真实设备模式只开放 FC01/02/03/04 读取。FC05/06/0F/10 只能切换到“离线模拟”后演练，避免现场误写。

## 现场故障判断

- `Connection refused`：目标 IP 可达，但端口未监听或被防火墙拒绝。
- `TCP timeout`：路由/VLAN/防火墙/地址错误，或设备没有响应。
- `Serial timeout`：COM 或串口参数、站号错误，或 RS-485 A/B 接反。
- `CRC error / Incomplete frame`：串口干扰、波特率/校验位错误或线路问题。
- `Modbus Exception 02`：地址或 Address Mode 不正确。
- OPC `BadNodeIdUnknown`：NodeId 错误或 Namespace Index 已变化，应重新 Browse。
- OPC `BadUserAccessDenied`：账号、证书信任或节点权限不满足。
- OPC 有 Value 但 Status 为 Bad/Uncertain：通信已经成立，问题在 Server 数据质量，不能把它当普通空值处理。

## 已知边界

- 真实支持：Modbus TCP、RTU over TCP、Modbus RTU 的 FC01/02/03/04，以及 OPC UA Session/Browse/Read、多测点 Subscription 与自动重连。
- 真实 Modbus Write 与 OPC UA Write 都已在服务端阻断；现场版本保持只读。
- OPC DA 仍未实现；它需要 Windows COM/DCOM 专用后端。
- 离线包包含应用运行库，但不包含特定 USB-RS485 转换器的 Windows 驱动；出发前必须确认转换器在设备管理器中正常出现 COM 口。
- 当前 Python 3.9 兼容后端支持 None、Basic128Rsa15、Basic256、Basic256Sha256、Aes128_Sha256_RsaOaep 与 Aes256_Sha256_RsaPss。
