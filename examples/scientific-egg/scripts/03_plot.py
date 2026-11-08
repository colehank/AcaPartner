"""Rebuild every quantitative panel from analysis CSV, with editable vector exports."""
from pathlib import Path
import argparse,json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
ROOT=Path(__file__).resolve().parents[1]
ORDER=['soft_boiled','hard_boiled','sous_vide','periodic']
LABELS={'soft_boiled':'Soft-boiled','hard_boiled':'Hard-boiled','sous_vide':'Sous vide','periodic':'Periodic'}
COLORS={'soft_boiled':'#6389a8','hard_boiled':'#8c939e','sous_vide':'#b29864','periodic':'#6559ac'}
plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['DejaVu Sans','Arial','Helvetica'],'font.size':8.2,'axes.labelsize':8.5,'axes.titlesize':9,'axes.linewidth':.6,'axes.spines.right':False,'axes.spines.top':False,'xtick.labelsize':7.5,'ytick.labelsize':7.5,'legend.fontsize':7.2,'legend.frameon':False,'svg.fonttype':'none','pdf.fonttype':42,'savefig.facecolor':'white'})
def frame():
 fig,axes=plt.subplots(1,2,figsize=(180/25.4,79/25.4));fig.subplots_adjust(left=.085,right=.98,bottom=.24,top=.88,wspace=.33)
 for i,ax in enumerate(axes):ax.text(-.14,1.08,chr(97+i),transform=ax.transAxes,fontweight='bold',fontsize=10,va='bottom');ax.tick_params(length=3,width=.6)
 fig.text(.085,.045,'SYNTHETIC DEMONSTRATION  |  No physical experiments',fontsize=6.5,color='#626773');return fig,axes

def save(fig,name,output):
 fig.canvas.draw();rects=[{'panel':chr(97+i),'x_pt':a.get_position().x0*fig.get_figwidth()*72,'y_pt':a.get_position().y0*fig.get_figheight()*72,'w_pt':a.get_position().width*fig.get_figwidth()*72,'h_pt':a.get_position().height*fig.get_figheight()*72} for i,a in enumerate(fig.axes)]
 (output/(name+'.axes.json')).write_text(json.dumps(rects,indent=2)+'\n')
 # Optional external authoring QA; plain reproduction needs only the pinned public requirements.
 try:from audit_panel_alignment import require_matplotlib_panel_alignment
 except ImportError:pass
 else:require_matplotlib_panel_alignment(fig,json_out=str(output/(name+'.alignment.json')),tolerance_pt=1.5,gutter_tolerance_pt=1.5,strict=True)
 fig.savefig(output/(name+'.png'),dpi=600)
 fig.savefig(output/(name+'.svg'))
 fig.savefig(output/(name+'.pdf'))
 plt.close(fig)

def plot(root,output):
 output.mkdir(parents=True,exist_ok=True);config=json.loads((root/'protocol.json').read_text());df=pd.read_csv(root/'results/classified_samples.csv');summary=pd.read_csv(root/'results/method_summary.csv').set_index('method');traces=pd.read_csv(root/'data/temperature_traces.csv');reference={}
 fig,axs=frame()
 for m in ORDER:
  # Reference identity is fixed by design stratum, before looking at the outcome.
  chosen=df[(df.method==m)&(df.batch=='B01')&(df.nominal_mass_g==60)&(df.initial_group_c==22)].iloc[2];reference[m]=chosen.sample_id;v=traces[traces.sample_id==chosen.sample_id]
  for ax,col in zip(axs,['white_c','yolk_c']):ax.plot(v.time_s/60,v[col],color=COLORS[m],lw=1.6,label=LABELS[m]);ax.set(xlim=(0,61),ylim=(15,104),xlabel='Time (min)',ylabel='Temperature (°C)');ax.set_yticks([20,40,60,80,100])
 axs[0].set_title('White response',loc='left',pad=8);axs[1].set_title('Delayed yolk response',loc='left',pad=8);axs[0].legend(loc='lower right',handlelength=1.6,labelspacing=.25)
 save(fig,'fig1_thermal',output);(output/'reference_eggs.json').write_text(json.dumps(reference,indent=2)+'\n')
 fig,axs=frame();crit=config['criteria'];ax=axs[0];ax.add_patch(Rectangle((crit['white_min'],crit['yolk_min']),10.3-crit['white_min'],crit['yolk_max']-crit['yolk_min'],facecolor='#edf2ee',edgecolor='#a3b7a7',lw=.7,zorder=0))
 for m in ORDER:
  g=df[df.method==m];ax.scatter(g.white_index,g.yolk_index,s=9,alpha=.55,color=COLORS[m],linewidths=0,label=LABELS[m])
 ax.set(xlim=(3,10.35),ylim=(-.3,10.6),xlabel='White setting index (a.u.)',ylabel='Yolk softness index (a.u.)');ax.set_title('Paired samples, not means',loc='left',pad=8)
 ax=axs[1]
 for y,m in enumerate(ORDER):
  r=summary.loc[m];value=r.joint_rate*100;ax.errorbar(value,y,xerr=[[value-r.wilson_low*100],[r.wilson_high*100-value]],fmt='o',color=COLORS[m],ms=5,capsize=3,lw=1.2);ax.text(min(94,r.wilson_high*100+3),y,f'{int(r.joint_pass_n)}/{int(r.n_total)}',fontsize=8,va='center')
 ax.set(yticks=range(4),yticklabels=[LABELS[m] for m in ORDER],xlim=(-2,102),ylim=(3.6,-.6),xlabel='Joint pass rate (%)');ax.set_title('Paired success / all samples',loc='left',pad=8);ax.set_xticks([0,25,50,75,100])
 save(fig,'fig2_joint',output)
 batch=pd.read_csv(root/'results/batch_summary.csv');sensitivity=pd.read_csv(root/'results/threshold_sensitivity.csv');fig,axs=frame()
 for m in ORDER:
  g=batch[batch.method==m];axs[0].plot(range(4),g.joint_rate*100,'o-',color=COLORS[m],ms=4,lw=1.2,label=LABELS[m]);g=sensitivity[sensitivity.method==m];axs[1].plot(g.white_threshold,g.joint_rate*100,color=COLORS[m],lw=1.5)
 axs[0].set(xticks=range(4),xticklabels=['B01','B02','B03','B04*'],ylim=(-3,103),xlabel='Generated batch (30 per method)',ylabel='Joint pass rate (%)');axs[0].set_title('A batch is not replication proof',loc='left',pad=8);axs[0].legend(loc='upper left',labelspacing=.2,handlelength=1.4)
 axs[1].axvline(crit['white_min'],color='#b6b7bd',lw=.7,ls='--');axs[1].set(xlim=(6.4,9.1),ylim=(-3,103),xlabel='Required white index (a.u.)',ylabel='Joint pass rate (%)');axs[1].set_title('Criterion sensitivity',loc='left',pad=8)
 save(fig,'fig3_robustness',output)
 strata=pd.read_csv(root/'results/condition_summary.csv');fig,axs=frame()
 for ax,m in zip(axs,['soft_boiled','periodic']):
  g=strata[strata.method==m];values=g.pivot(index='initial_group_c',columns='nominal_mass_g',values='joint_rate').sort_index();counts=g.pivot(index='initial_group_c',columns='nominal_mass_g',values='joint_pass_n').sort_index();ax.imshow(values.values,vmin=0,vmax=1,cmap='Purples',aspect='auto',origin='lower',extent=(-.5,2.5,-.5,1.5));ax.set(xticks=range(3),xticklabels=['50','60','70'],yticks=range(2),yticklabels=['4','22'],xlabel='Nominal mass (g)',ylabel='Initial group (°C)');ax.set_title(LABELS[m]+'  |  paired pass / 20',loc='left',pad=8)
  for y in range(2):
   for x in range(3):ax.text(x,y,f'{int(counts.iloc[y,x])}/20',ha='center',va='center',color='white' if values.iloc[y,x]>.55 else '#292932',fontsize=9)
 save(fig,'figS1_conditions',output)
 print(json.dumps({'figures':4,'synthetic':True,'formats':['png','svg','pdf'],'reference_eggs':reference}))
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT);parser.add_argument('--output',type=Path,default=ROOT/'figures');args=parser.parse_args();plot(args.root,args.output)
