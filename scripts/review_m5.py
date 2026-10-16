"""Independent equations and retained-artifact review; every attempt is saved."""
from pathlib import Path
from datetime import datetime, timezone
import copy
import hashlib
import json
import sys
import traceback
import uuid

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from uwb import m5, m5_algebraic, m5_sweeps


def _data(count=8, height=2.2, seed=41):
    """Independent distances, no simulator or solver residual used."""
    xy = np.random.default_rng(seed).uniform([-3., -2.], [9., 7.], (30, 2))
    tags = np.column_stack((xy, np.zeros(30)))
    anchors = np.column_stack((np.array([[0., 0.], [7.3, 0.], [-1.1, 5.8], [8., 7.], [-2., 3.], [4., -3.], [11., 4.], [1., 10.]])[:count], np.full(count, height)))
    times = np.arange(len(tags), dtype=float)
    distances = np.sqrt(np.sum((tags[:, None] - anchors[None]) ** 2, axis=2))
    observations = [{"epoch": i, "beacon_id": j, "range_m": float(distances[i, j]), "assumed_time_s": float(times[i]), "sigma_m": .03 + .01 * j} for i in range(len(tags)) for j in range(count)]
    return tags, anchors, times, observations


def _direct(parameters, problem):
    tags, anchors = problem.unpack(parameters)
    weights = np.zeros_like(problem.weights)
    # Rebuild interpolation independently; observation timestamps define rows.
    used = problem.assumed_times_s if problem.options["timing_model"] == "timestamp_aware" else problem.times_s[problem.epochs]
    for row, t in enumerate(used):
        left = np.searchsorted(problem.times_s, t, side="right") - 1
        left = int(np.clip(left, 0, len(problem.times_s) - 2))
        fraction = (t - problem.times_s[left]) / (problem.times_s[left + 1] - problem.times_s[left])
        weights[row, left:left + 2] = [1. - fraction, fraction]
    ping_tags = weights @ tags
    difference = ping_tags - anchors[problem.beacon_ids]
    distance = np.sqrt(np.sum(difference ** 2, axis=1))
    derivative = np.einsum("ik,kcn->icn", weights, problem.physical.tag_basis) - problem.physical.beacon_basis[problem.beacon_ids]
    matrix = np.einsum("ic,icn->in", difference, derivative) / (distance * problem.sigma_m)[:, None]
    if problem.height_index is not None:
        if problem.options["height_parameterization"] == "q":
            matrix[:, problem.height_index] = 1. / (2. * distance * problem.sigma_m)
        else:
            matrix[:, problem.height_index] *= problem.height_sign
    return (distance - problem.ranges_m) / problem.sigma_m, matrix


def _check_derivatives():
    rows = []
    tags, anchors, times, obs = _data()
    for mode in ("joint", "known_map"):
        for parameterization in ("h", "q"):
            for gap in (2.2, 1e-5):
                current_anchors = anchors.copy(); current_anchors[:, 2] = gap
                opts = {"mode": mode, "tag_height_model": "fixed" if mode == "joint" else "shared", "height_parameterization": parameterization, "starts": 1, "prior_sigma_m": .3}
                problem = m5.build_problem(obs, times, beacon_count=8, surveyed_beacons=current_anchors if mode == "known_map" else None, **opts)
                x = problem.pack(tags, current_anchors)
                direct_r, direct_j = _direct(x, problem)
                np.testing.assert_allclose(m5.measurement_residuals(x, problem), direct_r, atol=2e-13, rtol=0.)
                np.testing.assert_allclose(m5.measurement_jacobian(x, problem), direct_j, atol=2e-13, rtol=0.)
                # The q=0 boundary uses a one-sided derivative, never a
                # negative-q central difference or singular inverse map.
                finite = np.zeros_like(direct_j)
                for j in range(len(x)):
                    step = 1e-6 * max(1., abs(x[j]))
                    if j == problem.height_index and parameterization == "h": step = min(step, gap / 10.)
                    if j == problem.height_index and parameterization == "q" and x[j] < step:
                        shifted = x.copy(); shifted[j] += step
                        shifted2 = x.copy(); shifted2[j] += 2 * step
                        finite[:, j] = (-3 * _direct(x, problem)[0] + 4 * _direct(shifted, problem)[0] - _direct(shifted2, problem)[0]) / (2 * step)
                    else:
                        plus = x.copy(); minus = x.copy(); plus[j] += step; minus[j] -= step
                        finite[:, j] = (_direct(plus, problem)[0] - _direct(minus, problem)[0]) / (2 * step)
                np.testing.assert_allclose(direct_j, finite, atol=8e-5, rtol=4e-5)
                full_j = m5.jacobian(x, problem)
                assert np.all(full_j[len(obs):, problem.height_index] == 0.)
                scales = np.full(len(x), max(float(np.median(problem.ranges_m)), 1.))
                if parameterization == "q": scales[problem.height_index] **= 2
                singular = np.linalg.svd(direct_j * scales, compute_uv=False)
                native = m5.jacobian_diagnostics(x, problem)
                np.testing.assert_allclose(native["singular_values"], singular, rtol=2e-13, atol=2e-13)
                rows.append({"mode": mode, "parameterization": parameterization, "gap_m": gap, "jacobian_max_direct_error": float(np.max(np.abs(m5.measurement_jacobian(x, problem) - direct_j))), "finite_difference_max_error": float(np.max(np.abs(direct_j - finite))), "native_rank": native["rank"], "parameter_count": len(x), "native_condition": native["condition_number"], "native_height_column_norm": float(np.linalg.norm(direct_j[:, problem.height_index]))})
    # The inverse h=sqrt(q) is singular at zero even though q distance
    # derivatives remain finite for nonzero horizontal distances.
    zero_problem = m5.build_problem(obs, times, beacon_count=8, height_parameterization="q", tag_height_model="fixed")
    x = zero_problem.pack(tags, anchors); x[zero_problem.height_index] = 0.
    assert np.all(np.isfinite(m5.measurement_jacobian(x, zero_problem)))
    return {"cases": rows, "q_zero_finite_distance_derivatives": True, "q_zero_is_outside_solver_floor": True, "interpretation": "q at zero has finite distance derivative but a singular inverse to physical h; rank changes are coordinate dependent, not new height information"}


def _direct_priors(parameters, problem):
    tags, _ = problem.unpack(parameters)
    knot_times = problem.times_s
    matrix = np.zeros((len(knot_times)-2, len(knot_times))) if problem.options["prior_sigma_m"] else np.zeros((0,len(knot_times)))
    for i in range(len(matrix)):
        before=knot_times[i+1]-knot_times[i];after=knot_times[i+2]-knot_times[i+1]
        matrix[i,i:i+3]=[-after/(before+after),1.,-before/(before+after)]
    if len(matrix):matrix/=problem.options["prior_sigma_m"]
    motion=(matrix@tags).ravel()
    motion_j=np.einsum("ik,kcn->icn",matrix,problem.physical.tag_basis).reshape((-1,problem.parameter_count))
    if problem.options["tag_height_model"]=="soft":
        height=(tags[:,2]-problem.options["fixed_tag_z_m"])/problem.options["height_prior_sigma_m"]
        height_j=problem.physical.tag_basis[:,2]/problem.options["height_prior_sigma_m"]
    else:height=np.zeros(0);height_j=np.zeros((0,problem.parameter_count))
    if problem.height_index is not None:
        motion_j[:,problem.height_index]=0.
        height_j[:,problem.height_index]=0.
    return np.r_[motion,height],np.vstack((motion_j,height_j))


def _check_all_h_models():
    tags,anchors,times,obs=_data(6)
    rows=[];unsupported=[]
    for mode in ("joint","known_map"):
        for tag_model in ("fixed","shared","soft","free"):
            for beacon_model in ("shared","independent"):
                for below in (False,True):
                    options={"mode":mode,"tag_height_model":tag_model,"beacon_height_model":beacon_model,"below_beacons":below,"prior_sigma_m":.3,"height_prior_sigma_m":.2,"solver":"lm","starts":1}
                    if mode=="joint" and tag_model in ("soft","free") and beacon_model=="independent" and below:
                        try:m5.build_problem(obs,times,beacon_count=6,**options)
                        except ValueError:unsupported.append(options)
                        else:raise AssertionError("Coupled unsupported below bounds accepted")
                        continue
                    problem=m5.build_problem(obs,times,beacon_count=6,surveyed_beacons=anchors if mode=="known_map" else None,**options)
                    initial=m5._initial(problem,np.random.default_rng(211),0)
                    x=problem.pack(initial["knot_trajectory"],initial["beacons"])
                    r,j=_direct(x,problem);pr,pj=_direct_priors(x,problem)
                    expected_r=np.r_[r,pr];expected_j=np.vstack((j,pj))
                    np.testing.assert_allclose(m5.residuals(x,problem),expected_r,atol=2e-12,rtol=2e-13)
                    np.testing.assert_allclose(m5.jacobian(x,problem),expected_j,atol=2e-12,rtol=2e-13)
                    # Check complete physical range+prior finite differences.
                    finite=np.zeros_like(expected_j)
                    for column in range(len(x)):
                        step=1e-6*max(abs(x[column]),1.)
                        plus=x.copy();minus=x.copy();plus[column]+=step;minus[column]-=step
                        rr,_=_direct(plus,problem);pp,_=_direct_priors(plus,problem)
                        rl,_=_direct(minus,problem);pl,_=_direct_priors(minus,problem)
                        finite[:,column]=(np.r_[rr,pp]-np.r_[rl,pl])/(2*step)
                    np.testing.assert_allclose(finite,expected_j,atol=3e-6,rtol=3e-6)
                    transform=m5.BoundTransform(problem.lower,problem.upper)
                    u=transform.encode(x);decoded,chain=transform.decode(u)
                    np.testing.assert_allclose(decoded,x,atol=2e-12,rtol=2e-13)
                    transformed=np.zeros_like(expected_j)
                    for column in range(len(u)):
                        step=1e-6;plus=u.copy();minus=u.copy();plus[column]+=step;minus[column]-=step
                        xp=transform.decode(plus)[0];xm=transform.decode(minus)[0]
                        rr,_=_direct(xp,problem);pp,_=_direct_priors(xp,problem)
                        rl,_=_direct(xm,problem);pl,_=_direct_priors(xm,problem)
                        transformed[:,column]=(np.r_[rr,pp]-np.r_[rl,pl])/(2*step)
                    np.testing.assert_allclose(transformed,expected_j*chain,atol=4e-6,rtol=4e-6)
                    rows.append({"mode":mode,"tag_height_model":tag_model,"beacon_height_model":beacon_model,"below_beacons":below,"parameter_count":len(x),"measurement_rows":len(r),"prior_rows":len(pr),"direct_jacobian_max_error":float(np.max(np.abs(expected_j-m5.jacobian(x,problem)))),"finite_difference_max_error":float(np.max(np.abs(finite-expected_j))),"lm_chain_max_error":float(np.max(np.abs(transformed-expected_j*chain)))})
    return {"cases":rows,"supported_model_count":len(rows),"explicitly_unsupported_coupled_bounds":unsupported}


def _check_algebraic():
    cases = []
    for count in range(3, 9):
        tags, anchors, times, obs = _data(count)
        obs = list(reversed(obs))
        proposal = m5_algebraic.propose_initialization(obs, times, count)
        assert proposal["status"] == "success", proposal["error"]
        geometry = proposal["geometry"]
        np.testing.assert_allclose(geometry["trajectory"], tags, atol=2e-10, rtol=0.)
        np.testing.assert_allclose(geometry["beacons"], anchors, atol=2e-10, rtol=0.)
        d, a, b, h = 7.3, -1.1, 5.8, 2.2
        c = (a*a + b*b - a*d)/(2*b)
        expected = {"alpha": 1/(4*d*d) + a*a/(4*b*b*d*d), "beta": -a/(2*b*b*d), "gamma": 1/(4*b*b), "delta": -.5 + a*c/(b*d), "eta": -c/b, "kappa": d*d/4 + c*c + h*h}
        for key, value in expected.items(): np.testing.assert_allclose(proposal["diagnostics"]["coefficients_physical"][key], value, atol=2e-10, rtol=0.)
        reflected = anchors.copy(); reflected[:, 2] *= -1
        np.testing.assert_allclose(np.linalg.norm(tags[:, None]-reflected[None], axis=2), np.linalg.norm(tags[:, None]-anchors[None], axis=2), atol=0.)
        cases.append({"beacon_count": count, "trajectory_max_error_m": float(np.max(np.linalg.norm(np.asarray(geometry["trajectory"])-tags, axis=1))), "map_max_error_m": float(np.max(np.linalg.norm(np.asarray(geometry["beacons"])-anchors, axis=1))), "design_condition": proposal["diagnostics"]["design"]["condition_number"], "all_physical_coefficients_checked": True})
    tags, anchors, times, obs = _data(4)
    failures = []
    def rejected(label, data, t=times, count=4, opts=None):
        proposal = m5_algebraic.propose_initialization(data, t, count, opts)
        assert proposal["status"] != "success" and proposal["geometry"] is None, label
        failures.append({"case": label, "proposal": proposal})
    noisy = copy.deepcopy(obs)
    for o, error in zip(noisy, np.random.default_rng(29).normal(0., .05, len(noisy))): o["range_m"] += float(error)
    rejected("noisy_unconstrained_invalid_fit", noisy)
    assert "coefficients_dimensionless" in failures[-1]["proposal"]["diagnostics"]
    rejected("missing", obs[:-1])
    async_obs = copy.deepcopy(obs); async_obs[0]["assumed_time_s"] += .1
    rejected("asynchronous", async_obs)
    negative = copy.deepcopy(obs); negative[0]["range_m"] = -1.
    rejected("negative_range", negative)
    rejected("insufficient_epochs", [o for o in obs if o["epoch"] < 5], times[:5])
    rejected("independent_beacon_heights", obs, opts={"beacon_height_model":"independent"})
    straight = copy.deepcopy(obs)
    line = np.column_stack((np.linspace(2.,5.,len(times)), np.full(len(times),2.), np.zeros(len(times))))
    for o in straight: o["range_m"] = float(np.linalg.norm(line[o["epoch"]]-anchors[o["beacon_id"]]))
    rejected("straight_line_lifted_rank_loss", straight)
    u, v = np.random.default_rng(13).uniform(-.3,.3,(2,len(times)))
    for label, alpha, gamma, delta, kappa in (("negative_gamma", .1,-.1,-.5, 10.), ("physical_linear_mismatch", .1,.1,-.4,10.)):
        D0 = alpha*u*u + gamma*v*v + delta*u - .5*v + kappa
        synthetic = [{"epoch":i,"beacon_id":j,"range_m":float(np.sqrt(value)),"assumed_time_s":float(times[i])} for i in range(len(times)) for j,value in enumerate((D0[i],D0[i]+u[i],D0[i]+v[i]))]
        rejected(label, synthetic, count=3)
    negative_h2 = copy.deepcopy(obs)
    for o in negative_h2:
        i,j=o["epoch"],o["beacon_id"]
        horizontal2=np.sum((tags[i,:2]-anchors[j,:2])**2)
        # Every horizontal distance in this seeded fixture exceeds sqrt(.001).
        o["range_m"]=float(np.sqrt(horizontal2-.001))
    rejected("negative_height_squared",negative_h2)
    assert failures[-1]["proposal"]["error"]["code"] == "nonpositive_height_squared"
    # Truth-only ping metadata must have no effect, including fabricated actual
    # clocks. The support assertion is about estimator-assumed timing only.
    poisoned=copy.deepcopy(obs)
    for o in poisoned: o.update(actual_time_s=-1e9,delivery_time_s=1e9,truth={"beacons":"poison"})
    assert m5_algebraic.propose_initialization(poisoned,times,4) == m5_algebraic.propose_initialization(obs,times,4)
    return {"exact_cases":cases,"retained_failures":failures,"truth_metadata_excluded":True}


def _check_lm():
    transform=m5.BoundTransform(np.array([1e-6,-np.inf,-np.inf]),np.array([np.inf,2.,np.inf]))
    x=np.array([.4,1.2,-.3]);u=transform.encode(x);back,chain=transform.decode(u)
    np.testing.assert_allclose(back,x,atol=2e-15)
    eps=1e-6
    finite=np.column_stack([(transform.decode(u+eps*np.eye(3)[i])[0]-transform.decode(u-eps*np.eye(3)[i])[0])/(2*eps) for i in range(3)])
    np.testing.assert_allclose(finite,np.diag(chain),atol=2e-10)
    rejected=[]
    for label,native in (("lower_boundary",np.array([1e-6,1.,0.])),("upper_boundary",np.array([1.,2.,0.]))):
        try: transform.encode(native)
        except (ValueError,FloatingPointError): rejected.append(label)
        else: raise AssertionError(label+" must fail")
    for label,value in (("underflow",-1000.),("bound_roundoff",-100.),("overflow",1000.)):
        try: transform.decode(np.array([value,value,0.]))
        except (ValueError,FloatingPointError): rejected.append(label)
        else: raise AssertionError(label+" must fail instead of violating strict interior")
    exp=m5.generate_experiment({"samples":12})
    nonconverged=m5.solve_experiment(exp,{"solver":"lm","starts":2,"max_nfev":1})
    assert len(nonconverged["starts"])==2 and all(s["status"]=="not_converged" and s["estimate"] is not None for s in nonconverged["starts"])
    historical=[]
    # Reconstruct the exact former decode equations read during review. The
    # record identifies historical source behavior, not the repaired function.
    for value in (-1000.,-100.):
        exponential=float(np.exp(value))
        historical.append({"coordinate":value,"former_lower_plus_exp":float(1e-6+exponential),"lower_bound":1e-6,"former_upper_minus_exp":float(2.-exponential),"upper_bound":2.,"former_derivative_magnitude":exponential,"failed_strict_interior_contract":bool(1e-6+exponential<=1e-6 or 2.-exponential>=2.)})
    assert all(row["failed_strict_interior_contract"] for row in historical)
    return {"chain_finite_difference_max_error":float(np.max(np.abs(finite-np.diag(chain)))),"explicitly_rejected":rejected,"budget_exhaustion_statuses":[s["status"] for s in nonconverged["starts"]],"historical_pre_fix_reproducer":{"status":"failed_contract","method":"Reconstruction of former lower+exp(u), upper-exp(u) equations","cases":historical},"repaired_current_source_status":"passed"}


def _check_truth_and_pairing():
    exp=m5.generate_experiment({"samples":12})
    poisoned=copy.deepcopy(exp)
    poisoned["truth"]["trajectory"]=(np.asarray(poisoned["truth"]["trajectory"])+[200.,-100.,30.]).tolist()
    poisoned["truth"]["beacons"]=(np.asarray(poisoned["truth"]["beacons"])+[200.,-100.,30.]).tolist()
    for key in ("ping_positions","grouped_positions"):
        poisoned["truth"][key]=(np.asarray(poisoned["truth"][key])+[200.,-100.,30.]).tolist()
    for initializer in ("independent","algebraic"):
        options={"initialization":initializer,"starts":2}
        assert m5.make_initial_geometries(exp,options)==m5.make_initial_geometries(poisoned,options)
    for control,value in (("initialization_error_m",.2),("algebraic_physical_tolerance",.01)):
        try: m5_sweeps.validate_sweep_config({"factor":"noise_std_m","values":[0.],"seeds":[7],"variants":[{"label":"changed","options":{control:value}}]})
        except ValueError: pass
        else: raise AssertionError("Variant start-generating control must be rejected: "+control)
    return {"independent_and_algebraic_truth_poisoning_invariance":True,"variants_cannot_override_start_controls":True}


def _check_native_projection_and_failed_seeds():
    projection=[];degenerate=[]
    exp=m5.generate_experiment({"samples":8,"beacon_layout":{"count":4,"geometry":"equal","height_m":-3.}})
    for coordinate in ("h","q"):
        run=m5.solve_experiment(exp,{"tag_height_model":"fixed","height_parameterization":coordinate,"initialization":"algebraic","starts":1})
        native=run["diagnostics"]["native_model_projection"]
        assert native["available"]
        # The projected negative signed height is clamped to the declared
        # interior seed height, not reflected. Derive its displacement directly.
        np.testing.assert_allclose(native["map_rmse_m"],3.+2*m5.FLOOR,atol=3e-12,rtol=0.)
        np.testing.assert_allclose(native["knot_position_rmse_m"],0.,atol=3e-12,rtol=0.)
        np.testing.assert_allclose(run["diagnostics"]["truth_model_projection"]["beacon_rmse_m"],0.,atol=3e-12,rtol=0.)
        estimate=run["starts"][0]["estimate"]
        assert estimate is not None
        tags=np.asarray(estimate["knot_trajectory"]);beacons=np.asarray(estimate["beacons"])
        assert np.all(beacons[:,2]>tags[0,2])
        direct=np.linalg.norm(tags[:,None]-beacons[None],axis=2)
        observed=np.zeros_like(direct)
        for item in exp["estimator_input"]["observations"]:observed[item["epoch"],item["beacon_id"]]=item["range_m"]
        np.testing.assert_allclose(direct,observed,atol=3e-10,rtol=0.)
        projection.append({"coordinate":coordinate,"native_projected_map_rmse_m":native["map_rmse_m"],"preceding_m4_projected_map_rmse_m":run["diagnostics"]["truth_model_projection"]["beacon_rmse_m"],"reflected_positive_branch_max_range_error_m":float(np.max(np.abs(direct-observed))),"interpretation":"Model projection displacement is not a lower bound: a reflected positive-height geometry has the same ranges"})
    bad=m5.generate_experiment({"samples":8,"beacon_layout":{"count":6,"geometry":"collinear"},"truth_height":{"type":"spatial"}})
    for solver in ("trf","lm"):
        run=m5.solve_experiment(bad,{"solver":solver,"tag_height_model":"free","beacon_height_model":"independent","initialization":"truth_near","starts":3,"max_nfev":10})
        assert run["status"]=="failed" and run["selected_start"] is None and len(run["starts"])==3
        messages=[]
        for index,start in enumerate(run["starts"]):
            assert start["index"]==index and start["status"]=="failed" and start["estimate"] is None
            original=start["initial"]["initialization_error"]
            assert "Truth-near initialization failed" in original and "noncollinear" in original
            assert original in start["solver"]["message"]
            messages.append(start["solver"]["message"])
        assert not run["diagnostics"]["native_model_projection"]["available"]
        m5.validate_run(json.loads(json.dumps(run)))
        degenerate.append({"solver":solver,"requested_start_count":3,"retained_failed_start_count":3,"original_seed_errors":messages,"native_projection_unavailable_disclosed":True})
    # A saved native q at the floor is valid even if re-packing its world-z
    # geometry would cancel the small gap and misclassify its floor feasibility.
    tags,anchors,times,obs=_data(4)
    anchors[:,2]=10.;tags[:,2]=10.-m5.FLOOR
    problem=m5.build_problem(obs,times,beacon_count=4,surveyed_beacons=anchors,mode="known_map",tag_height_model="shared",height_parameterization="q")
    x=problem.pack(tags,anchors,project=True);x[problem.height_index]=m5.FLOOR**2
    geometry=problem.geometry(x)
    raw_difference=float(10.-np.asarray(geometry["knot_trajectory"])[0,2])
    try:problem.pack(geometry["knot_trajectory"],geometry["beacons"])
    except ValueError as exc:inverse={"status":"failed_due_to_roundoff","error":str(exc)}
    else:inverse={"status":"rounded_success"}
    direct_r,direct_j=_direct(x,problem)
    np.testing.assert_allclose(m5.measurement_residuals(x,problem),direct_r,atol=2e-12,rtol=0.)
    assert np.all(np.isfinite(direct_j)) and x[problem.height_index]>=problem.lower[problem.height_index]
    return {"native_branch_projection":projection,"retained_truth_near_degenerate_cases":degenerate,"near_surveyed_plane_inverse_cancellation":{"surveyed_plane_z_m":10.,"native_height_m":m5.FLOOR,"world_z_recovered_gap_m":raw_difference,"inverse_pack":inverse,"native_coordinates_remain_valid":True}}


def _check_artifacts():
    directories=sorted((ROOT/"evidence/m5").glob("acceptance_*"))
    source=next((p for p in reversed(directories) if (p/"acceptance_summary.json").exists() and json.loads((p/"acceptance_summary.json").read_text(encoding="utf-8")).get("status")=="passed"),None)
    assert source is not None,"Acceptance artifacts required"
    summary=json.loads((source/"acceptance_summary.json").read_text(encoding="utf-8"))
    assert summary["status"]=="passed",summary.get("error")
    files=[];max_r_error=0.;max_j_error=0.;paired=0;statuses={};initial_invalid=0;historical_bound_invalid=[]
    sweep_files=0;fixture_files=0;sweep_runs=0;sweep_starts=0;fixture_starts=0;finite_estimates=0
    for path in sorted(source.rglob("*.json")):
        if "checkpoint" in path.name or path.name=="acceptance_summary.json":continue
        data=json.loads(path.read_text(encoding="utf-8"))
        if data.get("artifact_type")=="solver_sweep":
            sweep_files+=1
            m5_sweeps.validate_artifact(data)
            runs=[e["run"] for e in data["entries"]]
            sweep_runs+=len(runs)
            sweep_starts+=sum(len(run["starts"]) for run in runs)
            for entry in data["entries"]:
                if entry.get("initial_reference_entry") is not None:paired+=1
        else:
            assert data.get("schema_version")=="5.0" and "experiment" in data,"Unexpected non-run source JSON: "+str(path)
            fixture_files+=1
            m5.validate_run(data);runs=[data]
            fixture_starts+=len(data["starts"])
        count=0
        for run in runs:
            problem=m5._problem(run["experiment"],run["options"])
            for start in run["starts"]:
                count+=1;statuses[start["status"]]=statuses.get(start["status"],0)+1
                if start.get("diagnostics",{}).get("algebraic_initializer",{}).get("status") in ("invalid","failed","unsupported"):initial_invalid+=1
                if start.get("estimate") is None:continue
                finite_estimates+=1
                estimate=start["estimate"];x=np.asarray(start["solver"]["final_parameters"],dtype=float)
                reconstructed=problem.geometry(x)
                for field in ("trajectory","beacons","knot_trajectory","ping_trajectory","assumed_ping_trajectory"):
                    np.testing.assert_allclose(estimate[field],reconstructed[field],atol=1e-8,rtol=1e-9)
                if run["options"]["solver"]=="lm" and (np.any(x<=problem.lower) or np.any(x>=problem.upper)):
                    revision=start["solver"].get("bounds_transform_revision",1)
                    assert revision<2,"Repaired LM estimate must remain strictly interior"
                    historical_bound_invalid.append({"file":str(path.relative_to(ROOT)),"start_index":start["index"],"raw_recorded_status":start["status"],"bounds_transform_revision":revision,"constraint_outcome":"invalid historical strict-interior claim; retain for inspection, exclude from feasibility/convergence acceptance"})
                direct_r,direct_j=_direct(x,problem)
                saved=np.asarray(start["diagnostics"]["residuals_normalized"])
                re=float(np.max(np.abs(saved-direct_r)));je=float(np.max(np.abs(m5.measurement_jacobian(x,problem)-direct_j)))
                max_r_error=max(max_r_error,re);max_j_error=max(max_j_error,je)
                np.testing.assert_allclose(saved,direct_r,atol=2e-9,rtol=2e-10)
                np.testing.assert_allclose(m5.measurement_jacobian(x,problem),direct_j,atol=2e-9,rtol=2e-10)
                prior_r,prior_j=_direct_priors(x,problem)
                native_scales=np.full(problem.parameter_count,max(float(np.median(problem.ranges_m)),1.))
                if problem.height_index is not None and problem.options["height_parameterization"]=="q":native_scales[problem.height_index]**=2
                physical_j=direct_j.copy();physical_prior_j=prior_j.copy()
                if problem.height_index is not None:
                    conversion=problem.height_sign
                    if problem.options["height_parameterization"]=="q":conversion*=2*np.sqrt(x[problem.height_index])
                    physical_j[:,problem.height_index]*=conversion
                    physical_prior_j[:,problem.height_index]*=conversion
                for key,matrix,scales in (("native_jacobian",direct_j,native_scales),("native_augmented_jacobian",np.vstack((direct_j,prior_j)),native_scales),("jacobian",physical_j,np.full(problem.parameter_count,max(float(np.median(problem.ranges_m)),1.))),("augmented_jacobian",np.vstack((physical_j,physical_prior_j)),np.full(problem.parameter_count,max(float(np.median(problem.ranges_m)),1.)))):
                    saved_rank=start["diagnostics"][key]
                    singular=np.linalg.svd(matrix*scales,compute_uv=False)
                    np.testing.assert_allclose(saved_rank["singular_values"],singular,atol=3e-8,rtol=3e-10)
                    rank=int(np.count_nonzero(singular>singular[0]*1e-8))
                    assert saved_rank["rank"]==rank and saved_rank["full_column_rank"]==(rank==problem.parameter_count)
                    if rank==problem.parameter_count:np.testing.assert_allclose(saved_rank["condition_number"],singular[0]/singular[-1],atol=1e-6,rtol=1e-5)
                    else:assert saved_rank["condition_number"] is None
                objective=float(.5*direct_r@direct_r)
                np.testing.assert_allclose(start["solver"]["measurement_objective"],objective,atol=1e-9,rtol=2e-10)
                if start["initial"] is not None:
                    initial=start["initial"];x0=problem.pack(initial["knot_trajectory"],initial["beacons"])
                    initial_r,_=_direct(x0,problem); motion,height=m5.prior_components(x0,problem)
                    initial_cost=float(.5*(initial_r@initial_r+motion@motion+height@height))
                    np.testing.assert_allclose(start["solver"]["initial_objective"],initial_cost,atol=2e-8,rtol=2e-10)
        files.append({"path":str(path.relative_to(ROOT)),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"attempts_checked":count})
    expected_sweep_starts=sum(cell["starts"] for cell in summary["sweeps"])
    expected_sweep_runs=sum(cell["runs"] for cell in summary["sweeps"])
    expected_fixture_starts=sum(len(cell["starts"]) for cell in summary["fixtures"])
    assert sweep_files==len(summary["sweeps"]),"Every summarized sweep must be read, including nested folders"
    assert fixture_files==len(summary["fixtures"]),"Every summarized demo run must be read"
    assert sweep_runs==expected_sweep_runs and sweep_starts==expected_sweep_starts
    assert fixture_starts==expected_fixture_starts
    assert sweep_files>=8 and fixture_files>=8 and sweep_starts>=288,"Acceptance source must cover the complete benchmark family, not an empty/partial traversal"
    assert sum(statuses.values())==sweep_starts+fixture_starts
    manifest=json.loads((ROOT/"evidence/m5/preservation_manifest.json").read_text(encoding="utf-8"))
    changed=[p for p,h in manifest.items() if not (ROOT/p).exists() or hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h]
    assert not changed,changed
    return {"source":str(source.relative_to(ROOT)),"sweep_count":sweep_files,"fixture_file_count":fixture_files,"sweep_run_count":sweep_runs,"sweep_start_count":sweep_starts,"fixture_start_count":fixture_starts,"total_attempt_count":sweep_starts+fixture_starts,"finite_estimate_count":finite_estimates,"files":files,"retained_status_counts":statuses,"invalid_algebraic_attempt_count":initial_invalid,"paired_reference_count":paired,"maximum_direct_residual_disagreement":max_r_error,"maximum_direct_jacobian_disagreement":max_j_error,"preservation_checked_files":len(manifest),"preservation_changes":changed,"historical_bound_invalid_estimates":historical_bound_invalid}


def main():
    identifier=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")+"_"+uuid.uuid4().hex[:8]
    directory=ROOT/"evidence/m5"/("independent_review_"+identifier);directory.mkdir(parents=True)
    result={"status":"incomplete","attempt":identifier,"author":"Independent mathematical review agent","checks":{},"failures":[],"software_versions":{"numpy":np.__version__},"independence":"Distance residuals, analytic range Jacobian and physical lifted coefficients are assembled directly; simulator residuals/Jacobians are not used as expected values. Native model unpack/bases define declared coordinates."}
    def record():
        text=json.dumps(result,indent=2,allow_nan=False)+"\n"
        (directory/"review.json").write_text(text,encoding="utf-8")
        (ROOT/"evidence/m5/independent_math_review.json").write_text(text,encoding="utf-8")
    record()
    for label,check in (("distance_jacobian_scaling",_check_derivatives),("all_supported_h_model_jacobians",_check_all_h_models),("algebraic_physics_support",_check_algebraic),("lm_domains_and_failures",_check_lm),("truth_independence_and_pairing",_check_truth_and_pairing),("native_projection_and_failed_seeds",_check_native_projection_and_failed_seeds),("retained_acceptance_artifacts",_check_artifacts)):
        try:result["checks"][label]={"status":"passed","evidence":check()}
        except Exception as exc:
            result["checks"][label]={"status":"failed","error":str(exc),"traceback":traceback.format_exc()}
            result["failures"].append(label)
        record()
    result["status"]="passed" if not result["failures"] else "failed";record()
    if result["checks"].get("lm_domains_and_failures",{}).get("status")=="passed":
        (directory/"pre_fix_defect_reproducer.json").write_text(json.dumps(result["checks"]["lm_domains_and_failures"]["evidence"]["historical_pre_fix_reproducer"],indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(str(directory.relative_to(ROOT))+": "+result["status"])
    if result["failures"]:raise SystemExit(1)


if __name__=="__main__":main()
