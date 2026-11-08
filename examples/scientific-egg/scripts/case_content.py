"""Reading copy for the egg case, shared by fresh publishing and in-place updates."""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METHODS = {'soft_boiled':'沸水6分钟','hard_boiled':'沸水12分钟','sous_vide':'65°C恒温60分钟','periodic':'冷热交替32分钟'}
QUESTIONS = (
    ('q1',None,0,'哪种煮蛋方法能够使蛋白凝固、蛋黄柔软','同一枚蛋能否同时达到蛋白与蛋黄目标？'),
    ('qw','q1',0,'哪种煮法能让蛋白充分凝固？','蛋白是否达到凝固目标？'),
    ('qy','q1',1,'哪种煮法能让蛋黄柔软且成形？','蛋黄是否保持目标软度？'),
    ('q2',None,1,'冷热交替煮蛋法对鸡蛋大小与下锅温度的泛化性','配对达标能否跨批次稳定复现？'),
    ('qs','q2',0,'不同大小与下锅温度下，蛋白凝固、蛋黄柔软的比例有何差异？','质量与初温是否改变配对达标？'),
    ('qb','q2',1,'批次间加热条件的变化，会干扰泛化性的判断吗？','批次差异能否由过程变化解释？'),
    ('qt','q2',2,'改变蛋白凝固的判据，会改变泛化性判断吗？','改变判据后结论是否保留？'),
)
DESCRIPTION = '比较哪种煮蛋方法能够使同一枚鸡蛋的蛋白凝固、蛋黄柔软，再检查冷热交替煮蛋法对不同鸡蛋大小与下锅温度的适用范围。'


def readable_copy(text):
    """Remove repeated template banners, retaining source metadata and scientific limits."""
    text=re.sub(r'^\*\*(?:合成数据[^\n]*|合成研究结果[^\n]*|完整科研项目[^\n]*)\*\*\s*','',text,count=1)
    return (text.replace('枚模拟蛋','枚鸡蛋').replace('四个模拟批次','四个批次')
            .replace('配对达标','同时达标')
            .replace('打开同时达标问题','Q1：哪种煮蛋方法能够使蛋白凝固、蛋黄柔软')
            .replace('查看稳定性问题及其子问题','Q2：冷热交替煮蛋法对鸡蛋大小与下锅温度的泛化性')
            .replace('。图中数值不能解释为真实煮蛋效果或安全建议。','。')
            .replace('模型、量表、四个批次和名义区间都未经实物校准。','')
            .replace('Wilson区间仅为模拟蛋级计数的描述','Wilson区间仅为蛋级计数的描述')
            .replace('；四个批次不等于实物重复验证。','。')
            .replace('两个指数为0–10的模拟代理量，不能解释为实测质构、蛋白质变性率或食品安全标准。',
                     '两个指数均为0–10：蛋白指数越高表示越凝固，蛋黄指数越高表示越软。整枚达标要求同一 sample_id 的蛋白≥7.5、蛋黄在5–8.5内。')
            .replace('这是合成数据研究问题，不是等待人工批准的任务事项。',''))


def build_case(link):
    """link(key, label) resolves the caller's current, versioned research sources."""
    summary = json.loads((ROOT/'results/summary.json').read_text())
    criteria = summary['criteria'];white=criteria['white_min'];low=criteria['yolk_min'];high=criteria['yolk_max']
    rows = list(csv.DictReader((ROOT/'data/observations.csv').open()))
    def passed(row):
        return bool(row['white_index']) and float(row['white_index'])>=white and low<=float(row['yolk_index'])<=high
    target = f'蛋白凝固指数 ≥ {white:g}；蛋黄软度指数在 {low:g}–{high:g} 之间（含端点）。两项必须来自同一个 sample_id，也就是同一枚蛋。'
    methods = summary['methods'];p=methods['periodic']
    counts={method:sum(low<=float(r['yolk_index'])<=high for r in rows if r['method']==method) for method in METHODS}
    table='| 煮法 | 蛋白达标 | 蛋黄达标 | 同一枚同时达标 |\n|:--|--:|--:|--:|\n'+'\n'.join(
        f"| {title} | {methods[key]['white_pass_n']}/120 | {counts[key]}/120 | {methods[key]['joint_pass_n']}/120 |" for key,title in METHODS.items())
    batches=[r for r in csv.DictReader((ROOT/'results/batch_summary.csv').open()) if r['method']=='periodic']
    batch_table='| 批次 | 同时达标的鸡蛋 | 达标率 |\n|:--|--:|--:|\n'+'\n'.join(f"| {r['batch']} | {r['joint_pass_n']}/{r['n_total']} | {float(r['joint_rate']):.1%} |" for r in batches)
    strata=[r for r in csv.DictReader((ROOT/'results/condition_summary.csv').open()) if r['method']=='periodic']
    strata_table='| 鸡蛋质量 | 下锅前温度 | 同时达标的鸡蛋 |\n|:--|:--|--:|\n'+'\n'.join(f"| {r['nominal_mass_g']} g | {r['initial_group_c']}°C | {r['joint_pass_n']}/{r['n_total']} |" for r in strata)
    sensitivity=list(csv.DictReader((ROOT/'results/threshold_sensitivity.csv').open()))
    sensitivity_table='| 蛋白指数下限 | 冷热交替 | 65°C恒温 |\n|--:|--:|--:|\n'+'\n'.join(
        '| '+threshold+' | '+' | '.join(next(r['joint_pass_n']+'/'+r['n_total'] for r in sensitivity if r['method']==method and float(r['white_threshold'])==float(threshold)) for method in ('periodic','sous_vide'))+' |' for threshold in ('6.5','7.5','9.0'))
    success=next(r for r in rows if r['method']=='periodic' and passed(r))
    failure=next(r for r in rows if r['method']=='periodic' and r['white_index'] and float(r['white_index'])>=white and not passed(r))
    example=f"例如 {success['sample_id']} 的蛋白指数为 {float(success['white_index']):.2f}、蛋黄指数为 {float(success['yolk_index']):.2f}，两项同时达标；{failure['sample_id']} 的蛋白为 {float(failure['white_index']):.2f}、蛋黄为 {float(failure['yolk_index']):.2f}，蛋黄超出上限，因此整枚不达标。"
    background=f'''## 想煮出什么样的鸡蛋？

目标是**蛋白凝固，蛋黄仍然柔软但能成形**。只追求“越熟越好”会让蛋黄变硬；只追求“越软越好”又可能过稀。两种口感必须出现在同一枚蛋上，不能把一枚蛋的蛋白和另一枚蛋的蛋黄拼成成功结果。

## 本项目如何判断达标？

| 指标 | 含义 | 本项目判据 |
|:--|:--|:--|
| 蛋白凝固指数，0–10 | 越高表示越凝固 | ≥ {white:g} |
| 蛋黄软度指数，0–10 | 越高表示越软，过高也可能过稀 | {low:g}–{high:g}，含端点 |
| 整枚鸡蛋达标 | 同一枚蛋同时满足以上两项 | 按 sample_id 逐枚判断 |

这些是本案例预先设定的操作判据，不是通用烹饪或食品安全标准。

## 为什么比较四种煮法？

蛋白和蛋黄受热的速度不同。{link('literature','周期煮蛋研究')}提出交替改变水温，因此这里比较沸水6分钟、沸水12分钟、65°C恒温60分钟，以及100°C热水与30°C凉水每2分钟切换、共32分钟的冷热交替煮法。

每种煮法120枚蛋，分4个批次；每批每种煮法30枚，包含50/60/70 g和4/22°C两档初温。480枚蛋中有4枚缺少蛋白读数，保留原记录，计入主要达标率的分母。

由此形成两个问题：**Q1 哪种煮蛋方法能够使蛋白凝固、蛋黄柔软；Q2 冷热交替煮蛋法对鸡蛋大小与下锅温度的泛化性。**

这里的“下锅温度”指鸡蛋下锅前的初温：4°C冷藏或22°C室温，不是水温。Q1比较煮蛋方法，Q2检查同一种冷热交替程序能否适用于不同大小与初温的鸡蛋。

## 数据来源

这是使用公开脚本生成的合成数据案例，未开展实物实验，也未使用所引论文的实验数据。指数来自未校准的模型，数值结论只适用于本案例。

{link('data','查看480枚蛋的逐行记录')} · {link('analysis','分析与绘图')} · {link('run','执行与复现记录')}'''
    content={
      'q1': {
        'Q':f'希望同一枚鸡蛋的蛋白凝固、蛋黄柔软且成形。四种煮法中，哪一种更容易同时做到？\n\n{target}\n\n这里把“同一枚蛋同时满足两项”简称为“同时达标”；不是两组鸡蛋的平均值分别合格。',
        'A':f'先分别判断每枚蛋的蛋白和蛋黄，再按 sample_id 取两项的交集。每种煮法以全部120枚为主要分母；缺少读数时不判为成功。\n\n同时报告两项单独达标的数量，检查瓶颈在哪里。\n\n{link("analysis","查看逐枚分类的分析代码")}',
        'E':table+'\n\n'+example+'\n\n65°C恒温有1枚蛋黄达标但蛋白读数缺失，因此不能计为整枚同时达标。\n\n'+link('fig2_joint','图2：两个指标在同一枚蛋上的位置')+' · '+link('data','原始记录'),
        'C':f'冷热交替有 {p["joint_pass_n"]}/120 枚（{p["joint_rate"]:.1%}）同时达标，沸水12分钟有8/120枚，另外两种煮法为0/120。冷热交替在本次比较中更有希望，但多数鸡蛋仍未同时达标。平均蛋白指数{p["white_mean"]:.2f}、蛋黄指数{p["yolk_mean"]:.2f}都在目标内，也不能替代逐枚判断。'},
      'qw': {
        'Q':f'先只看蛋白：哪种煮法能让蛋白充分凝固？本项目用凝固指数 ≥ {white:g} 判断；0–10分中越高表示越凝固。蛋黄是否合适留给另一个子问题。',
        'A':'逐枚比较 white_index 与7.5，分别统计四种煮法的达标数与缺失数。不能用整组的平均指数替代每枚蛋的判定。\n\n'+link('analysis','分析脚本与分类规则'),
        'E':'| 煮法 | 蛋白达标/全部 | 蛋白缺失 |\n|:--|--:|--:|\n'+'\n'.join(f"| {label} | {methods[key]['white_pass_n']}/120 | {methods[key]['n_missing']} |" for key,label in METHODS.items())+'\n\n'+link('fig2_joint','图2：横轴为蛋白凝固指数'),
        'C':'两种沸水程序和冷热交替都能使有读数的蛋白达到7.5；65°C恒温为0/120。对恒温程序来说，蛋白不够凝固是同时达标的主要障碍；其余程序还需要检查蛋黄。'},
      'qy': {
        'Q':f'先只看蛋黄：哪种煮法能让蛋黄柔软但仍能成形？本项目把软度指数 {low:g}–{high:g} 作为目标区间；低于5偏硬，高于8.5偏稀，不能把“更软”直接当作“更好”。',
        'A':'读取每枚蛋的 yolk_index，按含端点的5–8.5区间计数。此处只评价蛋黄，因此即使蛋白读数缺失，已有的蛋黄读数也保留；整枚是否达标再由Q1判断。\n\n'+link('analysis','分析方法')+' · '+link('data','逐枚记录'),
        'E':'| 煮法 | 蛋黄在目标区间/全部 |\n|:--|--:|\n'+'\n'.join(f'| {label} | {counts[key]}/120 |' for key,label in METHODS.items())+'\n\n'+link('fig2_joint','图2：纵轴为蛋黄软度指数'),
        'C':f'沸水6分钟的蛋黄偏稀，12分钟的蛋黄多数偏硬。65°C恒温有{counts["sous_vide"]}/120枚蛋黄在目标区间，冷热交替有{counts["periodic"]}/120枚。恒温虽更容易达到蛋黄目标，却没有兼顾蛋白凝固，因此不能只凭蛋黄选煮法。'},
      'q2': {
        'Q':f'冷热交替煮蛋法换用不同大小、不同初温的鸡蛋后，是否仍能使同一枚蛋的蛋白凝固、蛋黄柔软？\n\n这里的泛化性指：不为每种鸡蛋重新调整程序，检查50、60、70 g，以及下锅前4°C、22°C的鸡蛋能否兼顾这两种口感。下锅温度指鸡蛋初温，不是水温。\n\n具体按同一枚蛋的蛋白凝固指数 ≥ {white:g}、蛋黄软度指数 {low:g}–{high:g} 判断。',
        'A':'按3档质量×2档鸡蛋初温分成6个组合，每格20枚，分别报告蛋白凝固且蛋黄柔软的数量和比例。不能用120枚的总体结果代替每个组合。\n\n这些分层数据混合了4个批次；B04改变了热水停留时间和温控条件，须单独核对，不能把它视为同一固定程序的独立泛化验证。\n\n'+link('analysis','大小、初温与批次的分析来源'),
        'E':strata_table+'\n\n每格20枚包含四个批次，各批每格5枚。B04的加热条件与前三批不同，因此下表先作为跨条件的描述性结果。\n\n'+link('figS1_conditions','补充图：鸡蛋大小与初温')+' · '+link('fig3_robustness','批次过程变化的检查'),
        'C':'六个大小与初温组合中，同时达到蛋白凝固、蛋黄柔软的数量为5/20至11/20（25%–55%），不能认为冷热交替煮蛋法已经广泛适用于这些鸡蛋。批次的过程变化还混在分层结果中；需要固定同一套加热程序，再在不同大小和初温下分别验证。'},
      'qs': {
        'Q':'同样的冷热交替程序，用50、60、70 g的鸡蛋，以及冷藏后4°C、室温22°C的鸡蛋，会不会得到不同的同时达标率？大蛋和冷蛋的内部升温可能更慢，因此需要分开看。',
        'A':'按质量与初温组成6个条件，每格20枚，逐格计算两项同时达标的数量。四个批次在每格都有样本；这里先做描述性比较，不把分层差异直接解释成单个因素的因果作用。',
        'E':strata_table+'\n\n'+link('figS1_conditions','补充图：大小与初温分层')+' · '+link('data','样本身份与条件'),
        'C':'不同大小和初温的达标数存在差异，不能假定一套时间表适用于所有鸡蛋。每格只有20枚且混合四个批次，需在过程条件一致的新批次中分别比较大小和初温。'},
      'qb': {
        'Q':'不同大小和初温的分层结果包含B01–B04。B04的30枚鸡蛋全部达标，但这一批每轮在热水中多停留20秒、温控偏移也不同。它的高比例是否会让我们误以为同一套冷热交替程序适用于所有鸡蛋？',
        'A':'核对B04的过程记录：每240秒中，热水时间由120秒变为140秒，热端占比由50%升至58.3%，总时长仍为32分钟。按批次检查各大小与初温组合，分开报告程序改变前后的结果；未来应固定加热程序后重新验证适用范围。',
        'E':batch_table+'\n\n当前数据中，热水停留变化与温控偏移同时发生，没有独立对照组。\n\n'+link('fig3_robustness','分批结果')+' · '+link('analysis','配置与源码'),
        'C':'B04不是同一固定程序的重复验证，不能用它的30/30证明冷热交替煮蛋法对不同大小与初温的泛化性。热水停留变化与温控偏移也不能相互区分，当前只能把这一批作为过程变化的线索。'},
      'qt': {
        'Q':'如果把蛋白凝固指数下限从7.5放宽到6.5，或收紧到9.0，对不同大小和初温的鸡蛋是否仍会作出相同判断？蛋黄软度区间保持5–8.5不变。',
        'A':'先检查已有的总体敏感性分析，再按大小与初温的6个组合分别重算。改变判据时保留原样本和分母，不挑选最有利的标准；当前输出只完成了按煮法汇总的敏感性分析，分层重算仍待完成。',
        'E':sensitivity_table+'\n\n表中是各煮法的总体数量，没有按大小与初温拆分，不能直接当作泛化性判断的验证。\n\n'+link('fig3_robustness','图3：总体判据敏感性')+' · '+link('analysis','已有重分类脚本'),
        'C':'冷热交替的总体数量在这组判据下由45/120降至43/120，变化较小；但这不能证明每个大小与初温组合的判断都保持不变。需要补充分层敏感性分析，才能判断适用范围是否依赖蛋白凝固的判据。'},
    }
    return {'description':DESCRIPTION,'background':background,'questions':content,'target':target,'method_table':table}
