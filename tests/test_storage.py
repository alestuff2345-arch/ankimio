import os
import unittest
import psycopg
from unittest.mock import patch
from test_config import configure_test_database
configure_test_database()
from storage import db, postgres_options, initialize_storage, Row, database_connection_hint

class StorageConfiguration(unittest.TestCase):
    def test_render_refuses_ephemeral_storage(self):
        with patch.dict(os.environ,{'DATABASE_URL':'','RENDER':'true'}):
            with self.assertRaisesRegex(RuntimeError,'Falta DATABASE_URL'):
                with db():pass

    def test_required_database_never_silently_falls_back(self):
        with patch.dict(os.environ,{'DATABASE_URL':'','ANKIMIO_REQUIRE_DATABASE':'1'}):
            with self.assertRaisesRegex(RuntimeError,'Falta DATABASE_URL'):
                with db():pass

    def test_remote_connection_requires_verified_tls_and_timeouts(self):
        with patch.dict(os.environ,{'DATABASE_URL':'postgresql://example:fake@pooler.example.com/postgres?sslmode=disable'}):
            options=postgres_options()
            self.assertEqual(options['sslmode'],'verify-full')
            self.assertTrue(__import__('pathlib').Path(options['sslrootcert']).is_file())
            self.assertNotEqual(options['sslrootcert'],'system')
            self.assertEqual(options['connect_timeout'],'10')
            self.assertNotIn('options',options)

    def test_explicit_ca_file_is_used_without_disabling_verification(self):
        import ssl
        from pathlib import Path
        ca=ssl.get_default_verify_paths().cafile
        with patch.dict(os.environ,{'DATABASE_URL':'postgresql://example:fake@pooler.example.com/postgres?sslmode=disable','DATABASE_SSLROOTCERT':ca}):
            options=postgres_options()
            self.assertEqual(options['sslrootcert'],ca)
            self.assertEqual(options['sslmode'],'verify-full')

    def test_missing_or_invalid_ca_is_reported_without_echoing_path(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'private-example.pem'
            with patch.dict(os.environ,{'DATABASE_URL':'postgresql://example:fake@pooler.example.com/postgres','DATABASE_SSLROOTCERT':str(path)}):
                for write in (False,True):
                    if write:path.write_text('not a certificate')
                    with self.assertRaisesRegex(RuntimeError,'PG_TLS_CA_FILE') as error:postgres_options()
                    self.assertNotIn('private-example',str(error.exception))

    def test_invalid_connection_string_does_not_echo_credentials(self):
        with patch.dict(os.environ,{'DATABASE_URL':'bad-not-a-dsn-fake-password'}):
            with self.assertRaises(RuntimeError) as error:postgres_options()
            self.assertNotIn('fake-password',str(error.exception))

    def test_initialization_preserves_existing_data(self):
        with db() as c:
            c.execute('INSERT INTO decks VALUES (?,?)',('schema-preservation','Conservar'))
        initialize_storage()
        with db() as c:
            self.assertEqual(c.execute('SELECT name FROM decks WHERE id=?',('schema-preservation',)).fetchone()['name'],'Conservar')
            c.execute('DELETE FROM decks WHERE id=?',('schema-preservation',))

    def test_failed_postgres_connection_does_not_open_sqlite(self):
        with patch.dict(os.environ,{'DATABASE_URL':'postgresql://test@127.0.0.1/example'}),patch('storage.postgres_pool',side_effect=psycopg.OperationalError('test connection failure')),patch('storage.sqlite3.connect') as local:
            with self.assertRaises(psycopg.OperationalError):
                with db():pass
            local.assert_not_called()

    def test_pool_is_reused_and_recreated_for_changed_configuration(self):
        import storage
        with patch.object(storage,'_pool',None), patch.object(storage,'_pool_key',None), \
                patch('storage.ConnectionPool') as create, \
                patch('storage.postgres_options',return_value={}), \
                patch.dict(os.environ,{'DATABASE_URL':'postgresql://test@localhost/one'}):
            first=storage.postgres_pool()
            self.assertIs(storage.postgres_pool(),first)
            self.assertEqual(create.call_count,1)
            self.assertEqual(create.call_args.kwargs['max_size'],4)
            os.environ['DATABASE_URL']='postgresql://test@localhost/two'
            storage.postgres_pool()
            self.assertEqual(create.call_count,2)
            first.close.assert_called_once()

    def test_safe_diagnostics_distinguish_failures_without_echoing_secrets(self):
        for detail,code in (
            ('password authentication failed for user postgres.secret','PG_AUTH'),
            ('Tenant or user not found secret-password','PG_USER'),
            ('connection timeout expired secret-password','PG_NETWORK'),
            ('could not translate host name secret-password','PG_DNS'),
            ('SSL certificate verify failed secret-password','PG_TLS_TRUST'),
            ('server certificate does not match host name secret-password','PG_TLS_HOST'),
            ('root certificate file does not exist secret-password','PG_TLS_CA_FILE'),
            ('unsupported startup parameter: options secret-password','PG_POOLER'),
            ('permission denied for schema secret-password','PG_PERMISSIONS'),
            ('unknown secret-password','PG_CONNECTION'),
        ):
            message=database_connection_hint(psycopg.OperationalError(detail))
            self.assertTrue(message.startswith(code+':'),message)
            self.assertNotIn('secret-password',message)
            self.assertNotIn('postgres.secret',message)

    @unittest.skipUnless(os.environ.get('ANKIMIO_TEST_DATABASE_URL'),'Requires PostgreSQL')
    def test_pooler_safe_transaction_settings(self):
        with db() as c:
            self.assertEqual(c.execute('SHOW search_path').fetchone()[0],'ankimio')
            self.assertEqual(c.execute('SHOW statement_timeout').fetchone()[0],'15s')
            self.assertEqual(c.execute('SHOW lock_timeout').fetchone()[0],'5s')

    @unittest.skipUnless(os.environ.get('ANKIMIO_TEST_DATABASE_URL'),'Requires PostgreSQL')
    def test_pool_reuses_connection_after_rollback_and_replaces_closed_connection(self):
        with db() as c:
            pid=c.execute('SELECT pg_backend_pid()').fetchone()[0]
        with self.assertRaisesRegex(RuntimeError,'rollback'):
            with db() as c:
                self.assertEqual(c.execute('SELECT pg_backend_pid()').fetchone()[0],pid)
                c.execute('INSERT INTO decks VALUES (?,?)',('pool-rollback','Rollback'))
                raise RuntimeError('rollback')
        with db() as c:
            self.assertIsNone(c.execute('SELECT 1 FROM decks WHERE id=?',('pool-rollback',)).fetchone())
            self.assertEqual(c.execute('SELECT pg_backend_pid()').fetchone()[0],pid)
        from storage import postgres_pool
        with postgres_pool().connection() as connection:
            connection.close()
        with db() as c:
            self.assertNotEqual(c.execute('SELECT pg_backend_pid()').fetchone()[0],pid)

    def test_row_supports_existing_dict_and_index_access(self):
        row=Row(id='one',name='Example')
        self.assertEqual(row[0],'one')
        self.assertEqual(row['name'],'Example')
        self.assertEqual(dict(row),{'id':'one','name':'Example'})
