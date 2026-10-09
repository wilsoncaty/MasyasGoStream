import threading
import unittest
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest
from gostream_license import LicenseClient, LicenseConfig, LicenseError
from gostream_runtime import StreamRuntime
import gostream_auth


class LicensingTests(unittest.TestCase):
    def test_config_requires_stable_identity_and_https(self):
        values = dict(api_url='https://license.example', deployment_url='https://app.streamlit.app', installation_id='a'*48)
        self.assertEqual(LicenseConfig.from_mapping(values).installation_id, 'a'*48)
        for change in ({'installation_id': ''}, {'api_url': 'http://example.com'}, {'deployment_url': 'https://app.test/path'}):
            with self.assertRaises(LicenseError):
                LicenseConfig.from_mapping({**values, **change})

    def test_missing_secrets_blocks_dashboard_without_exception(self):
        app = AppTest.from_string('from gostream_auth import require_owner\nrequire_owner()\nimport streamlit as st\nst.button("PRIVATE START")').run()
        self.assertEqual(len(app.exception), 0)
        self.assertFalse(any(button.label == 'PRIVATE START' for button in app.button))
        self.assertTrue(any('Siapkan' in title.value for title in app.subheader))

    def test_login_screen_blocks_dashboard(self):
        app = AppTest.from_string('from gostream_auth import require_owner\nrequire_owner()\nimport streamlit as st\nst.button("PRIVATE START")')
        app.secrets['gostream_license'] = dict(api_url='https://license.example', deployment_url='https://app.streamlit.app', installation_id='a'*48)
        app.run()
        self.assertEqual(len(app.exception), 0)
        self.assertFalse(any(button.label == 'PRIVATE START' for button in app.button))
        self.assertTrue(any(button.label == 'Masuk' for button in app.button))

    def test_start_always_checks_server_and_preserves_running_process(self):
        running = StreamRuntime()
        running.process = Mock()
        running.process.poll.return_value = None
        client = Mock()
        fake_st = Mock(session_state={'_gs_owner_token': 'token', '_gs_owner_status': {'can_start': True}})
        with patch.object(gostream_auth, 'st', fake_st):
            client.check.return_value = {'can_start': False, 'status': 'expired'}
            self.assertFalse(gostream_auth.can_start_stream(client))
            client.check.assert_called_once_with('token')
            client.check.side_effect = LicenseError('service_unavailable')
            self.assertFalse(gostream_auth.can_start_stream(client))
            self.assertTrue(running.is_running())
            running.process.terminate.assert_not_called()
            client.check.side_effect = None
            client.check.return_value = {'can_start': True}
            self.assertTrue(gostream_auth.can_start_stream(client))

    def test_invalid_session_clears_owner(self):
        fake_st = Mock(session_state={'_gs_owner_token': 'token', '_gs_owner_status': {'can_start': True}})
        with patch.object(gostream_auth, 'st', fake_st):
            client = Mock()
            client.check.side_effect = LicenseError('login_required', 401)
            self.assertFalse(gostream_auth.can_start_stream(client))
            self.assertNotIn('_gs_owner_token', fake_st.session_state)

    def test_malformed_check_response_fails_closed(self):
        client = LicenseClient(None)
        for response in ({}, {'license': {}}, {'license': {'can_start': 'true'}}):
            with patch.object(client, 'request', return_value=response), self.assertRaises(LicenseError):
                client.check('token')

    def test_two_browsers_cannot_launch_two_processes(self):
        runtime = StreamRuntime()
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def target():
            entered.set()
            release.wait(3)
            finished.set()
        try:
            self.assertTrue(runtime.launch(target, ()))
            self.assertTrue(entered.wait(2))
            self.assertFalse(runtime.launch(target, ()))
        finally:
            release.set()
        self.assertTrue(finished.wait(2))


if __name__ == '__main__':
    unittest.main()
