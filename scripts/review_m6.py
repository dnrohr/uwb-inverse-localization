"""Independent M6 equations, boundary checks and retained artifact review.

Each invocation saves a unique attempt before checking anything; failures remain.
"""
from pathlib import Path
from datetime import datetime, timezone
import copy
import json
import math
import sys
import traceback
import uuid
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from uwb import m5
from scripts.review_m5 import _data, _direct, _direct_priors


def independent_loss(residuals, loss, scale):
    """Return per-row cost, dcost/dr, IRLS weight and signed curvature.

    Written in scalar physical residual units rather than the implementation's
    squared standardized rho coordinates. Scale is dimensionless sigma units.
    """
    rows = []
    for value in np.asarray(residuals, dtype=float):
        r = float(value); a = abs(r); c = float(scale)
        if loss == "gaussian": cost, gradient, weight, curvature = r*r/2, r, 1., 1.
        elif loss == "huber":
            cost = r*r/2 if a <= c else c*a-c*c/2
            gradient = r if a <= c else math.copysign(c, r)
            weight = 1. if a <= c else c/a
            curvature = 1. if a <= c else 0.
        elif loss == "soft_l1":
            norm = math.hypot(c, r)
            cost = c*r*r/(norm+c)
            gradient, weight, curvature = c*r/norm, c/norm, (c/norm)**3
        elif loss == "cauchy":
            ratio = r/c; denominator = 1+ratio*ratio
            cost = c*c*math.log1p(ratio*ratio)/2
            gradient, weight, curvature = r/denominator, 1/denominator, (1-ratio*ratio)/(denominator*denominator)
        else: raise ValueError(loss)
        rows.append((cost, gradient, weight, curvature))
    return np.asarray(rows).T


def _check_losses():
    from uwb import m6
    results = []
    for loss in ("gaussian", "huber", "soft_l1", "cauchy"):
        for scale in (.1, 2., 20.):
            r = np.array([-100., -3.1*scale, -.8*scale, -1e-9, 0., 1e-9, .8*scale, 3.1*scale, 100.])
            cost, gradient, weight, curvature = independent_loss(r, loss, scale)
            transformed, derivative = m6.range_transform(r, loss, scale)
            actual_weight, actual_curvature = m6.loss_statistics(r, loss, scale)
            np.testing.assert_allclose(.5*transformed**2, cost, rtol=4e-12, atol=1e-16)
            np.testing.assert_allclose(transformed*derivative, gradient, rtol=4e-12, atol=1e-13)
            np.testing.assert_allclose(actual_weight, weight, rtol=4e-12, atol=1e-13)
            np.testing.assert_allclose(actual_curvature, curvature, rtol=4e-12, atol=1e-13)
            finite = (m6.range_transform(r+1e-6,loss,scale)[0]-m6.range_transform(r-1e-6,loss,scale)[0])/2e-6
            np.testing.assert_allclose(derivative,finite,atol=2e-7,rtol=2e-7)
            results.append({"loss":loss,"scale_sigma":scale,"max_cost_disagreement":float(np.max(abs(.5*transformed**2-cost))),"max_derivative_disagreement":float(np.max(abs(finite-derivative)))})
    return {"cases":results,"cauchy_negative_curvature_preserved":True,"huber_kink_convention":"inside at |r|=scale; second derivative not mathematically defined at kink"}


def _check_objectives():
    from uwb import m6
    tags, anchors, times, observations = _data(5)
    for i, row in enumerate(observations): row["range_m"] += .11*math.sin(i)+(.8 if i%11==0 else 0.)
    results=[]
    for mode,tag_model in (("joint","fixed"),("known_map","soft")):
        for coordinate in ("h","q") if tag_model=="fixed" else ("h",):
            for loss in ("gaussian","huber","soft_l1","cauchy"):
                opts={"mode":mode,"tag_height_model":tag_model,"height_parameterization":coordinate,"prior_sigma_m":.4,"height_prior_sigma_m":.2,"loss":loss,"loss_scale_sigma":2.3}
                problem=m6.build_problem(observations,times,beacon_count=5,surveyed_beacons=anchors if mode=="known_map" else None,**opts)
                base=problem.base if hasattr(problem,"base") else problem
                x=base.pack(tags,anchors)
                # Nonzero motion/height priors make accidental prior robustness visible.
                x[:6]+=[.03,-.02,.12,.03,-.07,.04]
                if tag_model=="soft": x[2]=.4
                raw,raw_j=_direct(x,base); priors,prior_j=_direct_priors(x,base)
                costs,gradient,_,_=independent_loss(raw,loss,2.3)
                expected_cost=float(sum(costs)+.5*priors@priors)
                expected_gradient=raw_j.T@gradient+prior_j.T@priors
                rr=m6.residuals(x,problem); jj=m6.jacobian(x,problem)
                np.testing.assert_allclose(.5*rr@rr,expected_cost,atol=1e-9,rtol=2e-12)
                np.testing.assert_allclose(jj.T@rr,expected_gradient,atol=1e-8,rtol=3e-12)
                np.testing.assert_allclose(rr[len(raw):],priors,atol=1e-12,rtol=1e-13)
                np.testing.assert_allclose(jj[len(raw):],prior_j,atol=1e-12,rtol=1e-13)
                finite=np.zeros_like(jj)
                for column in range(len(x)):
                    step=1e-6*max(abs(x[column]),1.); delta=np.zeros_like(x);delta[column]=step
                    finite[:,column]=(m6.residuals(x+delta,problem)-m6.residuals(x-delta,problem))/(2*step)
                np.testing.assert_allclose(jj,finite,atol=2e-5,rtol=3e-6)
                results.append({"mode":mode,"tag_height_model":tag_model,"coordinate":coordinate,"loss":loss,"objective":expected_cost,"prior_objective":float(.5*priors@priors),"max_jacobian_error":float(np.max(abs(jj-finite)))})
    return {"cases":results,"prior_terms_checked_independently":True}


def _check_information_accounting():
    from uwb import m6
    tags,anchors,times,observations=_data(5)
    results=[]
    for coordinate in ("h","q"):
        for loss in ("gaussian","huber","soft_l1","cauchy","hard_rejection"):
            opts=m6.validate_options({"tag_height_model":"fixed","prior_sigma_m":.3,"height_parameterization":coordinate,"loss":loss})
            problem=m6.build_problem(observations,times,beacon_count=5,**opts)
            x=problem.pack(tags,anchors);x[:4]+=[.3,-.1,.6,-.2]
            raw,j=_direct(x,problem);pr,pj=_direct_priors(x,problem)
            mask=np.arange(len(raw))%3!=0 if loss=="hard_rejection" else None
            diag=m6._fit_diagnostics(x,problem,opts,mask=mask,pilot=raw if mask is not None else None)
            if mask is None: _,_,weights,curvature=independent_loss(raw,loss,opts["loss_scale_sigma"])
            else: weights=mask.astype(float);curvature=weights.copy()
            # Convert native q derivative back to the M4 signed metre coordinate.
            if coordinate=="q":j[:,problem.height_index]*=2*np.sqrt(x[problem.height_index])
            physical_matrices={"original_measurement":j,"retained_measurement":j*np.sqrt(weights)[:,None],"prior_augmented":np.vstack((j*np.sqrt(weights)[:,None],pj)),"positive_part_robust_curvature":j*np.sqrt(np.maximum(curvature,0))[:,None]}
            scale=max(float(np.median(abs(problem.ranges_m))),1.)
            for key,matrix in physical_matrices.items():
                singular=np.linalg.svd(matrix*scale,compute_uv=False)
                info=diag["information"][key]
                np.testing.assert_allclose(info["singular_values"],singular,atol=2e-10,rtol=2e-12)
                rank=int(np.count_nonzero(singular>singular[0]*1e-8))
                assert info["rank"]==rank and info["full_column_rank"]==(rank==problem.parameter_count)
                assert info["prior_residual_count"]==(len(pr) if key=="prior_augmented" else 0)
            flags=weights==0 if loss=="hard_rejection" else weights<opts["weight_decision_threshold"]
            assert diag["coverage"]["original_count"]==len(raw)
            assert diag["coverage"]["retained_count"]==int(sum(weights>0))
            assert diag["coverage"]["flagged_count"]==int(sum(flags))
            for key,ids in (("by_beacon",problem.beacon_ids),("by_epoch",problem.epochs)):
                for row in diag["coverage"][key]:
                    selected=ids==row["id"]
                    assert row["original_count"]==int(sum(selected))
                    assert row["retained_count"]==int(sum(selected&(weights>0)))
                    np.testing.assert_allclose(row["effective_weight_sum"],sum(weights[selected]),atol=1e-12)
            for i,row in enumerate(diag["observation_decisions"]):
                assert row["flagged"]==bool(flags[i]) and row["rejected"]==bool(weights[i]==0)
                np.testing.assert_allclose([row["weight"],row["residual_sigma"]],[weights[i],raw[i]],atol=1e-12)
            results.append({"coordinate":coordinate,"loss":loss,"original_rank":diag["information"]["original_measurement"]["rank"],"retained_rank":diag["information"]["retained_measurement"]["rank"],"original_count":len(raw),"retained_count":int(sum(weights>0)),"flagged_count":int(sum(flags))})
    records=[{"retained_index":0,"nlos":True},{"retained_index":1,"nlos":False},{"retained_index":2,"nlos":True},{"retained_index":3,"nlos":False},{"retained_index":None,"nlos":True}]
    metrics=m6.rejection_evaluation([{"flagged":f} for f in (True,True,False,False)],records)
    for key in ("true_positive","false_positive","false_negative","true_negative","dropped_count_excluded"):assert metrics[key]==1
    for key in ("precision","recall","false_positive_rate"):assert metrics[key]==.5
    empty=m6.rejection_evaluation([],[])
    assert empty["precision"] is None and empty["recall"] is None and empty["false_positive_rate"] is None
    return {"cases":results,"confusion_matrix":metrics,"empty_denominators":empty,"interpretation":"Frozen weighted local Jacobian information checked independently; positive-part robust curvature excludes negative scalar curvature and geometry second derivatives. No uniqueness inference."}


def _check_replay_isolation_equivalence():
    from uwb import m6
    config={"samples":12,"noise_std_m":.02,"acquisition":{"spacing_s":.01,"timestamp_offset_s":.002,"delivery_latency_s":.1},"contamination":{"nlos":{"prevalence":.2,"magnitude_m":.7,"burst_duration_cycles":3,"affected_beacons":[1,3]},"offsets_m":[0.,.02,-.01,.03],"correlated_noise_std_m":.03,"correlation":.6,"quantization_m":.01,"dropout_probability":.2}}
    exp=m6.generate_experiment(config)
    assert exp==m6.generate_experiment(config)
    source=exp["contamination_reference"]["source_experiment"]
    inputs=exp["estimator_input"]["observations"]
    kept=0
    for row in exp["contamination_reference"]["records"]:
        original=source["estimator_input"]["observations"][row["source_index"]]
        expected=original["range_m"]+row["offset_m"]+row["correlated_noise_m"]+row["nlos_bias_m"]+row["quantization_error_m"]
        np.testing.assert_allclose(row["range_m"],expected,atol=2e-15,rtol=1e-15)
        if row["nlos"]:assert row["beacon_id"] in (1,3) and row["nlos_bias_m"]==.7
        if row["retained_index"] is not None:
            assert row["retained_index"]==kept
            current=inputs[kept];assert current["range_m"]==row["range_m"]
            assert set(current)==set(original)
            for key in ("actual_time_s","assumed_time_s","delivery_time_s"):
                if key in original: assert current[key]==original[key]
            kept+=1
    equality=[]
    for noise in (0.,.02):
        clean=m6.generate_experiment({"samples":12,"noise_std_m":noise})
        observations=clean["estimator_input"]["observations"];times=clean["estimator_input"]["times_s"]
        for solver in ("trf","lm"):
            for coordinate in ("h","q"):
                options={"solver":solver,"height_parameterization":coordinate,"tag_height_model":"fixed","starts":1,"max_nfev":300}
                old=m5.fit_observations(observations,times,beacon_count=4,**options)[0]
                current=m6.fit_observations(observations,times,beacon_count=4,**options)[0]
                assert old["status"]==current["status"] and old["initial"]==current["initial"]
                np.testing.assert_allclose(old["solver"]["final_parameters"],current["solver"]["final_parameters"],atol=2e-9,rtol=2e-9)
                np.testing.assert_allclose(old["solver"]["final_objective"],current["solver"]["final_objective"],atol=1e-9,rtol=1e-10)
                equality.append({"noise_std_m":noise,"solver":solver,"coordinate":coordinate,"status":current["status"],"parameter_max_disagreement":float(np.max(abs(np.asarray(old["solver"]["final_parameters"])-current["solver"]["final_parameters"])))})
    poisoned=copy.deepcopy(observations)
    for row in poisoned: row.update(nlos=True,clean_range_m=-1e8,truth={"trajectory":"poison"},actual_time_s=-1e8,delivery_time_s=1e8)
    isolation=[]
    for loss in ("gaussian","huber","soft_l1","cauchy","hard_rejection"):
        options={"loss":loss,"tag_height_model":"fixed","starts":1,"max_nfev":150}
        normal=m6.fit_observations(observations,times,beacon_count=4,**options)[0]
        poison=m6.fit_observations(poisoned,times,beacon_count=4,**options)[0]
        assert normal["status"]==poison["status"] and normal["initial"]==poison["initial"] and normal["estimate"]==poison["estimate"]
        assert normal["diagnostics"]==poison["diagnostics"]
        isolation.append({"loss":loss,"status":normal["status"],"exact_initial_estimate_diagnostics_equality":True})
    return {"deterministic_full_experiment":True,"retained_observations":kept,"source_observations":len(source["estimator_input"]["observations"]),"component_sum_and_timestamp_preservation":True,"gaussian_m5_equivalence":equality,"poisoned_label_clean_reference_actual_delivery_isolation":isolation}


def _check_support_failures():
    from uwb import m6
    rejected=[]
    for label,opts in (("unknown_loss",{"loss":"oracle"}),("unknown_solver",{"solver":"dogbox"}),("unsupported_q_spatial",{"tag_height_model":"free","height_parameterization":"q"}),("unsupported_coupled_bounds",{"tag_height_model":"free","beacon_height_model":"independent","below_beacons":True})):
        try:m6.validate_options(opts)
        except ValueError:rejected.append(label)
        else:raise AssertionError(label+" silently accepted")
    tags,anchors,times,obs=_data(4)
    opts=m6.validate_options({"solver":"lm","loss":"hard_rejection","starts":1})
    problem=m6.build_problem(obs,times,beacon_count=4,**opts);x=problem.pack(tags,anchors)
    mask=np.zeros(len(obs),dtype=bool);mask[0]=True
    try:m6._optimize(problem,opts,x,mask)
    except ValueError as exc:assert "retained" in str(exc)
    else:raise AssertionError("LM counted rejected zero rows as information")
    failures=m6.fit_observations(obs,times,beacon_count=4,starts=2,initial_geometries=[{"initialization_error":"independent review intentional invalid physical start"}]*2)
    assert len(failures)==2 and all(s["status"]=="failed" and s["estimate"] is None and s["initial"] is not None for s in failures)
    return {"unsupported_explicitly_rejected":rejected,"lm_rejected_zero_rows_excluded":True,"invalid_physical_starts_retained":len(failures),"m5_bounds_contract":"Existing strict-interior exponential LM transform retained; every saved final parameter checked against its declared bounds in artifact review."}


def _check_artifacts(source):
    from uwb import m6,m6_sweeps
    import hashlib
    source=Path(source);source=source if source.is_absolute() else ROOT/source
    summary=json.loads((source/"acceptance_summary.json").read_text(encoding="utf-8"))
    assert summary["status"]=="passed" and not summary["errors"]
    files=[];statuses={};count=0;finite=0;paired=0;maximum_r_error=0.;maximum_j_error=0.;alternative_runs=[];paired_changes=[];pilot_statuses={"success":0,"not_converged":0}
    for record in summary["sweeps"]+summary["fixtures"]:
        path=ROOT/record["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest()==record["sha256"]
        # Offline reopening is required to use retained source observations.
        with patch.object(m6,"solve_experiment",side_effect=AssertionError("offline review must not solve")),patch.object(m6,"generate_experiment",side_effect=AssertionError("offline review must not generate source")):
            if path.parent.name=="sweeps":
                artifact=m6_sweeps.load_artifact(path);runs=[entry["run"] for entry in artifact["entries"]]
                assert len(artifact["start_table"])==sum(len(run["starts"]) for run in runs)
                for entry in artifact["entries"]:
                    if entry["initial_reference_entry"] is None:continue
                    reference=artifact["entries"][entry["initial_reference_entry"]]["run"]
                    assert entry["run"]["experiment"]==reference["experiment"]
                    for left,right in zip(reference["starts"],entry["run"]["starts"]):
                        for field in ("knot_trajectory","beacons"):
                            np.testing.assert_allclose(left["initial"][field],right["initial"][field],atol=5e-11,rtol=1e-12)
                    paired+=1
                for value in artifact["config"]["values"]:
                    for variant in artifact["config"]["variants"][1:]:
                        changes=[];unavailable=0
                        for seed in artifact["config"]["seeds"]:
                            left=next(e["run"] for e in artifact["entries"] if e["value"]==value and e["seed"]==seed and e["variant"]==artifact["config"]["variants"][0]["label"])
                            right=next(e["run"] for e in artifact["entries"] if e["value"]==value and e["seed"]==seed and e["variant"]==variant["label"])
                            for a,b in zip(left["starts"],right["starts"]):
                                if a["estimate"] is None or b["estimate"] is None:unavailable+=1;continue
                                ga=a["diagnostics"]["evaluation"]["raw"];gb=b["diagnostics"]["evaluation"]["raw"]
                                changes.append({"seed":seed,"start_index":a["index"],"position_rmse_delta_m":gb["position_rmse_m"]-ga["position_rmse_m"],"map_rmse_delta_m":gb["map_rmse_m"]-ga["map_rmse_m"]})
                        paired_changes.append({"sweep":record["name"],"value":value,"variant":variant["label"],"reference":artifact["config"]["variants"][0]["label"],"finite_pairs":len(changes),"unavailable_pairs":unavailable,"position_rmse_delta_median_m":float(np.median([p["position_rmse_delta_m"] for p in changes])) if changes else None,"map_rmse_delta_median_m":float(np.median([p["map_rmse_delta_m"] for p in changes])) if changes else None,"position_improved_pairs":sum(p["position_rmse_delta_m"] < -1e-6 for p in changes),"position_worsened_pairs":sum(p["position_rmse_delta_m"] > 1e-6 for p in changes),"pairs":changes})
            else:
                run=json.loads(path.read_text(encoding="utf-8"));m6.validate_run(run);runs=[run]
        per_file=0
        for run in runs:
            if run["diagnostics"].get("distinct_low_residual_solution_count",0)>1:
                alternative_runs.append({"path":str(path.relative_to(ROOT)),"loss":run["options"]["loss"],"count":run["diagnostics"]["distinct_low_residual_solution_count"],"measurement_seed":run["experiment"]["config"]["seed"],"note":"Sampled physical geometries grouped by existing 1mm RMS rule, original all-range max residual <=1e-7m; no claim of exhaustive alternatives or continuous ambiguity from rank alone."})
            opts=run["options"];problem=m6._problem(run["experiment"],opts)
            records=[r for r in run["experiment"]["contamination_reference"]["records"] if r["retained_index"] is not None]
            for start in run["starts"]:
                count+=1;per_file+=1;statuses[start["status"]]=statuses.get(start["status"],0)+1
                saved_pilot=start["diagnostics"].get("rejection_pilot")
                if saved_pilot is not None:pilot_statuses["success" if saved_pilot["success"] else "not_converged"]+=1
                if start["estimate"] is None:continue
                finite+=1;x=np.asarray(start["solver"]["final_parameters"])
                assert np.all(x>=problem.lower) and np.all(x<=problem.upper)
                if opts["solver"]=="lm":assert np.all(x>problem.lower) and np.all(x<problem.upper)
                r,j=_direct(x,problem);prior,pj=_direct_priors(x,problem)
                diag=start["diagnostics"];decisions=diag["observation_decisions"]
                maximum_r_error=max(maximum_r_error,float(np.max(abs(r-diag["residuals_normalized"]))))
                np.testing.assert_allclose(r,diag["residuals_normalized"],atol=1e-9,rtol=2e-11)
                if opts["loss"]=="hard_rejection":
                    pilot=start["diagnostics"]["rejection_pilot"];pilot_r,_=_direct(np.asarray(pilot["parameters"]),problem)
                    np.testing.assert_allclose(pilot_r,pilot["residuals_normalized"],atol=1e-9,rtol=2e-11)
                    weight=(abs(pilot_r)<=opts["rejection_threshold_sigma"]).astype(float);curvature=weight.copy();cost=.5*r*r*weight
                else:cost,_,weight,curvature=independent_loss(r,opts["loss"],opts["loss_scale_sigma"])
                np.testing.assert_allclose([row["weight"] for row in decisions],weight,atol=1e-10,rtol=2e-11)
                flagged=weight==0 if opts["loss"]=="hard_rejection" else weight<opts["weight_decision_threshold"]
                assert [row["flagged"] for row in decisions]==flagged.tolist()
                expected_cost=float(sum(cost)+.5*prior@prior)
                np.testing.assert_allclose(start["solver"]["final_objective"],expected_cost,atol=1e-7,rtol=3e-10)
                np.testing.assert_allclose(diag["measurement_objective"],sum(cost),atol=1e-7,rtol=3e-10)
                np.testing.assert_allclose(diag["prior_objective"],.5*prior@prior,atol=1e-7,rtol=3e-10)
                motion_count=3*(len(problem.times_s)-2) if opts["prior_sigma_m"] else 0
                np.testing.assert_allclose(diag["motion_prior_residuals_normalized"],prior[:motion_count],atol=1e-9,rtol=3e-11)
                np.testing.assert_allclose(diag["height_prior_residuals_normalized"],prior[motion_count:],atol=1e-9,rtol=3e-11)
                np.testing.assert_allclose(diag["motion_prior_objective"],.5*prior[:motion_count]@prior[:motion_count],atol=1e-7,rtol=3e-10)
                np.testing.assert_allclose(diag["height_prior_objective"],.5*prior[motion_count:]@prior[motion_count:],atol=1e-7,rtol=3e-10)
                assert diag["contamination_model_objective"]==0.
                initial=start["initial"];x0=problem.pack(initial["knot_trajectory"],initial["beacons"])
                r0,_=_direct(x0,problem);p0,_=_direct_priors(x0,problem)
                if opts["loss"]=="hard_rejection":c0=.5*r0*r0*weight
                else:c0=independent_loss(r0,opts["loss"],opts["loss_scale_sigma"])[0]
                np.testing.assert_allclose(start["solver"]["initial_parameters"],x0,atol=1e-11,rtol=1e-12)
                np.testing.assert_allclose(start["solver"]["initial_objective"],sum(c0)+.5*p0@p0,atol=2e-7,rtol=3e-10)
                if problem.height_index is not None:
                    conversion=problem.height_sign*(2*np.sqrt(x[problem.height_index]) if opts["height_parameterization"]=="q" else 1.)
                    j[:,problem.height_index]*=conversion
                matrices={"original_measurement":j,"retained_measurement":j*np.sqrt(weight)[:,None],"prior_augmented":np.vstack((j*np.sqrt(weight)[:,None],pj)),"positive_part_robust_curvature":j*np.sqrt(np.maximum(curvature,0))[:,None]}
                scale=max(float(np.median(abs(problem.ranges_m))),1.)
                for key,matrix in matrices.items():
                    singular=np.linalg.svd(matrix*scale,compute_uv=False);saved=np.asarray(diag["information"][key]["singular_values"])
                    maximum_j_error=max(maximum_j_error,float(np.max(abs(singular-saved))))
                    np.testing.assert_allclose(saved,singular,atol=2e-7,rtol=3e-9)
                    assert diag["information"][key]["rank"]==int(sum(singular>singular[0]*1e-8))
                labels=np.array([row["nlos"] for row in records]);metric=diag["rejection_evaluation"]
                tp=int(sum(labels&flagged));fp=int(sum(~labels&flagged));fn=int(sum(labels&~flagged));tn=int(sum(~labels&~flagged))
                assert [metric[key] for key in ("true_positive","false_positive","false_negative","true_negative")]==[tp,fp,fn,tn]
                assert metric["precision"]==(tp/(tp+fp) if tp+fp else None)
                assert metric["recall"]==(tp/(tp+fn) if tp+fn else None)
                assert metric["false_positive_rate"]==(fp/(fp+tn) if fp+tn else None)
        files.append({"path":str(path.relative_to(ROOT)),"attempts_checked":per_file,"sha256":record["sha256"]})
    assert count==summary["attempt_count"]==sum(statuses.values())
    assert len(summary["sweeps"])==14 and len(summary["fixtures"])==24
    joint_masking=sum(e["position_rmse_m"]>.25 and e["map_rmse_m"]>.25 for row in summary["sweeps"] for e in row["low_residual_distorted_geometry_examples"])
    return {"source":str(source.relative_to(ROOT)),"sweeps":len(summary["sweeps"]),"fixtures":len(summary["fixtures"]),"attempt_count":count,"finite_estimate_count":finite,"status_counts":statuses,"hard_rejection_pilot_stage_status_counts":pilot_statuses,"status_count_definition":"Top-level attempt status describes final estimator outcome; Gaussian pilot outcomes are additional separately reported stages, including pilots retained on failed hard-rejection attempts.","paired_reference_count":paired,"maximum_direct_normalized_residual_disagreement":maximum_r_error,"maximum_information_spectrum_disagreement":maximum_j_error,"masking_example_count":summary["masking_example_count"],"jointly_distorted_trajectory_and_map_masking_examples":joint_masking,"sampled_alternative_low_residual_runs":alternative_runs,"paired_geometry_changes":paired_changes,"paired_geometry_change_definition":"Each delta is robust minus Gaussian raw canonical-frame RMSE on identical observations/physical starts. Negative is geometric improvement. Includes finite nonconverged outcomes; unavailable failed pairs counted separately. Numerical changes within1e-6m not classified as gains/losses.","files":files,"offline_no_generation_or_solving":True}


def _check_benchmark(source):
    from uwb import m6
    import hashlib
    source=Path(source);source=source if source.is_absolute() else ROOT/source
    path=source/"performance_benchmark.json";summary=json.loads(path.read_text(encoding="utf-8"))
    assert summary["status"]=="complete" and len(summary["records"])==48
    paired={};files=[];statuses={}
    for row in summary["records"]:
        path=source/row["run"];run=json.loads(path.read_text(encoding="utf-8"))
        with patch.object(m6,"solve_experiment",side_effect=AssertionError("offline benchmark review must not solve")),patch.object(m6,"generate_experiment",side_effect=AssertionError("offline benchmark review must not regenerate")):m6.validate_run(run)
        key=(row["samples"],row["beacons"],row["repeat"])
        identity=(run["experiment"],[start["initial"] for start in run["starts"]])
        if key in paired:assert paired[key]==identity
        else:paired[key]=identity
        assert row["statuses"]==[start["status"] for start in run["starts"]]
        assert row["wrapper_s"]>=row["solver_s"]>=0
        assert row["solver_s"]==sum(start["solver"]["runtime_s"] for start in run["starts"])
        assert row["observation_count"]==len(run["experiment"]["estimator_input"]["observations"])
        problem=m6._problem(run["experiment"],run["options"])
        for start in run["starts"]:
            statuses[start["status"]]=statuses.get(start["status"],0)+1
            if start["estimate"] is None:continue
            x=np.asarray(start["solver"]["final_parameters"]);r,j=_direct(x,problem);prior,pj=_direct_priors(x,problem)
            diag=start["diagnostics"]
            np.testing.assert_allclose(r,diag["residuals_normalized"],atol=1e-9,rtol=3e-11)
            if run["options"]["loss"]=="hard_rejection":
                pilot_r,_=_direct(np.asarray(diag["rejection_pilot"]["parameters"]),problem)
                weight=(abs(pilot_r)<=run["options"]["rejection_threshold_sigma"]).astype(float);cost=.5*r*r*weight
            else:cost,_,weight,_=independent_loss(r,run["options"]["loss"],run["options"]["loss_scale_sigma"])
            np.testing.assert_allclose(start["solver"]["final_objective"],sum(cost)+.5*prior@prior,atol=1e-7,rtol=3e-10)
            np.testing.assert_allclose([d["weight"] for d in diag["observation_decisions"]],weight,atol=1e-10,rtol=3e-11)
            scale=max(float(np.median(abs(problem.ranges_m))),1.)
            for key,matrix in (("original_measurement",j),("retained_measurement",j*np.sqrt(weight)[:,None])):
                np.testing.assert_allclose(diag["information"][key]["singular_values"],np.linalg.svd(matrix*scale,compute_uv=False),atol=2e-7,rtol=3e-9)
        files.append({"path":str(path.relative_to(ROOT)),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    timings=[]
    for samples in (12,24):
        for count in (4,8):
            for loss in ("gaussian","huber","cauchy","hard_rejection"):
                rows=[row for row in summary["records"] if row["samples"]==samples and row["beacons"]==count and row["loss"]==loss]
                assert len(rows)==3
                timings.append({"samples":samples,"beacons":count,"loss":loss,"repeats":3,"wrapper_median_s":float(np.median([r["wrapper_s"] for r in rows])),"wrapper_min_s":min(r["wrapper_s"] for r in rows),"wrapper_max_s":max(r["wrapper_s"] for r in rows),"solver_median_s":float(np.median([r["solver_s"] for r in rows]))})
    return {"source":str(source.relative_to(ROOT)),"run_count":48,"paired_data_start_cells":len(paired),"status_counts":statuses,"scope":summary["scope"],"timing_distributions":timings,"files":files,"interpretation":"Paired local small-fixture timings include diagnostics/validation overhead and system contention. They do not establish general speed rankings."}


def main():
    identifier=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:8]
    directory=ROOT/"evidence/m6"/("independent_review_"+identifier);directory.mkdir(parents=True)
    result={"status":"incomplete","attempt":identifier,"author":"Independent mathematical review agent","checks":{},"failures":[],"software_versions":{"numpy":np.__version__},"independence":"Scalar robust costs/gradients/weights/curvatures and geometric range/prior equations assembled independently. Existing M5 coordinate unpack/bases define declared model; no native M6 residual/Jacobian is used as expected value."}
    def record(): (directory/"review.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    record()
    checks=[("scalar_robust_losses",_check_losses),("range_only_robust_objectives",_check_objectives),("information_and_decision_accounting",_check_information_accounting),("replay_isolation_clean_equivalence",_check_replay_isolation_equivalence),("support_and_failure_retention",_check_support_failures)]
    if len(sys.argv)>1:checks.append(("retained_acceptance_artifacts",lambda:_check_artifacts(sys.argv[1])))
    if len(sys.argv)>2:checks.append(("retained_performance_benchmark",lambda:_check_benchmark(sys.argv[2])))
    for label,check in checks:
        try: result["checks"][label]={"status":"passed","evidence":check()}
        except Exception as exc:
            result["checks"][label]={"status":"failed","error":str(exc),"traceback":traceback.format_exc()};result["failures"].append(label)
        record()
    result["status"]="failed" if result["failures"] else "passed";record()
    print(str(directory.relative_to(ROOT))+": "+result["status"])
    if result["failures"]: raise SystemExit(1)


if __name__=="__main__":main()
