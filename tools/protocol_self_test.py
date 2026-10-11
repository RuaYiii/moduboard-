"""Local integration test for the installed Modbus and OPC UA stacks."""

import asyncio
import sys
import threading
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_modbus() -> None:
    from pymodbus.datastore import (
        ModbusSlaveContext,
        ModbusSequentialDataBlock,
        ModbusServerContext,
    )
    from pymodbus.server import StartTcpServer
    from industrial_protocol.modbus_service import RealModbusService

    store = ModbusSlaveContext(
        di=ModbusSequentialDataBlock(0, [False] * 100),
        co=ModbusSequentialDataBlock(0, [False] * 100),
        hr=ModbusSequentialDataBlock(0, [0x0000, 0x435C] + [0] * 98),
        ir=ModbusSequentialDataBlock(0, [0] * 100),
        zero_mode=True,
    )
    context = ModbusServerContext(slaves={1: store}, single=False)
    threading.Thread(
        target=StartTcpServer,
        kwargs={"context": context, "address": ("127.0.0.1", 15020)},
        daemon=True,
    ).start()
    time.sleep(0.5)
    result = RealModbusService().execute({
        "transport": "modbus_tcp", "host": "127.0.0.1", "port": "15020",
        "unit_id": "1", "operation": "3", "address_mode": "raw", "address": "0",
        "quantity": "2", "data_type": "float32", "byte_order": "CDAB",
        "timeout": "2", "retries": "0",
    })
    assert result["decoded_value"] == 220.0, result
    print(f"[OK] Modbus TCP FC03 · raw={result['raw_bytes']} · value={result['decoded_value']} · {result['latency_ms']} ms")


def _run_opc_server(holder: dict, ready: threading.Event, stop: threading.Event) -> None:
    async def serve() -> None:
        from asyncua import Server

        server = Server()
        await server.init()
        server.set_endpoint("opc.tcp://127.0.0.1:48419/moduboard/self-test/")
        index = await server.register_namespace("urn:moduboard:self-test")
        bms = await server.nodes.objects.add_object(index, "BMS")
        voltage = await bms.add_variable(index, "VoltageA", 220.0)
        alarm = await bms.add_variable(index, "WaterLeakAlarm", False)
        holder.update({"loop": asyncio.get_running_loop(), "voltage": voltage, "alarm": alarm})
        await server.start()
        ready.set()
        try:
            while not stop.is_set():
                await asyncio.sleep(0.05)
        finally:
            await server.stop()

    asyncio.run(serve())


def test_opcua() -> None:
    from industrial_protocol.opcua_service import OpcUaService

    holder: dict = {}
    ready = threading.Event()
    stop = threading.Event()
    server_thread = threading.Thread(target=_run_opc_server, args=(holder, ready, stop), daemon=True)
    server_thread.start()
    if not ready.wait(8):
        raise RuntimeError("OPC UA self-test server failed to start")

    service = OpcUaService()
    try:
        service.connect({
            "endpoint": "opc.tcp://127.0.0.1:48419/moduboard/self-test/",
            "security_mode": "None", "security_policy": "None",
            "authentication": "Anonymous", "timeout": 3,
        })
        objects = service.browse("i=85")["children"]
        bms_node = next(item for item in objects if item["display_name"] == "BMS")
        variables = service.browse(bms_node["node_id"])["children"]
        items = [
            {"name": item["display_name"], "node_id": item["node_id"], "data_type": item["data_type"],
             "sampling_interval": 100, "queue_size": 10, "deadband": 0, "critical": True}
            for item in variables
        ]
        created = service.start_subscription(
            {"publishing_interval": 100, "keep_alive_count": 10, "lifetime_count": 60, "priority": 0},
            items,
        )
        asyncio.run_coroutine_threadsafe(holder["voltage"].write_value(231.25), holder["loop"]).result(5)
        asyncio.run_coroutine_threadsafe(holder["alarm"].write_value(True), holder["loop"]).result(5)
        time.sleep(0.6)
        snapshot = service.snapshot()
        values = {item["name"]: item["value"] for item in snapshot["items"]}
        assert values == {"VoltageA": 231.25, "WaterLeakAlarm": True}, values
        print(f"[OK] OPC UA Browse + Subscription #{created['subscription_id']} · 2 DataChange notifications")
        service.stop_subscription()
        service.disconnect()
    finally:
        stop.set()
        server_thread.join(timeout=5)


def main() -> int:
    print("ModuBoard protocol self-test (local only; no field device access)")
    test_modbus()
    test_opcua()
    print("[PASS] Real protocol stacks are operational.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
