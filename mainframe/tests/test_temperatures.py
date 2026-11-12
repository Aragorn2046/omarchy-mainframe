import importlib.util
import json
from pathlib import Path
import subprocess
import sys
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
            result = collector.apply_host_meta(sample, '', 'darwin', '24', mac_reader=lambda: value)
            self.assertEqual(result['temps'], expected)
            self.assertTrue(result['gpu']['na'])
            self.assertEqual(result['errors'], {'cpu': 'error'})

    def test_reader_caches_failed_initialization(self):
        clock = Mock(side_effect=[0, 1, 2])
        reader = collector.MacTemperatureReader(clock=clock)
        reader._initialize = Mock(side_effect=RuntimeError('unavailable'))
        self.assertEqual(reader.read(), {})
        self.assertEqual(reader.read(), {})
        self.assertEqual(reader.read(), {})
        self.assertEqual(reader._initialize.call_count, 2)

    def test_reader_reuses_client_and_releases_copied_objects(self):
        now = [0]
        reader = collector.MacTemperatureReader(clock=lambda: now[0])
        cf, io = Mock(), Mock()
        reader.cf, reader.io, reader.client, reader.initialized = cf, io, 1, True
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


class WslTemperatureTests(unittest.TestCase):
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

    def test_cache_and_failure_backoff(self):
        now = [0.0]
        output = registry_entry(1, 'CPU Package', '52 °C', '52.4').encode()
        runner = Mock(side_effect=[subprocess.CompletedProcess([], 0, output),
                                   subprocess.TimeoutExpired('reg.exe', 2),
                                   subprocess.CompletedProcess([], 0, output)])
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
        self.assertEqual(kwargs['timeout'], 2)

    def test_empty_and_missing_key_back_off(self):
        now = [0]
        runner = Mock(side_effect=[subprocess.CompletedProcess([], 0, b''),
                                   subprocess.CalledProcessError(1, 'reg.exe')])
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

    def test_non_wsl_never_runs_and_linux_value_wins(self):
        runner = Mock()
        reader = collector.WslTemperatureReader(runner=runner)
        self.assertEqual(reader.read(LINUX), {})
        runner.assert_not_called()
        probe = Mock(return_value=55)
        sample = {'temps': {'package_c': 42, 'disk_c': None}}
        collector.apply_host_meta(sample, '', 'linux', WSL, wsl_reader=probe)
        self.assertEqual(sample['temps']['package_c'], 42)
        probe.assert_not_called()
        sample['temps']['package_c'] = None
        collector.apply_host_meta(sample, '', 'linux', WSL, wsl_reader=probe)
        self.assertEqual(sample['temps']['package_c'], 55)
        probe.assert_called_once_with(WSL)
        probe.reset_mock()
        sample['temps']['package_c'] = None
        collector.apply_host_meta(sample, '', 'linux', LINUX, wsl_reader=probe)
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
