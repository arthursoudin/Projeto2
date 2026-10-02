import devices

# V14.0 smoke tests: device catalog + stale status handling + targeted queue shape.
devices.store.save(devices.KEY, [])
item=devices.register("test-device-1", name="PC Teste", capabilities=["computer"], version="13.5.0", telemetry={"cpu_percent":12.5,"ram_em_uso_percent":44})
assert item["status"] == "online"
assert item["cpu_percent"] == 12.5
assert devices.summary()["online"] == 1
assert devices.get_device("test-device-1")["name"] == "PC Teste"
print("V14.0 tests: OK")
