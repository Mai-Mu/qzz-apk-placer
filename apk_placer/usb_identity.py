"""Read USB serials from the Windows PnP parent chain, without changing devices."""
import ctypes as ct
import os
import re


def usb_serials(interface_path: str) -> tuple[str, ...]:
    parts = interface_path.removeprefix("\\\\?\\").split("#")
    if os.name != "nt" or len(parts) < 3:
        return ()
    instance_id = "\\".join(parts[:3])
    config = ct.WinDLL("cfgmgr32")
    config.CM_Locate_DevNodeW.argtypes = [ct.POINTER(ct.c_ulong), ct.c_wchar_p, ct.c_ulong]
    config.CM_Get_Parent.argtypes = [ct.POINTER(ct.c_ulong), ct.c_ulong, ct.c_ulong]
    config.CM_Get_Device_IDW.argtypes = [ct.c_ulong, ct.c_wchar_p, ct.c_ulong, ct.c_ulong]
    node = ct.c_ulong()
    if config.CM_Locate_DevNodeW(ct.byref(node), instance_id, 0):
        return ()
    serials = []
    for _ in range(6):
        buffer = ct.create_unicode_buffer(2048)
        if config.CM_Get_Device_IDW(node, buffer, len(buffer), 0) == 0:
            device_id = buffer.value
            # Composite MI interfaces often use generated IDs. Only use the
            # physical USB device's non-generated serial as an ADB identity.
            if re.match(r"USB\\VID_[0-9A-F]{4}&PID_[0-9A-F]{4}\\", device_id, re.I):
                serial = device_id.rsplit("\\", 1)[-1]
                if "&" not in serial:
                    serials.append(serial)
        parent = ct.c_ulong()
        if config.CM_Get_Parent(ct.byref(parent), node, 0):
            break
        node = parent
    return tuple(dict.fromkeys(serials))
