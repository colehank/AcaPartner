"""Trusted mathematical glyph renderer in the configured scientific runtime."""
import json
import sys
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
from matplotlib.mathtext import math_to_image
from matplotlib.font_manager import FontProperties

def main():
    work=Path(sys.argv[1]);values=json.loads((work/'input.json').read_text());result=[]
    matplotlib.rcParams['svg.fonttype']='path'
    for i,formula in enumerate(values):
        name=f'formula-{i}.svg'
        try:
            math_to_image('$'+formula.strip().replace('\n',' ')+'$',work/name,prop=FontProperties(size=14),format='svg',dpi=144)
            result.append({'formula':formula,'file':name})
        except (ValueError,RuntimeError) as error:result.append({'formula':formula,'error':str(error)})
    (work/'result.json').write_text(json.dumps(result))
if __name__=='__main__':main()
