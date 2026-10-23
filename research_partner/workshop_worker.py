"""Bounded scientific preparation worker; runnable from an exported source capsule.

Receives only a frozen job and copied input assets. Never fits a model or edits
an input. Scientific packages are imported only in this configured subprocess.
"""
from __future__ import annotations
import base64
import csv
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


VERSION = 1
CATEGORIES = {"stimuli", "annotation_cleaning", "neural_preprocessing", "visualization", "experiment"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def safe(root, value):
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("path outside preparation workspace")
    return path


def bounded_int(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


def image_inputs(job, root):
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = 25000000
    result, total_pixels = [], 0
    for ref in job["inputs"]:
        if ref.get("role") == "annotation" or Path(ref["alias"]).suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".ppm"}:
            continue
        path = safe(root, ref["path"])
        with Image.open(path) as source:
            total_pixels += source.width * source.height
            if source.width * source.height > 25000000 or total_pixels > 32000000:
                raise ValueError("image preparation is bounded to 25M pixels/image and 32M pixels/task")
            source.load()
            result.append((ref, source.convert("RGB")))
    if not result or len(result) > 100:
        raise ValueError("requires 1..100 imported images")
    return result


def contact_sheet(images, path):
    from PIL import Image, ImageOps, ImageDraw
    images = images[:12]
    canvas = Image.new("RGB", (min(4, len(images)) * 200, math.ceil(len(images) / 4) * 180), "white")
    draw = ImageDraw.Draw(canvas)
    for i, (name, image) in enumerate(images):
        x, y = (i % 4) * 200, (i // 4) * 180
        canvas.paste(ImageOps.contain(image, (190, 150)), (x + 5, y + 5))
        draw.text((x + 5, y + 158), str(name)[:24], fill="black")
    canvas.save(path)


def ordered_images(images, order):
    if order is None:
        return images
    aliases = [ref["alias"] for ref, _ in images]
    if (not isinstance(order, list) or not all(isinstance(alias, str) for alias in order)
            or len(order) != len(aliases) or len(set(order)) != len(order)
            or set(order) != set(aliases)):
        raise ValueError("explicit order must contain every image alias exactly once")
    lookup = {ref["alias"]: (ref, image) for ref, image in images}
    return [lookup[alias] for alias in order]


def stimuli(job, root, output):
    from PIL import Image, ImageOps
    config = job["config"]
    width = bounded_int(config.get("width", 256), 1, 4096, "width")
    height = bounded_int(config.get("height", 256), 1, 4096, "height")
    mode = config.get("resize", "contain")
    if mode not in {"contain", "pad", "stretch"}:
        raise ValueError("resize must be contain, pad or stretch")
    interpolation = config.get("interpolation", "lanczos")
    if interpolation not in {"lanczos", "nearest"}:
        raise ValueError("unsupported interpolation")
    resample = Image.Resampling.LANCZOS if interpolation == "lanczos" else Image.Resampling.NEAREST
    records, previews = [], []
    images = ordered_images(image_inputs(job, root), config.get("order"))
    if len(images) * width * height > 32000000:
        raise ValueError("transformed image batch exceeds 32M pixels")
    for index, (ref, image) in enumerate(images):
        transformed = (ImageOps.contain(image, (width, height), resample) if mode == "contain" else
                       ImageOps.pad(image, (width, height), resample, color=(0, 0, 0)) if mode == "pad" else
                       image.resize((width, height), resample))
        filename = f"stimulus-{index + 1:04d}.png"
        transformed.save(output / filename)
        records.append({"index": index, "input_sha256": ref["sha"], "input_alias": ref["alias"],
                        "original_size": list(image.size), "output_size": list(transformed.size),
                        "output": filename, "sha256": sha(output / filename)})
        previews.append((filename, transformed))
    write_json(output / "stimulus-manifest.json", {"parameters": config, "ordered_stimuli": records})
    contact_sheet(previews, output / "stimulus-preview.png")
    return {"count": len(records), "dimensions_verified": True, "ordered_input_sha256": [r["input_sha256"] for r in records]}, "stimulus-preview.png", []


def annotation_cleaning(job, root, output):
    from PIL import ImageDraw
    images = image_inputs(job, root)
    candidates = [r for r in job["inputs"] if r.get("role") == "annotation" or Path(r["alias"]).suffix.lower() == ".json"]
    if len(candidates) != 1:
        raise ValueError("requires exactly one annotation JSON asset")
    annotation = json.loads(safe(root, candidates[0]["path"]).read_text())
    rows = annotation.get("annotations") if isinstance(annotation, dict) else annotation
    if not isinstance(rows, list) or len(rows) > 100000:
        raise ValueError("annotation JSON needs at most 100000 rows")
    lookup = {ref["alias"]: (ref, image) for ref, image in images}
    lookup.update({ref["sha"]: (ref, image) for ref, image in images})
    config = job["config"]
    renames = config.get("rename_map", {})
    if not isinstance(renames, dict) or any(v not in lookup for v in renames.values()):
        raise ValueError("rename_map may point only to imported images")
    clean, changes, uncertain, ids = [], [], [], set()
    previews = {r["alias"]: im.copy() for r, im in images}
    for index, original in enumerate(rows):
        if not isinstance(original, dict):
            uncertain.append({"index": index, "reason": "annotation is not an object"})
            clean.append({"original": original, "uncertain": True, "issues": ["invalid_object"]})
            continue
        row = dict(original)
        issues = []
        reference = row.get("image")
        if isinstance(reference, str) and reference in renames:
            row["image"] = renames[reference]
        pair = lookup.get(row.get("image")) if isinstance(row.get("image"), str) else None
        if not pair:
            issues.append("missing_image")
        if not isinstance(row.get("label"), str) or not row.get("label", "").strip():
            issues.append("missing_label")
        row_id = row.get("id")
        if row_id is not None and not isinstance(row_id, (str, int)):
            issues.append("invalid_id")
        elif row_id in ids:
            issues.append("duplicate_id")
        if isinstance(row_id, (str, int)):
            ids.add(row_id)
        bbox = row.get("bbox")
        if bbox is not None:
            if not isinstance(bbox, list) or len(bbox) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in bbox):
                issues.append("invalid_bbox")
            elif pair:
                x, y, width, height = bbox
                imw, imh = pair[1].size
                if width <= 0 or height <= 0:
                    issues.append("nonpositive_bbox")
                elif x < 0 or y < 0 or x + width > imw or y + height > imh:
                    if config.get("clip_bboxes") is True:
                        x0, y0, x1, y1 = max(0, x), max(0, y), min(imw, x + width), min(imh, y + height)
                        if x1 > x0 and y1 > y0:
                            row["bbox"] = [x0, y0, x1 - x0, y1 - y0]
                        else:
                            issues.append("bbox_outside_image")
                    else:
                        issues.append("bbox_outside_image")
        row.update(uncertain=bool(issues), issues=issues)
        if issues:
            uncertain.append({"index": index, "id": row.get("id"), "issues": issues})
        if row != {**original, "uncertain": bool(issues), "issues": issues}:
            changes.append({"index": index, "before": original, "after": row})
        clean.append(row)
        if pair and not issues and row.get("bbox"):
            x, y, w, h = row["bbox"]
            ImageDraw.Draw(previews[pair[0]["alias"]]).rectangle((x, y, x + w, y + h), outline="red", width=2)
    write_json(output / "annotations-cleaned.json", {"annotations": clean, "input_sha256": candidates[0]["sha"]})
    write_json(output / "annotation-differences.json", {"changes": changes, "uncertain": uncertain, "parameters": config})
    contact_sheet(list(previews.items()), output / "annotation-preview.png")
    return {"rows": len(rows), "changed": len(changes), "uncertain": len(uncertain), "dropped": 0}, "annotation-preview.png", ["Uncertain annotations are retained for human review."]


def load_numeric(ref, root, config):
    import numpy as np
    path = safe(root, ref["path"])
    suffix = Path(ref["alias"]).suffix.lower()
    if suffix == ".npy":
        value = np.load(path, allow_pickle=False)
    elif suffix == ".csv":
        value = np.loadtxt(path, delimiter=",", skiprows=bounded_int(config.get("skiprows", 0), 0, 1, "skiprows"))
    elif suffix == ".json":
        data = json.loads(path.read_text())
        value = np.asarray(data.get("data") if isinstance(data, dict) else data, dtype=float)
    elif suffix in {".h5", ".hdf5"}:
        import h5py
        with h5py.File(path, "r") as source:
            name = config["dataset"]
            if not isinstance(name, str) or not name.strip("/"):
                raise ValueError("HDF5 dataset name required")
            current = source
            for part in name.strip("/").split("/"):
                if not isinstance(current.get(part, getlink=True), h5py.HardLink):
                    raise ValueError("HDF5 external/soft links are not accepted")
                current = current[part]
            dataset = current
            if not isinstance(dataset, h5py.Dataset) or dataset.is_virtual or dataset.external:
                raise ValueError("HDF5 virtual/external storage is not accepted")
            if dataset.size > 8000000:
                raise ValueError("neural input exceeds 8 million values")
            value = dataset[...]
    else:
        raise ValueError("neural input must be NPY, numeric CSV, JSON or HDF5")
    value = np.asarray(value, dtype=float)
    if value.ndim not in (1, 2) or value.size == 0 or value.size > 8000000 or not np.isfinite(value).all():
        raise ValueError("neural array must contain 1..8 million finite values, 1D or 2D")
    return value


def neural_preprocessing(job, root, output):
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    if len(job["inputs"]) != 1:
        raise ValueError("one explicitly identified neural input required")
    config = job["config"]
    operation = config.get("operation")
    if operation not in {"baseline_subtract", "select_window"}:
        raise ValueError("explicit operation must be baseline_subtract or select_window; no fitting")
    if type(config.get("samples_axis")) is not int or config.get("samples_axis") not in (0, 1) or not isinstance(config.get("units"), str) or not config.get("units"):
        raise ValueError("samples_axis and physical units are required")
    rate = config.get("sampling_rate_hz")
    if rate is not None and (isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate) or not 0 < rate <= 1000000):
        raise ValueError("sampling_rate_hz must be a known positive value or null for sample-index operations")
    raw = load_numeric(job["inputs"][0], root, config)
    if raw.ndim == 1:
        if config["samples_axis"] != 0:
            raise ValueError("1D data has samples_axis 0")
        raw = raw[:, None]
    elif config["samples_axis"] == 1:
        raw = raw.T
    window = config.get("baseline_samples" if operation == "baseline_subtract" else "window_samples")
    if not isinstance(window, list) or len(window) != 2:
        raise ValueError("explicit half-open sample interval required")
    start = bounded_int(window[0], 0, raw.shape[0] - 1, "window start")
    stop = bounded_int(window[1], start + 1, raw.shape[0], "window stop")
    baseline = raw[start:stop].mean(axis=0)
    result = raw - baseline if operation == "baseline_subtract" else raw[start:stop].copy()
    np.save(output / "preprocessed.npy", result, allow_pickle=False)
    np.savetxt(output / "preprocessed.csv", result, delimiter=",")
    qc = {"operation": operation, "input_shape_samples_channels": list(raw.shape),
          "output_shape_samples_channels": list(result.shape), "sampling_rate_hz": rate,
          "x_axis": "time_seconds" if rate is not None else "sample_index",
          "units": config["units"], "interval_half_open_samples": [start, stop],
          "input_mean_by_channel": raw.mean(axis=0).tolist(),
          "output_mean_by_channel": result.mean(axis=0).tolist(),
          "input_std_by_channel": raw.std(axis=0).tolist(),
          "output_std_by_channel": result.std(axis=0).tolist(), "finite_output": bool(np.isfinite(result).all()),
          "model_fitting": False, "input_sha256": job["inputs"][0]["sha"]}
    if operation == "baseline_subtract":
        qc["subtracted_baseline_by_channel"] = baseline.tolist()
    write_json(output / "neural-qc.json", qc)
    fig, axes = plt.subplots(2, 1, figsize=(8, 5), layout="constrained")
    stride = max(1, raw.shape[0] // 1500)
    axes[0].plot(np.arange(0, raw.shape[0], stride) / (rate if rate is not None else 1), raw[::stride, :min(4, raw.shape[1])])
    stride2 = max(1, result.shape[0] // 1500)
    offset = start if operation == "select_window" else 0
    axes[1].plot((offset + np.arange(0, result.shape[0], stride2)) / (rate if rate is not None else 1), result[::stride2, :min(4, result.shape[1])])
    axes[0].set_title("Input (up to four channels; display subsampled)")
    axes[1].set_title("Prepared output")
    for axis in axes:
        axis.set_xlabel("Time (s)" if rate is not None else "Sample index (sampling rate unspecified)"); axis.set_ylabel(config["units"])
    fig.savefig(output / "neural-preview.png", dpi=130)
    plt.close(fig)
    return qc, "neural-preview.png", ["This is an explicitly authorized preparation transform, not a fit or scientific acceptance."]


def data_rows(job, root):
    if len(job["inputs"]) != 1:
        raise ValueError("visualization requires one CSV/JSON table")
    ref = job["inputs"][0]
    path = safe(root, ref["path"])
    if Path(ref["alias"]).suffix.lower() == ".csv":
        rows = list(csv.DictReader(path.open(newline="")))
    else:
        value = json.loads(path.read_text())
        rows = value.get("rows") if isinstance(value, dict) else value
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100000 or not all(isinstance(r, dict) for r in rows):
        raise ValueError("table must have 1..100000 object rows")
    columns = []
    for key in rows[0]:
        try:
            values = [float(row[key]) for row in rows]
            if all(math.isfinite(v) for v in values):
                columns.append(key)
                for row, value in zip(rows, values):
                    row[key] = value
        except (ValueError, KeyError, TypeError):
            pass
    if len(columns) < 2:
        raise ValueError("requires at least two finite numeric columns")
    return rows, columns


def visualization(job, root, output):
    rows, columns = data_rows(job, root)
    config = job["config"]
    x, y = config.get("x", columns[0]), config.get("y", columns[1])
    if x not in columns or y not in columns:
        raise ValueError("x/y must name numeric columns")
    data = {"rows": rows, "columns": columns, "x": x, "y": y}
    write_json(output / "data.json", data)
    embedded = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    page = '''<!doctype html><meta charset="utf-8"><title>Research data explorer</title>
<style>body{font:16px system-ui;max-width:1000px;margin:30px auto}canvas{border:1px solid #ddd;width:100%}label{margin-right:20px}output{display:block;margin:16px 0}</style>
<h1>Research data explorer</h1><label>X <select id="x"></select></label><label>Y <select id="y"></select></label>
<label>Minimum X <input id="minimum" type="number" step="any"></label><button id="reset">Reset filter</button>
<output id="count"></output><canvas id="plot" width="960" height="500"></canvas><pre id="selected">Click a point to inspect its source row.</pre>
<script>const source=DATA;const xs=document.querySelector('#x'),ys=document.querySelector('#y'),limit=document.querySelector('#minimum'),canvas=document.querySelector('#plot'),ctx=canvas.getContext('2d');let visible=[],points=[];
for(const key of source.columns){for(const select of [xs,ys]){const o=document.createElement('option');o.value=key;o.textContent=key;select.append(o)}}xs.value=source.x;ys.value=source.y;
function draw(){visible=source.rows.map((row,index)=>({row,index})).filter(v=>limit.value===''||v.row[xs.value]>=Number(limit.value));document.querySelector('#count').textContent=visible.length+' / '+source.rows.length+' source rows';ctx.clearRect(0,0,960,500);points=[];if(!visible.length)return;const xv=visible.map(v=>v.row[xs.value]),yv=visible.map(v=>v.row[ys.value]),a=Math.min(...xv),b=Math.max(...xv),c=Math.min(...yv),d=Math.max(...yv);ctx.fillStyle='#195f8c';for(const v of visible){const x=35+(v.row[xs.value]-a)/(b-a||1)*890,y=465-(v.row[ys.value]-c)/(d-c||1)*425;ctx.beginPath();ctx.arc(x,y,3,0,7);ctx.fill();points.push({...v,x,y})}ctx.fillStyle='#111';ctx.fillText(xs.value,450,495);ctx.fillText(ys.value,4,16)}
for(const e of [xs,ys,limit])e.addEventListener('input',draw);document.querySelector('#reset').onclick=()=>{limit.value='';draw()};canvas.onclick=e=>{const r=canvas.getBoundingClientRect(),x=(e.clientX-r.left)*960/r.width,y=(e.clientY-r.top)*500/r.height;const p=points.reduce((best,p)=>!best||(p.x-x)**2+(p.y-y)**2<(best.x-x)**2+(best.y-y)**2?p:best,null);if(p)document.querySelector('#selected').textContent=JSON.stringify({source_row:p.index,...p.row},null,2)};draw();</script>'''.replace("DATA", embedded)
    (output / "visualization.html").write_text(page)
    # A separate numeric preview preserves source data identity without running JS.
    vals = [(float(r[x]), float(r[y])) for r in rows[:2000]]
    ax, bx = min(v[0] for v in vals), max(v[0] for v in vals)
    ay, by = min(v[1] for v in vals), max(v[1] for v in vals)
    circles = ''.join(f'<circle cx="{30+(a-ax)/(bx-ax or 1)*740:.3f}" cy="{370-(b-ay)/(by-ay or 1)*330:.3f}" r="2" fill="#195f8c"/>' for a, b in vals)
    (output / "visualization-preview.svg").write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="420"><rect width="800" height="420" fill="white"/><text x="30" y="22">{html.escape(y)} by {html.escape(x)} — preview of first {len(vals)} rows</text>{circles}<text x="30" y="405">Interactive filtering and point inspection: open visualization.html</text></svg>')
    (output / "serve.py").write_text("from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer\nfrom pathlib import Path\nimport os\nos.chdir(Path(__file__).parent)\nprint('Open http://127.0.0.1:8766/visualization.html', flush=True)\nThreadingHTTPServer(('127.0.0.1',8766),SimpleHTTPRequestHandler).serve_forever()\n")
    return {"rows": len(rows), "numeric_columns": columns, "initial_axes": [x, y], "browser_interaction": "requires actual opening, filtering and selecting"}, "visualization-preview.svg", ["Browser interaction is not automatically signed off by source generation."]


EXPERIMENT_RUNNER = '''from pathlib import Path
import argparse,json,time
p=argparse.ArgumentParser();p.add_argument('--trials',default='trials.json');p.add_argument('--output',default='operator-events.jsonl');a=p.parse_args()
trials=json.loads(Path(a.trials).read_text())['trials'];events=[];start=time.perf_counter_ns()
with Path(a.output).open('x') as output:
 def event(kind,**fields):
  value={'event':kind,'elapsed_ns':time.perf_counter_ns()-start,**fields};events.append(value);output.write(json.dumps(value)+'\\n');output.flush()
 event('session_start',timing_certified=False)
 for index,trial in enumerate(trials):
  event('trial_start',trial=index,stimulus_sha256=trial['sha256'],stimulus=trial['image'])
  response=input('Trial '+str(index+1)+' stimulus '+trial['image']+' response> ')
  event('response',trial=index,response=response)
  event('trial_end',trial=index)
 event('session_end',completed_trials=len(trials))
print(json.dumps({'completed_trials':len(trials),'events':len(events),'timing_certified':False}))
'''


def experiment(job, root, output):
    images = ordered_images(image_inputs(job, root), job["config"].get("order"))
    count = bounded_int(job["config"].get("trials", len(images)), 1, 200, "trials")
    if sum(images[i % len(images)][1].width * images[i % len(images)][1].height for i in range(count)) > 32000000:
        raise ValueError("trial stimulus copies exceed 32M pixels")
    trials, embedded = [], []
    for index in range(count):
        ref, image = images[index % len(images)]
        name = f"trial-stimulus-{index:03d}.png"
        image.save(output / name)
        trials.append({"trial": index, "image": name, "sha256": sha(output / name),
                       "input_sha256": ref["sha"], "input_alias": ref["alias"]})
        embedded.append({**trials[-1], "data_url": "data:image/png;base64," + base64.b64encode((output / name).read_bytes()).decode()})
    write_json(output / "trials.json", {"trials": trials, "timing_certified": False})
    (output / "experiment.py").write_text(EXPERIMENT_RUNNER)
    data = json.dumps(embedded).replace("<", "\\u003c")
    page = '''<!doctype html><meta charset="utf-8"><title>Controlled trial runner</title><style>body{text-align:center;font:18px system-ui;margin:30px}img{max-width:80vw;max-height:65vh}</style><h1>Controlled trial runner</h1><p id="state">Ready. Press Start, then a response key for each stimulus.</p><button id="start">Start</button><button id="download" disabled>Download event log</button><div><img id="stimulus"></div><p>Display, device latency and precise timing are uncalibrated.</p><script>const trials=DATA;let index=-1,events=[],started=false,ready=false,sessionStart=0;const state=document.querySelector('#state'),image=document.querySelector('#stimulus');function log(event,more={}){events.push({event,elapsed_ms:performance.now()-sessionStart,...more})}function next(){ready=false;index++;if(index===trials.length){started=false;image.removeAttribute('src');state.textContent='Completed '+trials.length+' trials';log('session_end',{completed_trials:trials.length,timing_certified:false});document.querySelector('#download').disabled=false;return}image.src=trials[index].data_url;image.onload=()=>{ready=true;log('stimulus_loaded',{trial:index,stimulus_sha256:trials[index].sha256});state.textContent='Trial '+(index+1)+' / '+trials.length+' — press a response key'}}document.querySelector('#start').onclick=()=>{if(started)return;events=[];index=-1;started=true;sessionStart=performance.now();log('session_start',{timing_certified:false});next()};document.addEventListener('keydown',e=>{if(!started||!ready||index<0)return;e.preventDefault();ready=false;log('response',{trial:index,key:e.key});next()});document.querySelector('#download').onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([events.map(e=>JSON.stringify(e)).join('\\n')+'\\n'],{type:'application/x-ndjson'}));a.download='operator-events.jsonl';a.click();URL.revokeObjectURL(a.href)};</script>'''.replace("DATA", data)
    (output / "experiment.html").write_text(page)
    contact_sheet([(r["alias"], im) for r, im in images], output / "experiment-preview.png")
    responses = job["config"].get("responses")
    validation = {"trials": count, "timing_certified": False, "operator_run": "pending"}
    if responses is not None:
        if not isinstance(responses, list) or len(responses) != count or not all(isinstance(r, str) and "\n" not in r and len(r) <= 100 for r in responses):
            raise ValueError("controlled responses must provide one bounded single-line string per trial")
        record = subprocess.run([sys.executable, "experiment.py", "--output", "controlled-events.jsonl"], cwd=output,
                                input="\n".join(responses) + "\n", text=True, capture_output=True, timeout=20)
        (output / "controlled-run.stdout").write_text(record.stdout)
        (output / "controlled-run.stderr").write_text(record.stderr)
        if record.returncode:
            raise ValueError("actual controlled experiment run failed")
        events = [json.loads(line) for line in (output / "controlled-events.jsonl").read_text().splitlines()]
        starts = [event for event in events if event["event"] == "trial_start"]
        logged_responses = [event for event in events if event["event"] == "response"]
        if ([event["event"] for event in events] != ["session_start"] + ["trial_start", "response", "trial_end"] * count + ["session_end"]
                or [(event.get("trial"), event.get("stimulus_sha256"), event.get("stimulus")) for event in starts]
                != [(trial["trial"], trial["sha256"], trial["image"]) for trial in trials]
                or [(event.get("trial"), event.get("response")) for event in logged_responses] != list(enumerate(responses))):
            raise ValueError("trial event postconditions failed")
        validation.update(controlled_run=True, input_mode="explicit_controlled_responses", logged_responses=count,
                          trial_order_verified=True,
                          operator_run="browser/physical operator interaction still pending")
    write_json(output / "experiment-validation.json", validation)
    return validation, "experiment-preview.png", ["Controlled script responses are not a human-use claim. Device latency and precise timing are unmeasured."]


def execute(job, root):
    root = Path(root).resolve()
    if job.get("version") != VERSION or job.get("category") not in CATEGORIES:
        raise ValueError("unsupported preparation job/version")
    if not isinstance(job.get("inputs"), list) or not 1 <= len(job["inputs"]) <= 101:
        raise ValueError("requires 1..101 copied input assets")
    aliases = [r["alias"] for r in job["inputs"]]
    if len(aliases) != len(set(aliases)):
        raise ValueError("input aliases must be unique")
    for ref in job["inputs"]:
        path = safe(root, ref["path"])
        if not path.is_file() or sha(path) != ref["sha"] or not path.is_relative_to(root / "inputs"):
            raise ValueError("copied input integrity or location mismatch")
    output = root / "outputs"
    output.mkdir(exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("output directory must be empty; retain partial results and choose a new attempt")
    started = time.time()
    quality, preview, limitations = globals()[job["category"]](job, root, output)
    for ref in job["inputs"]:
        if sha(safe(root, ref["path"])) != ref["sha"]:
            raise ValueError("input modified during execution")
    environment = {"python": sys.version, "executable": sys.executable, "platform": platform.platform(), "worker_sha256": sha(__file__)}
    write_json(output / "environment.json", environment)
    eligible = all(r.get("provenance") in {"authorized_real", "public_real"} and not r.get("synthetic") for r in job["inputs"])
    manifest = {"version": VERSION, "category": job["category"], "inputs": job["inputs"], "config": job["config"],
                "quality": quality, "limitations": limitations, "acceptance_eligible_input": eligible,
                "scientific_approval": False, "user_acceptance": "pending", "elapsed_seconds": time.time() - started,
                "environment": environment, "preview": "outputs/" + preview}
    write_json(output / "preparation-manifest.json", manifest)
    files = [{"path": str(p.relative_to(root)), "sha256": sha(p), "size": p.stat().st_size} for p in sorted(output.iterdir()) if p.is_file()]
    return {"ok": True, "job_sha256": hashlib.sha256(json.dumps(job, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            "files": files, "manifest": manifest}


def main(argv=None):
    argv = argv or sys.argv[1:]
    if len(argv) != 1:
        raise SystemExit("usage: workshop_worker.py JOB.json")
    request = Path(argv[0]).resolve()
    try:
        result = execute(json.loads(request.read_text()), request.parent)
        write_json(request.parent / "result.json", result)
        print(json.dumps({"ok": True, "category": result["manifest"]["category"], "files": len(result["files"])}))
    except Exception as exc:
        write_json(request.parent / "failure.json", {"ok": False, "error": type(exc).__name__ + ": " + str(exc)})
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
