import os
import unittest
from unittest.mock import patch

from jnpr.junos import Device
from jnpr.junos.exception import RpcError
from ncclient.manager import Manager, make_device_handler
from ncclient.transport import SSHSession


class TestGetJnuSatellitesInformation(unittest.TestCase):
    @patch("ncclient.manager.connect")
    def setUp(self, mock_connect):
        mock_connect.side_effect = self._mock_manager_setup
        self.dev = Device(
            host="1.1.1.1", user="rick", password="password123", gather_facts=False
        )
        self.dev.open()

    def _read_file(self, fname):
        from ncclient.xml_ import NCElement

        fpath = os.path.join(os.path.dirname(__file__), "rpc-reply", fname)
        with open(fpath) as f:
            foo = f.read()
        rpc_reply = NCElement(
            foo, self.dev._conn._device_handler.transform_reply()
        )._NCElement__doc[0]
        return rpc_reply

    def _mock_manager_setup(self, *args, **kwargs):
        if kwargs:
            device_params = kwargs["device_params"]
            device_handler = make_device_handler(device_params)
            session = SSHSession(device_handler)
            return Manager(session, device_handler)

    # -----------------------------------------------------------------------
    # helpers that map each RPC tag to the right fixture file
    # -----------------------------------------------------------------------

    def _mock_satellites_up(self, *args, **kwargs):
        """Two satellites, both up, full set of per-satellite RPCs."""
        if not args:
            return None
        tag = args[0].tag
        if tag == "get-jnu-satellites-information":
            return self._read_file("satellites_get-jnu-satellites-information.xml")
        # device-list kwarg tells us which satellite is being queried
        device_list = args[0].findtext("device-list") or ""
        if tag == "get-software-information":
            key = "one" if "satellite_one" in device_list else "two"
            return self._read_file(
                "satellites_{}_get-software-information.xml".format(key)
            )
        if tag == "get-route-engine-information":
            return self._read_file("satellites_get-route-engine-information.xml")
        if tag == "get-chassis-inventory":
            return self._read_file("satellites_get-chassis-inventory.xml")
        if tag == "get-virtual-chassis-information":
            return self._read_file("satellites_get-virtual-chassis-information.xml")
        return None

    def _mock_satellites_none(self, *args, **kwargs):
        if not args:
            return None
        if args[0].tag == "get-jnu-satellites-information":
            return self._read_file("satellites_none_get-jnu-satellites-information.xml")
        return None

    def _mock_satellites_down(self, *args, **kwargs):
        if not args:
            return None
        if args[0].tag == "get-jnu-satellites-information":
            return self._read_file("satellites_down_get-jnu-satellites-information.xml")
        return None

    def _mock_satellites_rpc_error(self, *args, **kwargs):
        if not args:
            return None
        if args[0].tag == "get-jnu-satellites-information":
            raise RpcError()
        return None

    # -----------------------------------------------------------------------
    # test cases
    # -----------------------------------------------------------------------

    @patch("jnpr.junos.Device.execute")
    def test_satellites_present(self, mock_execute):
        mock_execute.side_effect = self._mock_satellites_up
        self.assertTrue(self.dev.facts["jnu_satellite"])
        info = self.dev.facts["satellites_info"]
        self.assertIn("satellite_one", info)
        self.assertIn("satellite_two", info)

    @patch("jnpr.junos.Device.execute")
    def test_satellite_alive_status(self, mock_execute):
        mock_execute.side_effect = self._mock_satellites_up
        info = self.dev.facts["satellites_info"]
        self.assertEqual(info["satellite_one"]["alive"], "up")
        self.assertEqual(info["satellite_two"]["alive"], "up")

    @patch("jnpr.junos.Device.execute")
    def test_satellite_software_facts(self, mock_execute):
        mock_execute.side_effect = self._mock_satellites_up
        sat = self.dev.facts["satellites_info"]["satellite_one"]
        self.assertEqual(sat["hostname"], "r0_re0")
        self.assertEqual(sat["model"], "mx960")
        self.assertEqual(sat["version"], "26.3I20260309_1406_babud")
        self.assertEqual(sat["os_name"], "junos")

    @patch("jnpr.junos.Device.execute")
    def test_satellite_re_facts(self, mock_execute):
        mock_execute.side_effect = self._mock_satellites_up
        sat = self.dev.facts["satellites_info"]["satellite_one"]
        self.assertFalse(sat["2RE"])
        self.assertIsNotNone(sat["RE0"])
        self.assertEqual(sat["RE0"]["mastership_state"], "master")
        self.assertEqual(sat["RE0"]["status"], "OK")
        self.assertEqual(sat["RE0"]["model"], "RE-VMX")
        self.assertIsNone(sat["RE1"])
        self.assertEqual(sat["master"], "RE0")
        self.assertIsNotNone(sat["re_info"])
        self.assertIsNotNone(sat["re_master"])

    @patch("jnpr.junos.Device.execute")
    def test_satellite_chassis_inventory_facts(self, mock_execute):
        mock_execute.side_effect = self._mock_satellites_up
        sat = self.dev.facts["satellites_info"]["satellite_one"]
        self.assertEqual(sat["serialnumber"], "VM6A2F86A07D")

    @patch("jnpr.junos.Device.execute")
    def test_satellite_vc_not_capable(self, mock_execute):
        """Satellite returns rpc-error for VC — vc_capable must be False."""
        mock_execute.side_effect = self._mock_satellites_up
        sat = self.dev.facts["satellites_info"]["satellite_one"]
        self.assertFalse(sat["vc_capable"])
        self.assertIsNone(sat["vc_mode"])
        self.assertIsNone(sat["vc_fabric"])
        self.assertIsNone(sat["vc_master"])

    @patch("jnpr.junos.Device.execute")
    def test_no_satellites(self, mock_execute):
        """Empty satellite list — jnu_satellite must be False."""
        mock_execute.side_effect = self._mock_satellites_none
        self.assertFalse(self.dev.facts["jnu_satellite"])
        self.assertEqual(self.dev.facts["satellites_info"], {})

    @patch("jnpr.junos.Device.execute")
    def test_satellite_down_skips_detail_rpcs(self, mock_execute):
        """Down satellite — detail RPCs are not called, fields are None."""
        mock_execute.side_effect = self._mock_satellites_down
        self.assertTrue(self.dev.facts["jnu_satellite"])
        sat = self.dev.facts["satellites_info"]["satellite_one"]
        self.assertEqual(sat["alive"], "down")
        self.assertIsNone(sat["hostname"])
        self.assertIsNone(sat["serialnumber"])
        self.assertIsNone(sat["RE0"])
        self.assertFalse(sat["vc_capable"])

    @patch("jnpr.junos.Device.execute")
    def test_rpc_not_supported(self, mock_execute):
        """Device does not support JNU satellites RPC — no exception raised."""
        mock_execute.side_effect = self._mock_satellites_rpc_error
        self.assertFalse(self.dev.facts["jnu_satellite"])
        self.assertEqual(self.dev.facts["satellites_info"], {})


if __name__ == "__main__":
    unittest.main()
