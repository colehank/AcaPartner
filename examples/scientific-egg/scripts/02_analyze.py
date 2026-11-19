"""Analyze actual generated CSV; never substitute a hand-written result table."""
from pathlib import Path
import argparse, json
import numpy as np
import pandas as pd
from scipy.stats import norm
ROOT=Path(__file__).resolve().parents[1]
def wilson(success,n):
 if not n:return [None,None]
 z=norm.ppf(.975);p=success/n;d=1+z*z/n;c=(p+z*z/(2*n))/d;h=z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
 return [max(0,c-h),min(1,c+h)]
def analyze(data,out,config):
 df=pd.read_csv(data/'observations.csv');criteria=config['criteria'];out.mkdir(parents=True,exist_ok=True)
 assert df.sample_id.is_unique and len(df)==480 and df.is_simulated.all()
 df['assessable']=df[['white_index','yolk_index']].notna().all(axis=1)
 df['white_pass']=df.white_index.ge(criteria['white_min']);df['yolk_pass']=df.yolk_index.between(criteria['yolk_min'],criteria['yolk_max'],inclusive='both')
 df['joint_pass']=df.assessable&df.white_pass&df.yolk_pass
 df.to_csv(out/'classified_samples.csv',index=False)
 def summarize(group):
  n=len(group);assessed=int(group.assessable.sum());s=int(group.joint_pass.sum());lo,hi=wilson(s,n)
  return {'n_total':n,'n_assessable':assessed,'n_missing':n-assessed,'white_pass_n':int((group.white_pass&group.assessable).sum()),'yolk_pass_n':int((group.yolk_pass&group.assessable).sum()),'joint_pass_n':s,'joint_rate':s/n,'assessable_joint_rate':s/assessed if assessed else None,'wilson_low':lo,'wilson_high':hi,'white_mean':float(group.white_index.mean()),'yolk_mean':float(group.yolk_index.mean())}
 pooled=[{'method':k,**summarize(g)} for k,g in df.groupby('method',sort=False)]
 batches=[{'batch':b,'method':m,**summarize(g)} for (b,m),g in df.groupby(['batch','method'],sort=False)]
 strata=[{'method':m,'nominal_mass_g':int(w),'initial_group_c':int(t),**summarize(g)} for (m,w,t),g in df.groupby(['method','nominal_mass_g','initial_group_c'],sort=False)]
 sensitivity=[]
 for threshold in np.arange(6.5,9.01,.25):
  for method,g in df.groupby('method',sort=False):
   success=int((g.assessable&g.white_index.ge(threshold)&g.yolk_index.between(criteria['yolk_min'],criteria['yolk_max'])).sum());lo,hi=wilson(success,len(g));sensitivity.append({'method':method,'white_threshold':threshold,'joint_rate':success/len(g),'joint_pass_n':success,'n_total':len(g),'wilson_low':lo,'wilson_high':hi})
 for name,rows in [('method_summary',pooled),('batch_summary',batches),('condition_summary',strata),('threshold_sensitivity',sensitivity)]:pd.DataFrame(rows).to_csv(out/(name+'.csv'),index=False)
 # Show exactly why marginal success rates cannot substitute for paired joint success.
 paired={row['method']:{'white_n':row['white_pass_n'],'yolk_n':row['yolk_pass_n'],'paired_joint_n':row['joint_pass_n'],'n_total':row['n_total']} for row in pooled}
 p={row['method']:row for row in pooled};differences=[]
 for method in config['methods']:
  if method=='periodic':continue
  a=pd.DataFrame(batches);left=a[a.method=='periodic'].set_index('batch');right=a[a.method==method].set_index('batch');d=left.joint_rate-right.joint_rate
  differences.append({'contrast':'periodic - '+method,'batch_differences':d.to_dict(),'mean_difference':float(d.mean()),'scope':'descriptive paired differences across four simulated batches, not real-world inference'})
 checks={'samples':len(df),'unique_ids':bool(df.sample_id.is_unique),'all_synthetic':bool(df.is_simulated.all()),'missing_rows':df.loc[~df.assessable,'sample_id'].tolist(),'excluded_rows':0,'group_sizes':{k:int(v) for k,v in df.groupby('method').size().items()},'joint_never_exceeds_either_margin':all(r['joint_pass_n']<=min(r['white_pass_n'],r['yolk_pass_n']) for r in pooled),'all_recorded_batches_present':sorted(df.batch.unique())==sorted(config['batches'])}
 summary={'synthetic':True,'seed':config['seed'],'criteria':criteria,'methods':p,'batch_differences':differences,'paired_counts':paired,'checks':checks,'uncertainty':'95% Wilson intervals for descriptive egg-level rates under the synthetic generator. They ignore within-batch dependence and are not population validation; four batches are reported separately. No p-values or causal inference.','limitations':['two-node phenomenological model, not validated CFD','arbitrary uncalibrated texture indices','four generated batches, no actual experimental replication','missing rows retained; no imputation','B04 periodic duty-cycle deviation retained','thresholds chosen for demonstration, not food safety or preference recommendations']}
 (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');(out/'quality_checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:{'joint':v['joint_pass_n'],'n':v['n_total'],'white':round(v['white_mean'],2),'yolk':round(v['yolk_mean'],2)} for k,v in p.items()}))
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--data',type=Path,default=ROOT/'data');parser.add_argument('--output',type=Path,default=ROOT/'results');args=parser.parse_args();analyze(args.data,args.output,json.loads((ROOT/'protocol.json').read_text()))
