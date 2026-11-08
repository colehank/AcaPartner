"""Editor working files reuse the generation service; evidence stays pinned."""
import tempfile
import unittest
from research_partner.app import App
from research_partner.store import Problem

class EditorSources(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = App(self.tmp.name)
        self.project = self.app.dispatch({'action':'desk.project.create','title':'Source editor fixture','template':'single','request_id':'project'})['project']
    def tearDown(self): self.tmp.cleanup()
    def script(self, action, **payload):
        return self.app.dispatch({'action':'recipe.script.'+action,'project_id':self.project['id'],'request_id':'script','payload':{'filename':'analysis.py',**payload}})
    def test_working_copy_cas_and_snapshot_identity(self):
        original = 'def compute(x):\n    return x + 1\n'
        first = self.script('write',code=original,expected_sha256=None)
        source = self.app.store.create('report','Registered analysis',self.project['id'],{'attachments':{'code':first['sha256']}})
        files = self.app.dispatch({'action':'article.files','project_id':self.project['id']})
        entry = next(e for e in files['entries'] if e.get('asset_sha256')==first['sha256'])
        self.assertEqual(files['working_scripts'][0]['path'],'scripts/analysis.py')
        self.assertEqual(entry['role'],'registered_source')
        changed = self.script('write',code='print("revised")\n',expected_sha256=first['sha256'])
        self.assertNotEqual(changed['sha256'],first['sha256'])
        self.assertEqual((self.app.store.blobs/first['sha256']).read_text(),original)
        self.assertEqual(self.app.store.get(source['id'])['revision'],source['revision'])
        with self.assertRaises(Problem): self.script('write',code='stale',expected_sha256=first['sha256'])
        self.assertEqual(self.script('read')['code'],'print("revised")\n')
    def test_source_paths_are_not_inferred_from_untrusted_names(self):
        asset=self.app.store.add_asset(b'print(1)','fake.py','text/x-python',{'project_id':self.project['id'],'source_path':'scripts/../fake.py'})
        self.app.store.create('report','Input',self.project['id'],{'attachments':{'code':asset['sha']}})
        files=self.app.dispatch({'action':'article.files','project_id':self.project['id']})
        entry=next(e for e in files['entries'] if e.get('asset_sha256')==asset['sha'])
        self.assertNotIn('working_copy_path',entry)
        self.assertEqual(files['working_scripts'],[])
    def test_project_authority_still_applies(self):
        other=self.app.store.create('project','Other')
        with self.assertRaises(Problem):
            self.app.dispatch({'action':'recipe.script.write','project_id':self.project['id'],'payload':{'filename':'analysis.py','code':'print(1)','expected_sha256':None}},scope={other['id']})
        with self.assertRaises(Problem): self.script('write',filename='../analysis.py',code='print(1)',expected_sha256=None)

    def test_identical_blobs_do_not_hide_another_projects_working_file(self):
        self.script('write',code='print(1)',expected_sha256=None)
        other=self.app.dispatch({'action':'desk.project.create','title':'Another','template':'single','request_id':'other'})['project']
        self.app.dispatch({'action':'recipe.script.write','project_id':other['id'],'request_id':'other-script','payload':{'filename':'different.py','code':'print(1)','expected_sha256':None}})
        files=self.app.dispatch({'action':'article.files','project_id':other['id']})
        self.assertEqual([e['path'] for e in files['working_scripts']],['scripts/different.py'])

    def test_utf8_source_without_text_mime_stays_readable_and_binary_does_not(self):
        for filename,raw,encoding in [('component.tsx',b'export const x = <div />;','utf-8'),('invalid.tsx',b'\xff\xfe\x00','base64')]:
            asset=self.app.store.add_asset(raw,filename,'application/octet-stream',{'project_id':self.project['id']})
            self.app.store.create('report',filename,self.project['id'],{'source_asset':asset['sha']})
            files=self.app.dispatch({'action':'article.files','project_id':self.project['id']})
            entry=next(e for e in files['entries'] if e.get('asset_sha256')==asset['sha'])
            result=self.app.dispatch({'action':'article.file_read','project_id':self.project['id'],'path':entry['path']})
            self.assertEqual(result['encoding'],encoding)
