"""Recoverable tree actions reuse file authority and never overwrite another file."""
import os
import tempfile
import unittest
from pathlib import Path
from research_partner.app import App
from research_partner.store import Problem

class TreeActions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=App(self.tmp.name)
        self.project=self.app.dispatch({'action':'desk.project.create','title':'Tree actions','template':'single','request_id':'project'})['project']
    def tearDown(self):self.tmp.cleanup()
    def call(self,action,payload,key='test'):
        return self.app.dispatch({'action':action,'project_id':self.project['id'],'request_id':key,'payload':payload})
    def script(self,name='tree.py',code='print(1)\n',expected=None):
        return self.call('recipe.script.write',{'filename':name,'code':code,'expected_sha256':expected})
    def test_script_trash_restore_replay_and_snapshot(self):
        saved=self.script();payload={'filename':'tree.py','expected_sha256':saved['sha256']}
        result=self.call('recipe.script.trash',payload)
        self.assertEqual(self.call('recipe.script.trash',payload)['trash_id'],result['trash_id'])
        self.assertTrue(self.call('recipe.script.trash',payload)['replayed'])
        with self.assertRaises(Problem):self.call('recipe.script.read',{'filename':'tree.py'})
        listing=self.call('recipe.script.trash.list',{})['items'];self.assertEqual(listing[0]['filename'],'tree.py')
        self.assertEqual((self.app.store.blobs/saved['sha256']).read_text(),'print(1)\n')
        self.call('recipe.script.restore',{'trash_id':result['trash_id']})
        self.assertEqual(self.call('recipe.script.read',{'filename':'tree.py'})['code'],'print(1)\n')
        self.assertEqual(self.call('recipe.script.trash.list',{})['items'],[])
    def test_stale_delete_and_restore_collision_preserve_both_versions(self):
        old=self.script();new=self.script(code='print(2)\n',expected=old['sha256'])
        with self.assertRaises(Problem):self.call('recipe.script.trash',{'filename':'tree.py','expected_sha256':old['sha256']})
        deleted=self.call('recipe.script.trash',{'filename':'tree.py','expected_sha256':new['sha256']},'delete-new')
        self.script(code='print(3)\n')
        with self.assertRaises(Problem):self.call('recipe.script.restore',{'trash_id':deleted['trash_id']})
        self.assertEqual(self.call('recipe.script.read',{'filename':'tree.py'})['code'],'print(3)\n')
        self.assertEqual(len(self.call('recipe.script.trash.list',{})['items']),1)
    def test_script_paths_and_symlinks_are_not_followed(self):
        saved=self.script()
        with self.assertRaises(Problem):self.call('recipe.script.trash',{'filename':'../tree.py','expected_sha256':saved['sha256']})
        with self.app.notebook._locked(self.project['id']) as session:
            fd=os.open('scripts',os.O_RDONLY|os.O_DIRECTORY,dir_fd=session['project_root_fd'])
            try:os.symlink('tree.py','linked.py',dir_fd=fd)
            finally:os.close(fd)
        with self.assertRaises(Problem):self.call('recipe.script.trash',{'filename':'linked.py','expected_sha256':saved['sha256']})
        self.assertEqual(self.call('recipe.script.read',{'filename':'tree.py'})['code'],'print(1)\n')
    def test_native_note_move_and_trash_work_without_overwriting(self):
        created=self.call('notes.create',{'relative_path':'notes/folder/old.md','markdown':'# 研究笔记\n','if_absent':True},'create')
        saved=self.call('notes.read',{'relative_path':'notes/folder/old.md'})
        moved=self.call('notes.move',{'relative_path':'notes/folder/old.md','new_path':'notes/folder/new.md','expected_content_sha256':saved['content_sha256'],'links_reviewed':True},'move')
        self.assertEqual(moved['relative_path'],'notes/folder/new.md')
        deleted=self.call('notes.trash',{'relative_path':'notes/folder/new.md','expected_content_sha256':saved['content_sha256']},'delete')
        self.assertEqual(len(self.call('notes.trash.list',{})['items']),1)
        self.call('notes.create',{'relative_path':'notes/folder/new.md','markdown':'new owner','if_absent':True},'replacement')
        with self.assertRaises(Problem):self.call('notes.restore',{'trash_id':deleted['trash_id']},'collision')
        self.assertEqual(self.call('notes.read',{'relative_path':'notes/folder/new.md'})['markdown'],'new owner')
    def test_question_archive_can_be_undone_without_deleting_children(self):
        q=self.app.dispatch({'action':'workbench.question.create','project_id':self.project['id'],'title':'Parent?','parent_id':None,'request_key':'q'})
        child=self.app.dispatch({'action':'workbench.question.create','project_id':self.project['id'],'title':'Child?','parent_id':q['id'],'request_key':'child'})
        archived=self.app.dispatch({'action':'object.archive','id':q['id'],'expected_revision':q['revision']})
        self.assertTrue(archived['archived']);self.assertFalse(self.app.store.get(child['id'])['archived'])
        restored=self.app.dispatch({'action':'object.save','id':q['id'],'expected_revision':archived['revision'],'archived':False})
        self.assertFalse(restored['archived'])
