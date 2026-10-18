"""Never run destructive application tests against the production DATABASE_URL."""
import os
import tempfile

def configure_test_database():
    os.environ['ANKIMIO_DATA']=tempfile.mkdtemp(prefix='ankimio-test-')
    test_url=os.environ.get('ANKIMIO_TEST_DATABASE_URL','')
    if test_url:os.environ['DATABASE_URL']=test_url
    else:os.environ.pop('DATABASE_URL',None)
    os.environ.pop('RENDER',None)
    os.environ.pop('ANKIMIO_REQUIRE_DATABASE',None)
