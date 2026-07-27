import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from config import Config
from db import init_db
from db.applications import get_application_stats, update_application_status
from db.mypages import update_mypage_status
from domain.statuses import ApplicationStatus


class DatabaseStatusMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, 'jobs.db')
        self.original_db_path = Config.DB_PATH
        Config.DB_PATH = self.db_path

    def tearDown(self):
        Config.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_new_database_accepts_workflow_statuses(self):
        init_db()
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("INSERT INTO jobs (company_name) VALUES ('Test Co')")
            job_id = conn.execute("SELECT id FROM jobs").fetchone()[0]
            conn.execute(
                "INSERT INTO applications (job_id, status) VALUES (?, 'processing')",
                (job_id,),
            )
            conn.execute(
                "UPDATE applications SET status = 'dry_run_done' WHERE job_id = ?",
                (job_id,),
            )
            conn.execute(
                "INSERT INTO mypage_credentials (job_id, status) "
                "VALUES (?, 'filling_profile')",
                (job_id,),
            )
            conn.commit()

    def test_legacy_constraints_are_migrated_without_data_loss(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.executescript('''
                PRAGMA foreign_keys=ON;
                CREATE TABLE jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL
                );
                CREATE TABLE es_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL
                );
                CREATE TABLE applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    es_id INTEGER,
                    ai_generated_es TEXT,
                    status TEXT DEFAULT 'pending'
                        CHECK(status IN ('pending', 'generating', 'ready', 'submitted', 'failed')),
                    submitted_at TIMESTAMP,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE mypage_credentials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL UNIQUE,
                    login_url TEXT,
                    username TEXT,
                    initial_password TEXT,
                    current_password TEXT,
                    source_email_id TEXT,
                    status TEXT DEFAULT 'received'
                        CHECK(status IN ('received', 'logging_in', 'password_changed',
                            'profile_filled', 'es_filling', 'draft_saved',
                            'ready_for_review', 'manual_intervention_needed',
                            'submitted', 'failed')),
                    error_message TEXT,
                    last_screenshot TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO jobs (company_name) VALUES ('Legacy Co');
                INSERT INTO applications (job_id, status) VALUES (1, 'pending');
                INSERT INTO mypage_credentials (job_id, username, status)
                    VALUES (1, 'legacy-user', 'received');
            ''')

        init_db()

        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("UPDATE applications SET status = 'processing' WHERE id = 1")
            conn.execute(
                "UPDATE mypage_credentials SET status = 'filling_profile' WHERE id = 1"
            )
            username = conn.execute(
                "SELECT username FROM mypage_credentials WHERE id = 1"
            ).fetchone()[0]
            self.assertEqual(username, 'legacy-user')

    def test_generating_applications_are_included_in_stats(self):
        init_db()
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("INSERT INTO jobs (company_name) VALUES ('Test Co')")
            conn.execute(
                "INSERT INTO applications (job_id, status) "
                "VALUES (1, 'generating')"
            )
            conn.commit()

        stats = get_application_stats()

        self.assertEqual(stats['generating'], 1)
        self.assertEqual(stats['total'], 1)


class MyPageGenerationRouteTests(unittest.TestCase):
    def test_generation_returns_text_in_same_response(self):
        from routes.api_mypage import api_mypage_generate_es, mypage_bp
        from flask import Flask

        app = Flask(__name__)
        app.register_blueprint(mypage_bp)
        fake_job = {'id': 1, 'company_name': 'Test Co'}
        fake_result = {
            'text': '生成結果', 'char_count': 4, 'max_chars': 400,
            'min_chars': 360, 'attempts': 1, 'status': 'ok',
        }

        with patch('db.jobs.get_job', return_value=fake_job), \
                patch('db.es.get_all_es_documents', return_value=[]), \
                patch('db.openwork.get_openwork_data', return_value=None), \
                patch(
                    'services.strict_es_generator.generate_strict_es',
                    return_value=fake_result,
                ):
            response = app.test_client().post(
                '/api/mypage/generate-es',
                json={'job_id': 1, 'question': '自己PR', 'max_chars': 400},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['text'], '生成結果')


class StatusValidationTests(unittest.TestCase):
    def test_status_enums_have_string_values_on_supported_python_versions(self):
        self.assertEqual(str(ApplicationStatus.PENDING), 'pending')

    def test_invalid_application_status_fails_before_database_write(self):
        with self.assertRaisesRegex(ValueError, 'Invalid application status'):
            update_application_status(1, 'typo_status')

    def test_invalid_mypage_status_fails_before_database_write(self):
        with self.assertRaisesRegex(ValueError, 'Invalid MyPage status'):
            update_mypage_status(1, 'typo_status')


class ESUploadRouteTests(unittest.TestCase):
    def test_japanese_filename_keeps_an_allowed_extension(self):
        from flask import Flask
        from routes.api_es import es_bp

        app = Flask(__name__)
        app.register_blueprint(es_bp)

        with tempfile.TemporaryDirectory() as upload_dir, \
                patch.object(Config, 'UPLOAD_DIR', upload_dir), \
                patch(
                    'services.es_parser.parse_es_file',
                    return_value={
                        'self_pr': '',
                        'motivation': '',
                        'strengths': [],
                        'is_resume': False,
                    },
                ), \
                patch('services.es_parser.save_es_to_db', return_value=7):
            response = app.test_client().post(
                '/api/es/upload',
                data={'file': (io.BytesIO(b'%PDF-test'), '履歴書.pdf')},
                content_type='multipart/form-data',
            )
            saved_files = list(Path(upload_dir).iterdir())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['id'], 7)
        self.assertEqual(len(saved_files), 1)
        self.assertEqual(saved_files[0].suffix, '.pdf')


class DockerConfigurationTests(unittest.TestCase):
    def test_container_listens_on_all_interfaces_but_host_port_is_local(self):
        compose = (
            Path(__file__).resolve().parents[1] / 'docker-compose.yml'
        ).read_text(encoding='utf-8')

        self.assertIn('"127.0.0.1:5001:5000"', compose)
        self.assertIn('HOST=0.0.0.0', compose)


if __name__ == '__main__':
    unittest.main()
