import importlib
import io
import unittest
from unittest.mock import Mock, patch
from contextlib import ExitStack, redirect_stdout, redirect_stderr


class LauncherTests(unittest.TestCase):
    def test_help_does_not_open_devices(self):
        try:
            launcher = importlib.import_module('run_dashboard')
        except ModuleNotFoundError:
            self.fail('Missing runnable local dashboard launcher')
        with patch('smart_gate_full.backend.runtime.MonitorRuntime.start') as start, redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as exc:
                launcher.main(['--help'])
            self.assertEqual(exc.exception.code, 0)
            start.assert_not_called()

    def test_invalid_duration_rejected_before_startup(self):
        import run_dashboard
        for value in ['nan', 'inf', '-1']:
            with self.subTest(value=value), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
                run_dashboard.main(['--seconds', value])
            self.assertEqual(exc.exception.code, 2)

    def _assert_report_failure_cleans_up(self, *, snapshot=None, snapshot_error=None,
                                        mkdir_error=None, write_error=None, stop_error=None):
        import run_dashboard
        runtime = Mock()
        runtime.snapshot.return_value = {} if snapshot is None else snapshot
        runtime.snapshot.side_effect = snapshot_error
        runtime.stop.side_effect = stop_error
        server = Mock()
        server.handle_request.side_effect = KeyboardInterrupt
        errors = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(patch('smart_gate_full.backend.runtime.MonitorRuntime', return_value=runtime))
            stack.enter_context(patch('smart_gate_full.backend.app.create_app', return_value=object()))
            stack.enter_context(patch('werkzeug.serving.make_server', return_value=server))
            stack.enter_context(patch.object(run_dashboard, 'lan_ip', return_value='127.0.0.1'))
            mkdir = stack.enter_context(patch.object(run_dashboard.Path, 'mkdir', side_effect=mkdir_error))
            write = stack.enter_context(patch.object(run_dashboard.Path, 'write_text', side_effect=write_error))
            stack.enter_context(redirect_stdout(io.StringIO()))
            stack.enter_context(redirect_stderr(errors))
            raised = None
            result = None
            try:
                result = run_dashboard.main(['--no-camera', '--report', 'mock-only/status.json'])
            except Exception as exc:
                raised = exc
            self.assertEqual(runtime.stop.call_count, 1, f'Cleanup skipped after {raised!r}')
            server.server_close.assert_called_once_with()
            self.assertIsNone(raised, f'Report/cleanup exception escaped: {raised!r}')
            self.assertEqual(result, 1)
            self.assertIn('[ERROR REPORT]', errors.getvalue())
            if stop_error is not None:
                self.assertIn('[ERROR STOP]', errors.getvalue())
            mkdir.assert_called_once_with(parents=True, exist_ok=True)
            # Path I/O above is mocked: no report directory or file is touched.
            if mkdir_error is not None or snapshot_error is not None or snapshot is not None:
                write.assert_not_called()
            else:
                write.assert_called_once()
            runtime.start.assert_called_once_with(camera_enabled=False, camera_index=0,
                                                  camera_backend='dshow', udp_port=5006)

    def test_report_write_failure_still_cleans_up(self):
        for stop_error in (None, RuntimeError('worker stop failed'), OSError('socket stop failed')):
            with self.subTest(stop_error=stop_error):
                self._assert_report_failure_cleans_up(
                    write_error=PermissionError('report write denied'), stop_error=stop_error)

    def test_report_mkdir_failure_still_cleans_up(self):
        self._assert_report_failure_cleans_up(mkdir_error=PermissionError('report directory denied'))

    def test_report_snapshot_failure_still_cleans_up(self):
        self._assert_report_failure_cleans_up(snapshot_error=RuntimeError('snapshot failed'))

    def test_report_serialization_failure_still_cleans_up(self):
        for value in (object(), float('nan')):
            with self.subTest(value=value):
                self._assert_report_failure_cleans_up(snapshot={'unserializable': value})


if __name__ == '__main__':
    unittest.main()
