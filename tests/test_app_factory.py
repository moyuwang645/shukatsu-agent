import unittest
from unittest.mock import patch

from app import create_app, start_background_services


class ApplicationFactoryTests(unittest.TestCase):
    def test_create_app_does_not_start_background_services(self):
        with patch('scheduler.init_scheduler') as init_scheduler:
            flask_app = create_app(initialize_database=False)

        self.assertIsNotNone(flask_app)
        init_scheduler.assert_not_called()

    def test_api_http_errors_are_json(self):
        flask_app = create_app(initialize_database=False)
        response = flask_app.test_client().get('/api/does-not-exist')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()['error_code'], 'NOT_FOUND')
        self.assertFalse(response.get_json()['ok'])

    def test_unexpected_api_errors_are_json(self):
        flask_app = create_app(initialize_database=False)

        @flask_app.get('/api/test/unexpected-error')
        def unexpected_error():
            raise RuntimeError('sensitive implementation detail')

        response = flask_app.test_client().get('/api/test/unexpected-error')

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json()['error_code'], 'INTERNAL_SERVER_ERROR'
        )
        self.assertNotIn('sensitive implementation detail', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
