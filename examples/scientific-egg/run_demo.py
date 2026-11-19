"""Rebuild the demonstration with real local subprocess receipts; does not submit an Agent task."""
from pathlib import Path
from datetime import datetime,timezone
import subprocess,sys,json,hashlib,platform,importlib.metadata
ROOT=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 started=datetime.now(timezone.utc).isoformat();steps=[]
 for name in ['01_simulate.py','02_analyze.py','03_plot.py','04_write_paper.py']:
  start=datetime.now(timezone.utc).isoformat();r=subprocess.run([sys.executable,str(ROOT/'scripts'/name)],cwd=ROOT,capture_output=True,text=True)
  steps.append({'command':['python','scripts/'+name],'started_utc':start,'finished_utc':datetime.now(timezone.utc).isoformat(),'exit_code':r.returncode,'stdout':r.stdout.strip(),'stderr':r.stderr[-6000:]})
  if r.returncode:raise RuntimeError(name+' failed: '+r.stderr[-2000:])
 inputs={str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'protocol.json',*sorted((ROOT/'scripts').glob('0[1-4]*.py'))]}
 outputs={str(p.relative_to(ROOT)):sha(p) for folder in ['data','results','figures','manuscript'] for p in sorted((ROOT/folder).glob('*')) if p.is_file() and p.name not in {'run_receipt.json','verification.json'} and not p.name.endswith('.collisions.json')}
 versions={name:importlib.metadata.version(name) for name in ['numpy','pandas','scipy','matplotlib','python-docx']}
 receipt={'synthetic':True,'execution_kind':'actual_local_script_run','not_platform_task':True,'started_utc':started,'finished_utc':datetime.now(timezone.utc).isoformat(),'python':platform.python_version(),'packages':versions,'steps':steps,'inputs_sha256':inputs,'outputs_sha256':outputs,'scope':'Actual generated data and local computation; no laboratory experiment, model invocation or platform task-runner event is claimed.'}
 (ROOT/'results/run_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'steps':len(steps),'all_exit_codes_zero':all(s['exit_code']==0 for s in steps),'synthetic':True}))
if __name__=='__main__':main()
