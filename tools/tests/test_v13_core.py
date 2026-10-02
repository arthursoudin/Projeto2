import os, tempfile, unittest
os.environ["JARVIS_STORE_DIR"] = tempfile.mkdtemp()
import orchestrator
import devices

class V13CoreTests(unittest.TestCase):
    def test_capabilities(self):
        c = orchestrator.capabilities()
        self.assertEqual(c["version"], "13.0.0")
        self.assertIn("multi_pc", c["future_ready"])

    def test_mission_lifecycle(self):
        m = orchestrator.create_mission("Teste V13", source="test")
        self.assertEqual(m["status"], "running")
        done = orchestrator.finish_mission(m["id"], True, {"ok": True})
        self.assertEqual(done["status"], "completed")

    def test_timeline(self):
        orchestrator.record_event("test_event", source="test")
        self.assertTrue(orchestrator.events())

    def test_device_registry(self):
        d = devices.register("test-device", "PC Teste", ["computer"], "13.0")
        self.assertEqual(d["status"], "online")
        self.assertEqual(devices.summary()["total"], 1)

if __name__ == "__main__":
    unittest.main()
