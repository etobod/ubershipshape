"""The ``device_id`` query warning of skills/ush-advice/scripts/advice.py (plan 009, M2):
more shapes than test_fault.py, and clean data that must never warn.

Every device id, GUID, url and query is invented.
"""

import unittest

from .fakes import AdviceTestCase

DEVICE_IDS = (
    r"USB\VID_1234&PID_5678\5&2A3B4C5D&0&1",
    r"HID\VID_1234&PID_5678&MI_00\7&1A2B3C4D&0&0000",
    r"PCI\VEN_8086&DEV_1234&SUBSYS_00000000&REV_01\3&1A2B3C4D&0&A0",
    r"USB\VID_1234&PID_5678\0123456789AB",
    r"\\?\USB#VID_1234&PID_5678#5&2a3b4c5d&0&1#{a5dcbf10-6530-11d2-901f-00c04fb951ed}",
    r"BTHENUM\{0000110b-0000-1000-8000-00805f9b34fb}_LOCALMFG&0002\7&1A2B3C4D&0&0",
    "https://search.example/s?q=USB%5CVID_1234%26PID_5678%5C5%262A3B4C5D%260%261",
)

CLEAN = (
    "CM_PROB_FAILED_POST_START Windows 11 USB hub",
    "dwm.exe 0xc00001ad Windows 11 25H2",
    r"USB\VID_1234&PID_5678 driver Windows 11",
    r"USB\VID_1234&PID_5678&REV_0100",
    r"HKLM\SYSTEM\CurrentControlSet\Control\Class\{4d36e972-e325-11ce-bfc1-08002be10318}\0001",
    "https://learn.microsoft.com/windows-hardware/drivers/install/guid-devinterface-usb-hub",
    ("https://learn.microsoft.com/en-us/windows-hardware/drivers/install/"
     "{f18a0e88-c30c-11d0-8815-00a0c906bed8}/overview"),
    ("https://learn.microsoft.com/en-us/windows-hardware/drivers/install/"
     "%7Bf18a0e88-c30c-11d0-8815-00a0c906bed8%7D#remarks"),
    ("https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/"
     "usb-device-descriptors#vid_and_pid"),
    ("https://support.microsoft.com/en-us/windows/"
     "invented-fix-usb-hub-errors-0c1a2b3d-1234-5678-9abc-def012345678"),
    ("https://learn.microsoft.com/en-us/answers/questions/123456/"
     "invented-dwm-exe-0xc00001ad#answers"),
    # A GUID in the path or query, then a fragment holding ``&``: no instance id.
    ("https://learn.microsoft.com/en-us/windows-hardware/drivers/install/"
     "%7Bf18a0e88-c30c-11d0-8815-00a0c906bed8%7D/overview#a&b"),
    ("https://learn.microsoft.com/en-us/windows-hardware/drivers/install/"
     "{f18a0e88-c30c-11d0-8815-00a0c906bed8}/overview%23a%26b"),
    "https://x.example/p?id={f18a0e88-c30c-11d0-8815-00a0c906bed8}&x=1#top&y",
    ("https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/"
     "usb-device-descriptors?view=vid_1234/x#a&b"),
)


def finding(query, url="https://learn.microsoft.com/windows-hardware/drivers/invented"):
    return {"id": "w1", "kind": "fault", "query": query, "url": url}


class TestDeviceIdShapes(AdviceTestCase):
    def reasons(self, item):
        warnings = self.advice.query_warnings([item], {}, [])
        return [w["reason"] for w in warnings]

    def test_device_id_shapes_warn(self):
        for value in DEVICE_IDS:
            with self.subTest(f"query {value!r}"):
                self.assertEqual(self.reasons(finding(f"code 10 {value}")), ["device_id"])
            if value.startswith("https://"):
                with self.subTest(f"url {value!r}"):
                    self.assertEqual(self.reasons(finding(None, url=value)), ["device_id"])

    def test_clean_data_no_device_id(self):
        for value in CLEAN:
            if value.startswith("https://"):
                item = finding(None, url=value)
            else:
                item = finding(value)
            with self.subTest(value):
                self.assertEqual(self.reasons(item), [])

    def test_warning_never_carries_the_text(self):
        not_checked = []
        warnings = self.advice.query_warnings([finding(DEVICE_IDS[0])], {}, not_checked)
        self.assertEqual(warnings, [{"finding_id": "w1", "reason": "device_id"}])
        for item in not_checked:
            self.assertNotIn("5&2A3B4C5D", str(item))


if __name__ == "__main__":
    unittest.main()
