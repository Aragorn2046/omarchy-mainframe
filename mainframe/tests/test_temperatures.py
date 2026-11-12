import ast
import importlib.util
import ctypes
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch


COLLECT = Path(__file__).resolve().parents[1] / 'collect.py'
spec = importlib.util.spec_from_file_location('temperature_collector', COLLECT)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

WSL = '6.6.0-microsoft-standard-WSL2'
LINUX = '6.6.0-linux'


def registry_entry(index, label, shown, raw):
    return (f'    Sensor{index}    REG_SZ    Processor\r\n'
            f'    Label{index}    REG_SZ    {label}\r\n'
            f'    Value{index}    REG_SZ    {shown}\r\n'
            f'    ValueRaw{index}    REG_SZ    {raw}\r\n')


class MacTemperatureTests(unittest.TestCase):
    def test_cpu_sensor_selection(self):
        choose = collector.select_mac_cpu_temperature
        self.assertEqual(choose({'PMU tdie1': 49, 'PMU2 tdie3': 71,
                                 'pACC MTR Temp Sensor0': 100}), 71)
        self.assertEqual(choose({'pACC MTR Temp Sensor0': 52,
                                 'eACC MTR Temp Sensor1': 62,
                                 'ACC MTR Temp Sensor2': 58}), 62)
        self.assertIsNone(choose({'GPU MTR Temp Sensor': 60,
                                  'GPU ACC MTR Temp Sensor': 70, 'other': 40}))
        self.assertEqual(choose({'tdie1': float('nan'), 'tdie2': 151,
                                 'tdie3': -21, 'tdie4': float('inf'),
                                 'pACC MTR Temp Sensor': 50}), 50)
        self.assertIsNone(choose({'tdie': float('nan'), 'tdie2': 151}))

    def test_host_metadata_with_and_without_value(self):
        for value, expected in [(53.5, {'package_c': 53.5, 'disk_c': None}),
                                (None, collector.temps_na())]:
            sample = {'gpu': {}, 'temps': {}, 'errors': {'temps': 'unavailable', 'cpu': 'error'}}
            with patch.object(collector.sys, 'platform', 'darwin'):
                result = collector.apply_host_meta(sample, '', 'darwin', '24', mac_reader=lambda: value, local=True)
            self.assertEqual(result['temps'], expected)
            self.assertTrue(result['gpu']['na'])
            self.assertEqual(result['errors'], {'cpu': 'error'})

    def test_reader_caches_failed_initialization(self):
        now = [0]
        reader = collector.MacTemperatureReader(clock=lambda: now[0])
        cf, io = Mock(), Mock()
        io.IOHIDEventSystemClientCreate.side_effect = [None, 10, 20]
        cf.CFStringCreateWithCString.side_effect = [11, RuntimeError('unavailable'), 21, 22]
        cf.CFNumberCreate.side_effect = [23, 24]
        cf.CFDictionaryCreate.return_value = 25
        io.IOHIDEventSystemClientCopyServices.return_value = None
        byte_type = Mock()
        with patch.object(collector.sys, 'platform', 'darwin'), \
             patch.object(collector.os, 'uname', return_value=Mock(machine='arm64')), \
             patch.object(collector.ctypes, 'CDLL', side_effect=[cf, io] * 3), \
             patch.object(collector.ctypes, 'c_byte', byte_type), \
             patch.object(collector.ctypes, 'addressof', return_value=1), \
             patch.object(collector.atexit, 'register'):
            for instant, attempts in ((0, 1), (59, 1), (60, 2), (119, 2), (120, 3), (200, 3)):
                now[0] = instant
                self.assertEqual(reader.read(), {})
                self.assertEqual(io.IOHIDEventSystemClientCreate.call_count, attempts)
            self.assertEqual(io.IOHIDEventSystemClientCreate.call_count, 3)
            self.assertEqual(reader.client, 20)
            self.assertEqual([call.args[0] for call in cf.CFRelease.call_args_list],
                             [11, 10, 25, 24, 23, 22, 21])
            self.assertEqual(io.IOHIDServiceClientCopyEvent.argtypes,
                             [ctypes.c_void_p, ctypes.c_int64, ctypes.c_int32, ctypes.c_int64])
            self.assertEqual(io.IOHIDServiceClientCopyEvent.restype, ctypes.c_void_p)
            reader.close()
            self.assertEqual(cf.CFRelease.call_args.args, (20,))

    def test_reader_reuses_client_and_releases_copied_objects(self):
        now = [0]
        reader = collector.MacTemperatureReader(clock=lambda: now[0])
        cf, io = Mock(), Mock()
        reader.cf, reader.io, reader.client = cf, io, 1
        io.IOHIDEventSystemClientCopyServices.return_value = 2
        cf.CFStringCreateWithCString.return_value = 3
        cf.CFArrayGetCount.return_value = 1
        cf.CFArrayGetValueAtIndex.return_value = 4
        io.IOHIDServiceClientCopyProperty.return_value = 5
        cf.CFGetTypeID.return_value = cf.CFStringGetTypeID.return_value = 6
        cf.CFStringGetLength.return_value = 9
        cf.CFStringGetMaximumSizeForEncoding.return_value = 20
        def get_string(_name, buffer, _size, _encoding):
            buffer.value = b'PMU tdie1'
            return True
        cf.CFStringGetCString.side_effect = get_string
        io.IOHIDServiceClientCopyEvent.return_value = 7
        io.IOHIDEventGetFloatValue.return_value = 53.5
        self.assertEqual(reader.read(), {'PMU tdie1': 53.5})
        now[0] = 1.99
        self.assertEqual(reader.read(), {'PMU tdie1': 53.5})
        self.assertEqual(io.IOHIDEventSystemClientCopyServices.call_count, 1)
        now[0] = 2
        self.assertEqual(reader.read(), {'PMU tdie1': 53.5})
        self.assertEqual(io.IOHIDEventSystemClientCopyServices.call_count, 2)
        self.assertEqual([call.args[0] for call in cf.CFRelease.call_args_list],
                         [7, 5, 3, 2, 7, 5, 3, 2])
        reader.close()
        self.assertEqual(cf.CFRelease.call_args.args, (1,))

    def test_non_mac_does_not_read_local_mac_sensors(self):
        probe = Mock(return_value=55)
        with patch.object(collector.sys, 'platform', 'linux'):
            collector.apply_host_meta({'temps': {}}, '', 'darwin', '24', mac_reader=probe, local=True)
        probe.assert_not_called()

    def test_nonlocal_mac_preserves_valid_temperatures_without_reading(self):
        probe = Mock(return_value=99)
        for value in (55, -20, 150):
            original = {'package_c': value, 'disk_c': 30, 'na': True, 'extra': 1}
            sample = {'temps': original}
            with patch.object(collector.sys, 'platform', 'darwin'):
                collector.apply_host_meta(sample, '', 'darwin', '24', mac_reader=probe)
            self.assertEqual(sample['temps'], {'package_c': value, 'disk_c': None, 'extra': 1})
            self.assertEqual(original['disk_c'], 30)
        probe.assert_not_called()

    def test_nonlocal_mac_rejects_invalid_temperatures(self):
        for value in (None, True, '55', -21, 151, float('nan'), float('inf')):
            with self.subTest(value=value):
                sample = {'temps': {'package_c': value}}
                collector.apply_host_meta(sample, '', 'darwin', '24')
                self.assertEqual(sample['temps'], collector.temps_na())

    def test_local_sample_producers_mark_samples_local(self):
        tree = ast.parse(COLLECT.read_text())
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == 'apply_host_meta'
                 and any(isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
                         and arg.func.id == 'host_name' for arg in node.args)]
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertTrue(any(kw.arg == 'local' and isinstance(kw.value, ast.Constant)
                                and kw.value.value is True for kw in call.keywords))

    def test_duplicate_sensor_names_keep_highest_value(self):
        for values in ([72, 48], [48, 72]):
            with self.subTest(values=values):
                reader = collector.MacTemperatureReader()
                cf, io = Mock(), Mock()
                reader.cf, reader.io, reader.client = cf, io, 1
                io.IOHIDEventSystemClientCopyServices.return_value = 2
                cf.CFStringCreateWithCString.return_value = 3
                cf.CFArrayGetCount.return_value = 2
                cf.CFArrayGetValueAtIndex.side_effect = [4, 5]
                io.IOHIDServiceClientCopyProperty.return_value = 6
                cf.CFGetTypeID.return_value = cf.CFStringGetTypeID.return_value = 8
                cf.CFStringGetLength.return_value = 9
                cf.CFStringGetMaximumSizeForEncoding.return_value = 20
                def get_string(_name, buffer, _size, _encoding):
                    buffer.value = b'PMU tdie1'
                    return True
                cf.CFStringGetCString.side_effect = get_string
                io.IOHIDServiceClientCopyEvent.return_value = 9
                io.IOHIDEventGetFloatValue.side_effect = values
                self.assertEqual(reader.read(), {'PMU tdie1': 72})

    def test_reader_replaces_invalid_name_without_losing_other_sensors(self):
        reader = collector.MacTemperatureReader()
        cf, io = Mock(), Mock()
        reader.cf, reader.io, reader.client = cf, io, 1
        io.IOHIDEventSystemClientCopyServices.return_value = 2
        cf.CFStringCreateWithCString.return_value = 3
        cf.CFArrayGetCount.return_value = 2
        cf.CFArrayGetValueAtIndex.side_effect = [4, 5]
        io.IOHIDServiceClientCopyProperty.side_effect = [6, 7]
        cf.CFGetTypeID.return_value = cf.CFStringGetTypeID.return_value = 8
        cf.CFStringGetLength.return_value = 10
        cf.CFStringGetMaximumSizeForEncoding.return_value = 20
        def get_string(name, buffer, _size, _encoding):
            buffer.value = b'bad\xffname' if name == 6 else b'PMU tdie1'
            return True
        cf.CFStringGetCString.side_effect = get_string
        io.IOHIDServiceClientCopyEvent.return_value = 9
        io.IOHIDEventGetFloatValue.return_value = 53.5
        sensors = reader.read()
        self.assertEqual(sensors, {'bad\ufffdname': 53.5, 'PMU tdie1': 53.5})
        self.assertEqual(collector.select_mac_cpu_temperature(sensors), 53.5)


class WslTemperatureTests(unittest.TestCase):
    def test_large_lines_and_output_are_bounded(self):
        for label, shown in (('x' + ' ' * 200000 + 'y', '50 C'),
                             ('CPU', '9' * 200000)):
            data = (registry_entry(1, label, shown, '50')
                    + registry_entry(2, 'Core Max', '48 C', '48')).encode()
            start = time.monotonic()
            self.assertEqual(collector.parse_hwinfo_temperatures(data), {'Core Max': 48.0})
            self.assertLess(time.monotonic() - start, 1.0)
        data = (b' ' * (256 * 1024) + b'\n' +
                registry_entry(1, 'CPU', '50 C', '50').encode())
        self.assertEqual(collector.parse_hwinfo_temperatures(data), {})

    def test_utf16_and_priority(self):
        data = ('HKEY_CURRENT_USER\\Software\\HWiNFO64\\VSB\r\n'
                + registry_entry(1, 'CPU', '35 °C', '35.5')
                + registry_entry(2, 'CPU (Tctl/Tdie)', '49 °C', '49.2')
                + registry_entry(3, 'cpu package', '52 °C', '52.4')).encode('utf-16')
        sensors = collector.parse_hwinfo_temperatures(data)
        self.assertEqual(collector.select_hwinfo_cpu_temperature(sensors), 52.4)
        self.assertEqual(len(sensors), 3)

    def test_utf8_crlf_rejects_non_temperature_and_bad_values(self):
        data = (registry_entry(1, 'CPU Package', '95 %', '95')
                + registry_entry(2, 'CPU (Tctl/Tdie)', '160 °C', '160')
                + registry_entry(3, 'CPU Die (average)', '45 C', 'nan')
                + registry_entry(4, 'Core Max', '48 C', '48.1')).encode('utf-8')
        sensors = collector.parse_hwinfo_temperatures(data)
        self.assertEqual(sensors, {'Core Max': 48.1})
        self.assertEqual(collector.select_hwinfo_cpu_temperature(sensors), 48.1)
        self.assertEqual(collector.parse_hwinfo_temperatures(b''), {})
        self.assertEqual(collector.parse_hwinfo_temperatures(b'ERROR: key missing\r\n'), {})

    def test_codepages_and_decimal_comma(self):
        text = (registry_entry(1, 'CPU Package', '52 °C', '52,4')
                + registry_entry(2, 'Core Max', '48 C', '48.1')
                + registry_entry(3, 'CPU', '40 MHz', '40')
                + registry_entry(4, 'Fan', '50 RPM', '50')
                + registry_entry(5, 'Power', '5 W', '5')
                + registry_entry(6, 'Voltage', '1 V', '1')
                + registry_entry(7, 'Bad', 'C', '4')
                + registry_entry(8, 'Bad comma', '52 C', '52,4,1')
                + registry_entry(9, 'Bad mixed', '52 C', '52,4.1'))
        for encoding in ('cp437', 'cp1252', 'utf-8', 'utf-8-sig', 'utf-16', 'utf-16le'):
            with self.subTest(encoding=encoding):
                self.assertEqual(collector.parse_hwinfo_temperatures(text.encode(encoding)),
                                 {'CPU Package': 52.4, 'Core Max': 48.1})
        self.assertEqual(collector.parse_hwinfo_temperatures(text.encode('utf-16le') + b'\xff'),
                         {'CPU Package': 52.4, 'Core Max': 48.1})

    def test_cache_and_failure_backoff(self):
        now = [0.0]
        output = registry_entry(1, 'CPU Package', '52 °C', '52.4').encode()
        scripts = iter([f'import sys; sys.stdout.buffer.write({output!r})',
                        f'import sys; sys.stdout.buffer.write({output!r}); sys.exit(1)',
                        f'import sys; sys.stdout.buffer.write({output!r})'])
        runner = Mock(side_effect=lambda _args, **kwargs:
                      subprocess.Popen([sys.executable, '-c', next(scripts)], **kwargs))
        reader = collector.WslTemperatureReader(clock=lambda: now[0], runner=runner)
        self.assertEqual(reader.read(WSL), {'CPU Package': 52.4})
        now[0] = 4.99
        self.assertEqual(reader.read(WSL), {'CPU Package': 52.4})
        self.assertEqual(runner.call_count, 1)
        now[0] = 5
        self.assertEqual(reader.read(WSL), {})
        now[0] = 64.99
        self.assertEqual(reader.read(WSL), {})
        self.assertEqual(runner.call_count, 2)
        now[0] = 65
        self.assertEqual(reader.read(WSL), {'CPU Package': 52.4})
        self.assertEqual(runner.call_count, 3)
        args, kwargs = runner.call_args
        self.assertEqual(args[0], ['/mnt/c/Windows/System32/reg.exe', 'query',
                                  r'HKCU\Software\HWiNFO64\VSB'])
        self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
        self.assertEqual(kwargs['stdout'], subprocess.PIPE)
        self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)
        self.assertEqual(set(kwargs), {'stdin', 'stdout', 'stderr'})

    def test_empty_and_missing_key_back_off(self):
        now = [0]
        scripts = iter(['pass', 'import sys; sys.exit(1)'])
        runner = Mock(side_effect=lambda _args, **kwargs:
                      subprocess.Popen([sys.executable, '-c', next(scripts)], **kwargs))
        reader = collector.WslTemperatureReader(clock=lambda: now[0], runner=runner)
        self.assertEqual(reader.read(WSL), {})
        now[0] = 59
        self.assertEqual(reader.read(WSL), {})
        self.assertEqual(runner.call_count, 1)
        now[0] = 60
        self.assertEqual(reader.read(WSL), {})
        now[0] = 119
        self.assertEqual(reader.read(WSL), {})
        self.assertEqual(runner.call_count, 2)

    def test_over_limit_output_fails_and_backs_off(self):
        now = [0]
        output = registry_entry(1, 'CPU', '50 C', '50').encode()
        script = f'import sys; sys.stdout.buffer.write({output!r} + b" " * (256 * 1024))'
        children = []
        def run(_args, **kwargs):
            child = subprocess.Popen([sys.executable, '-c', script], **kwargs)
            children.append(child)
            return child
        runner = Mock(side_effect=run)
        reader = collector.WslTemperatureReader(clock=lambda: now[0], runner=runner)
        self.assertEqual(reader.read(WSL), {})
        self.assertIsNotNone(children[0].returncode)
        now[0] = 59
        self.assertEqual(reader.read(WSL), {})
        self.assertEqual(runner.call_count, 1)
        now[0] = 60
        self.assertEqual(reader.read(WSL), {})
        self.assertEqual(runner.call_count, 2)

    def test_timeout_kills_and_reaps_child(self):
        children = []
        def run(_args, **kwargs):
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'], **kwargs)
            child.kill = Mock(wraps=child.kill)
            child.wait = Mock(wraps=child.wait)
            children.append(child)
            return child
        reader = collector.WslTemperatureReader(runner=run)
        with patch.object(collector, '_HWiNFO_TIMEOUT', 0.1):
            self.assertEqual(reader.read(WSL), {})
        children[0].kill.assert_called_once()
        children[0].wait.assert_called()
        self.assertIsNotNone(children[0].returncode)

    def test_reader_exception_kills_and_reaps_child(self):
        children = []
        def run(_args, **kwargs):
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'], **kwargs)
            children.append(child)
            return child
        reader = collector.WslTemperatureReader(runner=run)
        with patch.object(collector.select, 'select', side_effect=OSError('read failed')):
            self.assertEqual(reader.read(WSL), {})
        self.assertIsNotNone(children[0].returncode)
        self.assertTrue(children[0].stdout.closed)

    def test_no_cpu_label_backs_off_but_preserves_diagnostics(self):
        now = [0]
        output = registry_entry(1, 'GPU', '50 C', '50').encode()
        script = f'import sys; sys.stdout.buffer.write({output!r})'
        runner = Mock(side_effect=lambda _args, **kwargs:
                      subprocess.Popen([sys.executable, '-c', script], **kwargs))
        reader = collector.WslTemperatureReader(clock=lambda: now[0], runner=runner)
        self.assertEqual(reader.read(WSL), {'GPU': 50})
        now[0] = 59
        self.assertEqual(reader.read(WSL), {'GPU': 50})
        self.assertEqual(runner.call_count, 1)
        now[0] = 60
        self.assertEqual(reader.read(WSL), {'GPU': 50})
        self.assertEqual(runner.call_count, 2)

    def test_non_wsl_never_runs_and_linux_value_wins(self):
        runner = Mock()
        reader = collector.WslTemperatureReader(runner=runner)
        self.assertEqual(reader.read(LINUX), {})
        runner.assert_not_called()
        probe = Mock(return_value=55)
        sample = {'temps': {'package_c': 42, 'disk_c': None}}
        with patch.object(collector, 'kernel_release', return_value=WSL):
            collector.apply_host_meta(sample, '', 'linux', WSL, wsl_reader=probe, local=True)
            self.assertEqual(sample['temps']['package_c'], 42)
            probe.assert_not_called()
            sample['temps']['package_c'] = None
            collector.apply_host_meta(sample, '', 'linux', WSL, wsl_reader=probe, local=True)
            self.assertEqual(sample['temps']['package_c'], 55)
            probe.assert_called_once_with(WSL)
            probe.reset_mock()
            sample['temps']['package_c'] = None
            collector.apply_host_meta(sample, '', 'linux', LINUX, wsl_reader=probe, local=True)
            probe.assert_not_called()

    def test_wsl_result_shape_and_local_guard(self):
        probe = Mock(return_value=55)
        for disk in (None, 36):
            original = dict(collector.temps_na(), disk_c=disk, extra=17)
            sample = {'temps': original,
                      'errors': {'temps': 'unavailable', 'cpu': 'error'}}
            with patch.object(collector, 'kernel_release', return_value=WSL):
                collector.apply_host_meta(sample, '', 'linux', WSL, wsl_reader=probe, local=True)
            self.assertEqual(sample['temps'], {'package_c': 55, 'disk_c': disk, 'extra': 17})
            self.assertIsNot(sample['temps'], original)
            self.assertEqual(sample['errors'], {'cpu': 'error'})
        probe.reset_mock()
        sample = {'temps': collector.temps_na(), 'errors': {'temps': 'unavailable'}}
        with patch.object(collector, 'kernel_release', return_value=LINUX):
            collector.apply_host_meta(sample, '', 'linux', WSL, wsl_reader=probe, local=True)
        probe.assert_not_called()
        self.assertEqual(sample['temps'], collector.temps_na())
        self.assertEqual(sample['errors'], {'temps': 'unavailable'})
        with patch.object(collector, 'kernel_release', return_value=WSL):
            collector.apply_host_meta(sample, '', 'linux', WSL, wsl_reader=lambda _: None, local=True)
        self.assertEqual(sample['temps'], collector.temps_na())
        self.assertEqual(sample['errors'], {'temps': 'unavailable'})

    def test_nonlocal_wsl_keeps_temperatures_without_reading(self):
        probe = Mock(return_value=55)
        temps = {'package_c': None, 'disk_c': 36, 'na': True}
        sample = {'temps': temps}
        with patch.object(collector, 'kernel_release', return_value=WSL):
            collector.apply_host_meta(sample, '', 'linux', WSL, wsl_reader=probe)
        self.assertIs(sample['temps'], temps)
        self.assertEqual(sample['temps'], {'package_c': None, 'disk_c': 36, 'na': True})
        probe.assert_not_called()

    def test_diagnostic_on_linux(self):
        with patch.object(collector, 'host_os_name', return_value='linux'), \
             patch.object(collector, 'kernel_release', return_value=LINUX), \
             patch.object(sys, 'argv', ['collect.py', '--temp-sensors']), \
             patch('sys.stdout', new_callable=__import__('io').StringIO) as output:
            self.assertEqual(collector._main(), 0)
            self.assertEqual(json.loads(output.getvalue()), {})


if __name__ == '__main__':
    unittest.main()
