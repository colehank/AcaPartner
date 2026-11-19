"""Generate fully disclosed synthetic eggs. No sensor/experimental data are claimed."""
from pathlib import Path
import argparse, json, hashlib
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]

def simulate(config, output):
    rng=np.random.default_rng(config['seed']);model=config['model'];dt=config['time_step_s']
    observations=[];trajectories=[];ordinal=0
    for batch_i,batch in enumerate(config['batches']):
      for method,protocol in config['methods'].items():
       for nominal_mass in config['mass_groups_g']:
        for nominal_initial in config['initial_temperature_groups_c']:
         for rep in range(1,config['replicates_per_cell']+1):
          ordinal+=1;ident=f'EGG-{ordinal:04d}';mass=float(rng.normal(nominal_mass,1.4));initial=float(rng.normal(nominal_initial,.65))
          scale=(mass/60)**(2/3)*float(rng.lognormal(0,.055));tw=ty=initial;dw=dy=0.;peak_y=initial;noise=float(rng.normal(0,.45));duration=protocol['duration_s']
          deviation=method=='periodic' and batch=='B04'
          for t in range(0,duration+1,dt):
           if method=='periodic':
            half=protocol['half_cycle_s'];phase=t%(half*2);hot=phase<(half+(20 if deviation else 0));bath=protocol['hot_c'] if hot else protocol['cool_c']
           else:bath=protocol['bath_c']
           bath=min(100.0,bath+model['batch_heat_shift_c'][batch_i]+noise)  # fixed-pressure toy bath: no superheating
           if t%config['record_interval_s']==0 or t==duration:trajectories.append([ident,batch,method,nominal_mass,nominal_initial,t,round(bath,4),round(tw,4),round(ty,4),True])
           if t==duration:break
           old_tw=tw;tw+=dt*(bath-tw)/(model['white_tau_s']*scale);ty+=dt*(old_tw-ty)/(model['yolk_tau_s']*scale);peak_y=max(peak_y,ty)
           dw+=dt*min(.05,model['white_rate_s']*np.exp((tw-model['white_reference_c'])/model['white_scale_c']))
           dy+=dt*min(.04,model['yolk_rate_s']*np.exp((ty-model['yolk_reference_c'])/model['yolk_scale_c']))
          white=float(np.clip(10*(1-np.exp(-dw))+rng.normal(0,model['measurement_sd'])+model['batch_texture_shift'][batch_i],0,10))
          yolk=float(np.clip(10*np.exp(-dy)+rng.normal(0,model['measurement_sd']),0,10))
          observations.append([ident,batch,method,nominal_mass,round(mass,3),nominal_initial,round(initial,3),duration,round(tw,3),round(ty,3),round(peak_y,3),round(white,3),round(yolk,3),'hot_dwell_plus_20s' if deviation else 'none','complete',True])
    cols=['sample_id','batch','method','nominal_mass_g','mass_g','initial_group_c','initial_temperature_c','duration_s','end_white_c','end_yolk_c','peak_yolk_c','white_index','yolk_index','protocol_deviation','quality_flag','is_simulated']
    df=pd.DataFrame(observations,columns=cols)
    # Fixed identities: declared before evaluating outcome or threshold.
    missing=['EGG-0017','EGG-0146','EGG-0259','EGG-0443']
    df.loc[df.sample_id.isin(missing),'white_index']=np.nan;df.loc[df.sample_id.isin(missing),'quality_flag']='white_reading_missing'
    output.mkdir(parents=True,exist_ok=True);df.to_csv(output/'observations.csv',index=False)
    pd.DataFrame(trajectories,columns=['sample_id','batch','method','nominal_mass_g','initial_group_c','time_s','bath_c','white_c','yolk_c','is_simulated']).to_csv(output/'temperature_traces.csv',index=False)
    dictionary={'disclosure':'All values are synthetic. Texture indices are arbitrary proxies, not calibrated gelation or food-safety measures.','sample_unit':'one simulated egg; white/yolk paired by sample_id','row_count':len(df),'missing_sample_ids':missing,'batch_unit':'four synthetic process groups; time points are not independent samples','columns':{'white_index':'0-10; synthetic setting proxy; larger means firmer','yolk_index':'0-10; synthetic softness proxy; creamy target is an interval, not maximum softness','nominal_mass_g':'design stratum; actual mass has generated variation','protocol_deviation':'B04 periodic keeps total duration fixed but changes duty cycle; not excluded'},'generation_model':'dTw/dt=(Tb-Tw)/tau_w; dTy/dt=(Tw-Ty)/tau_y; accumulated exponential rate proxies; see protocol.json'}
    (output/'data_dictionary.json').write_text(json.dumps(dictionary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'synthetic':True,'samples':len(df),'traces':len(trajectories),'missing':len(missing)}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'data');args=p.parse_args();simulate(json.loads((ROOT/'protocol.json').read_text()),args.output)
