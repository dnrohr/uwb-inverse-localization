"""Retained paired M6 acceptance matrix; never overwrite an earlier attempt."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback
import uuid
import shutil

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from uwb import m6,m6_sweeps
from uwb.experiments import save_json


def acceptance_cases():
    base={"samples":12,"beacon_layout":{"count":4,"geometry":"equal"}}
    cases=[]
    for scenario in ("informative","nearly_collinear","straight_line"):
        for noise in (0.,.03):
            config={**base,"scenario":scenario,"noise_std_m":noise}
            if scenario=="nearly_collinear":config["beacon_layout"]={"count":4,"geometry":"near_collinear"}
            cases.append((f"masking_{scenario}_{'exact' if noise==0 else 'noisy'}",config,{},"nlos_prevalence",[0.,.15]))
    for noise in (0.,.03):
        cases.append((f"surveyed_{'exact' if noise==0 else 'noisy'}",{**base,"noise_std_m":noise},{"mode":"known_map"},"nlos_prevalence",[0.,.15]))
    cases.extend([
        ("burst_duration",{**base,"noise_std_m":.03,"contamination":{"nlos":{"prevalence":.12,"affected_beacons":[1,3]}}},{},"burst_duration_cycles",[1,3]),
        ("beacon_offsets",{**base,"noise_std_m":.03},{},"offset_m",[0.,.15]),
        ("correlated_noise",{**base,"contamination":{"correlation":.7}},{},"correlated_noise_std_m",[0.,.06]),
        ("quantization",copy.deepcopy(base),{},"quantization_m",[0.,.1]),
        ("dropout",{**base,"noise_std_m":.03},{},"dropout_probability",[0.,.2]),
        # Combining follows all isolated-source cases above and cannot isolate a cause.
        ("combined_sources",{**base,"noise_std_m":.03,"contamination":{"offsets_m":[0.,.03,.06,.09],"correlated_noise_std_m":.03,"correlation":.6,"quantization_m":.05,"dropout_probability":.1,"nlos":{"burst_duration_cycles":2}}},{},"nlos_prevalence",[0.,.1])])
    return cases


def reaggregate(source):
    """Versioned derived-table migration; retain source runs/observations bytewise.

    Used when the orchestrator changes display aggregates while a long retained
    matrix is already running. This never refits or regenerates any experiment.
    """
    source=Path(source);source=source if source.is_absolute() else ROOT/source
    original=json.loads((source/"acceptance_summary.json").read_text(encoding="utf-8"))
    assert original["status"]=="passed" and not original["errors"]
    directory=ROOT/"evidence/m6"/("acceptance_reviewed_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:8])
    for child in ("sweeps","fixtures"):(directory/child).mkdir(parents=True)
    summary=copy.deepcopy(original)
    summary.update(status="incomplete",directory=str(directory.relative_to(ROOT)),sweeps=[],fixtures=[],migration={"source":str(source.relative_to(ROOT)),"definition":"Only derived start_table/aggregates and CSV rebuilt from identical retained source runs using final M6 aggregate code. No fitting, no source generation. Original attempts, requests and checkpoints remain at source.","source_summary_sha256":hashlib.sha256((source/"acceptance_summary.json").read_bytes()).hexdigest(),"source_run_equality":True})
    def record():(directory/"acceptance_summary.json").write_text(json.dumps(summary,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    record()
    try:
        for entry in original["sweeps"]:
            old_path=ROOT/entry["path"];data=json.loads(old_path.read_text(encoding="utf-8"))
            assert hashlib.sha256(old_path.read_bytes()).hexdigest()==entry["sha256"]
            source_runs=copy.deepcopy(data["entries"])
            source_entries_hash=hashlib.sha256(json.dumps(source_runs,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
            data.update(m6_sweeps.aggregate_sweep(data))
            assert data["entries"]==source_runs
            path=directory/"sweeps"/old_path.name;m6_sweeps.save_artifact(path,data)
            assert m6_sweeps.load_artifact(path)==data
            (directory/"sweeps"/(path.stem+".csv")).write_text(m6_sweeps.table_csv(data),encoding="utf-8")
            row=copy.deepcopy(entry);row.update(path=str(path.relative_to(ROOT)),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),aggregates=data["aggregates"],source_path=entry["path"],source_sha256=entry["sha256"],unchanged_source_entries_sha256=source_entries_hash)
            summary["sweeps"].append(row);record()
        for entry in original["fixtures"]:
            old_path=ROOT/entry["path"];data=json.loads(old_path.read_text(encoding="utf-8"));m6.validate_run(data)
            assert hashlib.sha256(old_path.read_bytes()).hexdigest()==entry["sha256"]
            path=directory/"fixtures"/old_path.name;shutil.copy2(old_path,path)
            assert path.read_bytes()==old_path.read_bytes()
            row=copy.deepcopy(entry);row.update(path=str(path.relative_to(ROOT)),source_path=entry["path"])
            summary["fixtures"].append(row);record()
        summary["status"]="passed";record()
    except Exception as exc:
        summary["status"]="failed";summary["errors"].append({"stage":"derived_table_migration","error":str(exc),"traceback":traceback.format_exc()});record();raise
    print(str(directory.relative_to(ROOT))+": "+summary["status"])


def main():
    directory=ROOT/"evidence/m6"/("acceptance_"+time.strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:8])
    for child in ("sweeps","fixtures","checkpoints"):(directory/child).mkdir(parents=True,exist_ok=True)
    summary={"status":"incomplete","directory":str(directory.relative_to(ROOT)),"sweeps":[],"fixtures":[],"errors":[],"benchmark_definition":{"samples":12,"starts_per_run":2,"paired_measurement_seeds":[7,8],"losses":["gaussian","huber","cauchy","hard_rejection"],"solver":"trf","max_nfev_per_stage":300,"wall_scope":"Whole sweep including diagnostics, validation and per-entry JSON checkpoint saves; excludes final CSV export. Solver runtime separately retained per attempted start and includes hard-rejection pilot.","geometry_scope":"Original canonical gauge and proper rigid alignment only; no scale/reflection fitting. Informative/weak/straight-line exact and noisy cells repeated across identical-data paired losses. Known-map cells explicitly use surveyed truth map."}}
    def record():(directory/"acceptance_summary.json").write_text(json.dumps(summary,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    record()
    variants=[{"label":loss,"options":{"loss":loss}} for loss in ("gaussian","huber","cauchy","hard_rejection")]
    for name,config,options,factor,values in acceptance_cases():
        started=time.perf_counter()
        request={"base_experiment":config,"options":{"mode":"joint","tag_height_model":"fixed","starts":2,"max_nfev":300,**options},"factor":factor,"values":values,"seeds":[7,8],"variants":variants}
        (directory/"sweeps"/(name+"_request.json")).write_text(json.dumps(request,indent=2,allow_nan=False),encoding="utf-8")
        try:
            def checkpoint(artifact):m6_sweeps.save_artifact(directory/"checkpoints"/(name+".json"),artifact)
            artifact=m6_sweeps.run_sweep(request,on_progress=checkpoint)
            path=directory/"sweeps"/(name+".json");m6_sweeps.save_artifact(path,artifact)
            reopened=m6_sweeps.load_artifact(path);assert reopened==artifact
            (directory/"sweeps"/(name+".csv")).write_text(m6_sweeps.table_csv(artifact),encoding="utf-8")
            statuses={status:sum(start["status"]==status for entry in artifact["entries"] for start in entry["run"]["starts"]) for status in ("success","not_converged","failed")}
            masking=[]
            for entry in artifact["entries"]:
                for start in entry["run"]["starts"]:
                    if start["estimate"] is None:continue
                    diag=start["diagnostics"];geo=diag["evaluation"]["raw"]
                    if diag["range_rmse_m"]<.05 and max(geo["position_rmse_m"],geo["map_rmse_m"])>.25:
                        masking.append({"entry_index":entry["index"],"start_index":start["index"],"variant":entry["variant"],"seed":entry["seed"],"range_rmse_m":diag["range_rmse_m"],"position_rmse_m":geo["position_rmse_m"],"map_rmse_m":geo["map_rmse_m"]})
            summary["sweeps"].append({"name":name,"path":str(path.relative_to(ROOT)),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"runs":len(artifact["entries"]),"starts":len(artifact["start_table"]),"wall_s":time.perf_counter()-started,"status_counts":statuses,"aggregates":artifact["aggregates"],"low_residual_distorted_geometry_examples":masking})
        except Exception as exc:
            error={"name":name,"request":request,"error":str(exc),"traceback":traceback.format_exc(),"wall_s":time.perf_counter()-started};summary["errors"].append(error)
            (directory/"sweeps"/(name+"_infrastructure_error.json")).write_text(json.dumps(error,indent=2),encoding="utf-8")
        record();print(name+": saved",flush=True)
    fixtures=[
        ("forced_nonconvergence",{"samples":12,"noise_std_m":.03},{"max_nfev":1},None),
        ("invalid_initial_geometry",{"samples":12},{},[{"initialization_error":"Intentional retained acceptance failure"}]*2),
        ("all_dropout",{"samples":12,"contamination":{"dropout_probability":1.}},{},None),
        ("asynchronous",{"samples":12,"acquisition":{"spacing_s":.02,"timestamp_offset_s":.01,"delivery_latency_s":.2},"contamination":{"nlos":{"prevalence":.1}}},{"prior_sigma_m":.3},None),
        ("height_prior",{"samples":12,"truth_height":{"type":"excursion"},"contamination":{"nlos":{"prevalence":.1}}},{"mode":"known_map","tag_height_model":"soft","height_prior_sigma_m":.2,"prior_sigma_m":.3},None),
        ("spatial_geometry",{"samples":12,"beacon_layout":{"count":6,"geometry":"diverse"},"truth_height":{"type":"spatial"},"contamination":{"nlos":{"prevalence":.1}}},{"tag_height_model":"free","beacon_height_model":"independent"},None)]
    for name,config,options,initials in fixtures:
        try:
            exp=m6.generate_experiment(config);reference=None
            for loss in ("gaussian","huber","cauchy","hard_rejection"):
                opts={"starts":2,"max_nfev":300,"tag_height_model":"fixed",**options,"loss":loss}
                paired=initials if initials is not None else m6.compatible_initial_geometries(reference,exp,opts) if reference else None
                run=m6.solve_experiment(exp,opts,initial_geometries=paired)
                if reference is None:reference=run
                path=directory/"fixtures"/(name+"_"+loss+".json");save_json(path,run)
                reopened=json.loads(path.read_text(encoding="utf-8"));m6.validate_run(reopened);assert reopened==run
                summary["fixtures"].append({"name":name,"loss":loss,"path":str(path.relative_to(ROOT)),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"status":run["status"],"starts":len(run["starts"]),"status_counts":{status:sum(start["status"]==status for start in run["starts"]) for status in ("success","not_converged","failed")}});record()
        except Exception as exc:
            summary["errors"].append({"name":name,"error":str(exc),"traceback":traceback.format_exc()});record()
    summary["run_count"]=sum(row["runs"] for row in summary["sweeps"])+len(summary["fixtures"])
    summary["attempt_count"]=sum(row["starts"] for row in summary["sweeps"]+summary["fixtures"])
    summary["status_counts"]={status:sum(row["status_counts"][status] for row in summary["sweeps"]+summary["fixtures"]) for status in ("success","not_converged","failed")}
    summary["masking_example_count"]=sum(len(row["low_residual_distorted_geometry_examples"]) for row in summary["sweeps"])
    summary["status"]="failed" if summary["errors"] else "passed";record()
    print(str(directory.relative_to(ROOT))+": "+summary["status"],flush=True)
    if summary["errors"]:raise SystemExit(1)


if __name__=="__main__":
    if len(sys.argv)>2 and sys.argv[1]=="--reaggregate":reaggregate(sys.argv[2])
    else:main()
