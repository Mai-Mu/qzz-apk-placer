"""Synchronous Windows Portable Devices adapter. All COM objects stay on one thread.

Property keys: Microsoft win32metadata PortableDevice.h. Use raw COM methods for
allocated strings/arrays so CoTaskMemFree can release every returned allocation.
"""
from __future__ import annotations

import ctypes as ct
from pathlib import Path
from typing import Callable

import comtypes
import comtypes.client
from comtypes import GUID

from .core import Device
from .usb_identity import usb_serials

API = comtypes.client.GetModule("PortableDeviceApi.dll")
TYPES = comtypes.client.GetModule("PortableDeviceTypes.dll")
OLE = ct.OleDLL("ole32")
OLE.CoTaskMemFree.argtypes = [ct.c_void_p]
OLE.CoTaskMemFree.restype = None


def key(guid: str, pid: int):
    return API._tagpropertykey(GUID(guid), pid)


OBJECT = "{EF6B490D-5CD8-437A-AFFC-DA8B60EE4A3C}"
CLIENT = "{204D9F0C-2292-4080-9F42-40664E70F859}"
PARENT, NAME = key(OBJECT, 3), key(OBJECT, 4)
FORMAT, CONTENT = key(OBJECT, 6), key(OBJECT, 7)
SIZE, FILENAME = key(OBJECT, 11), key(OBJECT, 12)
STORAGE_TYPE = key("{01A3057A-74D6-4E80-BEA7-DC4C212CE50A}", 2)
CATEGORY = key("{8F052D93-ABCA-4FC5-A5AC-B01DF4DBE598}", 2)
SERIAL = key("{26D4979A-E643-4626-9E2B-736DC0C92FDC}", 9)
FOLDER = GUID("{27E2E392-A111-48E0-AB0C-E17705A05F85}")
GENERIC_FILE = GUID("{0085E0A6-8D34-45D7-BC5C-447E59C73D48}")
UNSPECIFIED = GUID("{30000000-AE6C-4804-98BA-C5B746965FE7}")
STORAGE_CATEGORY = GUID("{23F05BBC-15DE-4C2A-A55B-A9AF5CE412EF}")


def raw(obj, interface: str, method: str):
    return getattr(obj, f"_{interface}__com_{method}")


def new_values():
    return comtypes.client.CreateObject(TYPES.PortableDeviceValues, interface=API.IPortableDeviceValues)


def string_value(values, property_key) -> str:
    result = ct.c_wchar_p()
    try:
        raw(values, "IPortableDeviceValues", "GetStringValue")(ct.byref(property_key), ct.byref(result))
        return result.value or ""
    finally:
        if ct.cast(result, ct.c_void_p).value:
            OLE.CoTaskMemFree(ct.cast(result, ct.c_void_p))


def optional(call, default=None):
    try:
        return call()
    except comtypes.COMError:
        return default


class WpdBackend:
    def __init__(self):
        self.manager = comtypes.client.CreateObject(API.PortableDeviceManager, interface=API.IPortableDeviceManager)

    def list_devices(self) -> list[Device]:
        self.manager.RefreshDeviceList()
        count = ct.c_ulong()
        get = raw(self.manager, "IPortableDeviceManager", "GetDevices")
        get(None, ct.byref(count))
        if not count.value:
            return []
        pointers = (ct.c_void_p * count.value)()
        try:
            get(ct.cast(pointers, ct.POINTER(ct.c_wchar_p)), ct.byref(count))
            result = []
            for pointer in pointers:
                if not pointer:
                    continue
                device_id = ct.wstring_at(pointer)
                # Android USB MTP endpoints have USB/VID identifiers. Exclude
                # virtual network devices and software portable-device providers.
                if "USB" not in device_id.upper() or "VID_" not in device_id.upper():
                    continue
                buffer = ct.create_unicode_buffer(512)
                length = ct.c_ulong(len(buffer))
                try:
                    raw(self.manager, "IPortableDeviceManager", "GetDeviceFriendlyName")(
                        device_id, ct.cast(buffer, ct.POINTER(ct.c_ushort)), ct.byref(length))
                    name = buffer.value
                except comtypes.COMError:
                    name = "PDA / Android 设备"
                result.append(Device(device_id, name, usb_serials(device_id)))
            return result
        finally:
            for pointer in pointers:
                if pointer:
                    OLE.CoTaskMemFree(pointer)

    def open(self, device: Device):
        return WpdSession(device)


class WpdSession:
    def __init__(self, device: Device):
        self.device = comtypes.client.CreateObject(API.PortableDevice, interface=API.IPortableDevice)
        info = new_values()
        info.SetStringValue(key(CLIENT, 2), "Qzz APK Placer")
        info.SetUnsignedIntegerValue(key(CLIENT, 3), 1)
        self.device.Open(device.id, info)
        self.content = self.device.Content()
        self.properties = self.content.Properties()
        self.keys = comtypes.client.CreateObject(TYPES.PortableDeviceKeyCollection,
                                                 interface=API.IPortableDeviceKeyCollection)
        for item in (NAME, FILENAME, CONTENT, SIZE, STORAGE_TYPE, CATEGORY):
            self.keys.Add(item)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.keys = self.properties = self.content = None
        self.device.Close()
        self.device = None

    def children(self, parent: str) -> list[str]:
        enumerator = self.content.EnumObjects(0, parent, None)
        result = []
        while True:
            fetched = ct.c_ulong()
            pointer = ct.c_wchar_p()
            try:
                raw(enumerator, "IEnumPortableDeviceObjectIDs", "Next")(1, ct.byref(pointer), ct.byref(fetched))
                if not fetched.value:
                    break
                result.append(pointer.value)
            finally:
                if ct.cast(pointer, ct.c_void_p).value:
                    OLE.CoTaskMemFree(ct.cast(pointer, ct.c_void_p))
        return result

    def values(self, object_id: str):
        return self.properties.GetValues(object_id, self.keys)

    def serial_number(self) -> str:
        keys = comtypes.client.CreateObject(TYPES.PortableDeviceKeyCollection,
                                            interface=API.IPortableDeviceKeyCollection)
        keys.Add(SERIAL)
        return optional(lambda: string_value(self.properties.GetValues("DEVICE", keys), SERIAL), "").strip()

    def name(self, values):
        return optional(lambda: string_value(values, FILENAME), "") or string_value(values, NAME)

    def download_folder(self) -> str:
        internal, named = [], []
        for object_id in self.children("DEVICE"):
            values = self.values(object_id)
            if optional(lambda: values.GetGuidValue(CATEGORY)) != STORAGE_CATEGORY:
                continue
            storage_type = optional(lambda: values.GetUnsignedIntegerValue(STORAGE_TYPE), 0)
            name = self.name(values).casefold()
            if storage_type == 3:
                internal.append(object_id)
            elif storage_type == 0 and any(word in name for word in ("internal", "内部", "内置", "shared")):
                named.append(object_id)
        candidates = internal or named
        if len(candidates) != 1:
            raise RuntimeError("尚未识别到唯一的内部存储，请解锁 PDA 并选择 USB 文件传输模式")
        storage = candidates[0]
        for object_id in self.children(storage):
            values = self.values(object_id)
            if self.name(values).casefold() == "download":
                if values.GetGuidValue(CONTENT) != FOLDER:
                    raise RuntimeError("内部存储中的 Download 不是文件夹")
                return object_id
        values = new_values()
        values.SetStringValue(PARENT, storage)
        values.SetStringValue(NAME, "Download")
        values.SetStringValue(FILENAME, "Download")
        values.SetGuidValue(CONTENT, FOLDER)
        result = ct.c_wchar_p()
        try:
            raw(self.content, "IPortableDeviceContent", "CreateObjectWithPropertiesOnly")(values, ct.byref(result))
            return result.value
        finally:
            if ct.cast(result, ct.c_void_p).value:
                OLE.CoTaskMemFree(ct.cast(result, ct.c_void_p))

    def matching(self, folder: str, name: str) -> list[str]:
        result = []
        for object_id in self.children(folder):
            values = self.values(object_id)
            if self.name(values).casefold() == name.casefold():
                if optional(lambda: values.GetGuidValue(CONTENT)) == FOLDER:
                    raise RuntimeError("目标位置有与 APK 同名的文件夹，已停止传输")
                result.append(object_id)
        return result

    def delete(self, object_id: str):
        collection = comtypes.client.CreateObject(TYPES.PortableDevicePropVariantCollection,
                                                  interface=API.IPortableDevicePropVariantCollection)
        variant = API.tag_inner_PROPVARIANT()
        variant.vt = 31  # VT_LPWSTR; Add copies the borrowed string.
        union = getattr(variant, variant._fields_[-1][0])
        union.pwszVal = object_id
        collection.Add(variant)
        results = ct.POINTER(API.IPortableDevicePropVariantCollection)()
        raw(self.content, "IPortableDeviceContent", "Delete")(0, collection, ct.byref(results))

    def transfer(self, source: Path, progress: Callable[[int, int], None], cancelled: Callable[[], bool]):
        folder = self.download_folder()
        total = source.stat().st_size
        if cancelled():
            raise InterruptedError("传输已取消")
        for object_id in self.matching(folder, source.name):
            self.delete(object_id)
        if self.matching(folder, source.name):
            raise RuntimeError("无法覆盖设备上的同名 APK，请检查设备是否允许删除文件")
        values = new_values()
        values.SetStringValue(PARENT, folder)
        values.SetStringValue(NAME, source.stem)
        values.SetStringValue(FILENAME, source.name)
        values.SetUnsignedLargeIntegerValue(SIZE, total)
        values.SetGuidValue(CONTENT, GENERIC_FILE)
        values.SetGuidValue(FORMAT, UNSPECIFIED)
        stream = ct.POINTER(API.IStream)()
        optimal = ct.c_ulong()
        cookie = ct.c_wchar_p()
        committed = False
        try:
            raw(self.content, "IPortableDeviceContent", "CreateObjectWithPropertiesAndData")(
                values, ct.byref(stream), ct.byref(optimal), ct.byref(cookie))
            chunk_size = min(max(optimal.value, 64 * 1024), 1024 * 1024)
            sent = 0
            with source.open("rb") as file:
                while chunk := file.read(chunk_size):
                    if cancelled():
                        raise InterruptedError("传输已取消")
                    buffer = (ct.c_ubyte * len(chunk)).from_buffer_copy(chunk)
                    written = int(stream.RemoteWrite(buffer, len(chunk)))
                    if written != len(chunk):
                        raise OSError("设备未完整接收数据，请重新连接后重试")
                    sent += written
                    progress(sent, total)
            stream.Commit(0)
            committed = True
            matches = self.matching(folder, source.name)
            if len(matches) != 1 or self.values(matches[0]).GetUnsignedLargeIntegerValue(SIZE) != total:
                raise OSError("目标文件大小校验失败，请重新传输")
        finally:
            if stream and not committed:
                optional(lambda: stream.Revert())
            if ct.cast(cookie, ct.c_void_p).value:
                OLE.CoTaskMemFree(ct.cast(cookie, ct.c_void_p))
