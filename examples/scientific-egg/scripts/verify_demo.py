"""Check identity, joint-event arithmetic, missingness, thermals and deterministic regeneration."""
from pathlib import Path
import tempfile,subprocess,sys,json,hashlib,zipfile
import pandas as pd
from lxml import etree
ROOT=Path(__file__).resolve().parents[1]
def main():
 raw=pd.read_csv(ROOT/'data/observations.csv');classified=pd.read_csv(ROOT/'results/classified_samples.csv');traces=pd.read_csv(ROOT/'data/temperature_traces.csv');summary=json.loads((ROOT/'results/summary.json').read_text());criteria=json.loads((ROOT/'protocol.json').read_text())['criteria']
 assert len(raw)==480 and raw.sample_id.is_unique and raw.is_simulated.all()
 assert len(traces)==40080 and traces.is_simulated.all() and traces.bath_c.max()<=100
 assert raw.white_index.isna().sum()==4 and classified.assessable.sum()==476
 expected=raw.white_index.ge(criteria['white_min'])&raw.yolk_index.between(criteria['yolk_min'],criteria['yolk_max'])&raw[['white_index','yolk_index']].notna().all(axis=1)
 assert expected.tolist()==classified.joint_pass.tolist()
 for method,group in raw.groupby('method'):
  assert len(group)==120;assert summary['methods'][method]['joint_pass_n']==int(expected[group.index].sum())
 for ident,group in traces.groupby('sample_id'):
  row=raw.set_index('sample_id').loc[ident];assert group.time_s.iloc[0]==0 and group.time_s.iloc[-1]==row.duration_s and group.time_s.is_monotonic_increasing
 with tempfile.TemporaryDirectory(prefix='egg-reproduction-') as t:
  out=Path(t);subprocess.run([sys.executable,str(ROOT/'scripts/01_simulate.py'),'--output',str(out)],check=True,capture_output=True)
  for name in ['observations.csv','temperature_traces.csv']:
   assert hashlib.sha256((ROOT/'data'/name).read_bytes()).digest()==hashlib.sha256((out/name).read_bytes()).digest()
 with zipfile.ZipFile(ROOT/'manuscript/paper.docx') as archive:
  assert archive.testzip() is None;assert len([n for n in archive.namelist() if n.startswith('word/media/')])>=4
  node=etree.fromstring(archive.read('word/document.xml'));ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main','m':'http://schemas.openxmlformats.org/officeDocument/2006/math'}
  text=''.join(node.xpath('//w:t/text()',namespaces=ns));assert str(summary['methods']['periodic']['joint_pass_n'])+'/120' in text and '合成' in text and len(node.xpath('//m:oMath',namespaces=ns))>=2
 checks={'synthetic':True,'samples':len(raw),'traces':len(traces),'missing_retained':4,'paired_definition_matches':True,'all_group_counts_match':True,'temperature_bounds_checked':True,'seed_regenerates_identical_csv':True,'docx_has_4_images_and_native_equations':True}
 (ROOT/'results/verification.json').write_text(json.dumps(checks,indent=2)+'\n');print(json.dumps(checks))
if __name__=='__main__':main()
