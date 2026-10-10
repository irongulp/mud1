"""Exercise the installed editor on a disposable deployment container only."""
import argparse
from pathlib import Path

from tests.integration_database_access import tcp,rejected
from tools.database_access import read_credentials,CREDENTIAL_FILE


def verify(name):
    if not Path('/.dockerenv').exists(): raise RuntimeError('This check is for disposable Docker deployments only')
    credentials=read_credentials(Path('/etc/mud86')/CREDENTIAL_FILE)
    rejected(lambda:tcp(credentials,user='root',password='',database=None))
    with tcp(credentials) as connection,connection.cursor() as cursor:
        cursor.execute("SELECT score,revision FROM persona_editor WHERE namespace='mud' AND name=%s",(name.lower(),))
        before=cursor.fetchone()
        if before is None: raise AssertionError('Deployment editor fixture missing')
        score,revision=before
        cursor.execute("UPDATE persona_editor SET score=%s WHERE namespace='mud' AND name=%s AND revision=%s",
                       (score+1,name.lower(),revision))
        assert cursor.rowcount==1
        cursor.execute("SELECT score,revision FROM persona_editor WHERE namespace='mud' AND name=%s",(name.lower(),))
        assert cursor.fetchone()==(score+1,revision+1)
        cursor.execute("UPDATE persona_editor SET score=%s WHERE namespace='mud' AND name=%s AND revision=%s",
                       (score,name.lower(),revision+1))
        assert cursor.rowcount==1
    print('Installed editor TCP update/revision/restore and root rejection passed')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('name')
    verify(parser.parse_args().name)
