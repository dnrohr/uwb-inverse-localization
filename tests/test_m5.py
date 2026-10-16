import copy
import json
import unittest
from unittest.mock import patch
import numpy as np
from uwb import m5, m5_sweeps, m5_algebraic

class M5Tests(unittest.TestCase):
    def experiment(self, **changes):
        return m5.generate_experiment({"samples":16, **changes})

    def test_physical_h_q_equivalence_and_analytic_derivatives(self):
        exp=self.experiment()
        opts={"mode":"joint","tag_height_model":"fixed","beacon_height_model":"shared","starts":1}
        geometry=m5.make_initial_geometries(exp,opts)[0]
        residual=None
        for param in ("h","q"):
            p=m5._problem(exp,m5.validate_options({**opts,"height_parameterization":param}))
            x=p.pack(geometry["knot_trajectory"],geometry["beacons"])
            r=m5.residuals(x,p)
            if residual is not None: np.testing.assert_allclose(r,residual,atol=1e-12)
            residual=r
            eps=1e-6
            finite=np.column_stack([(m5.residuals(x+eps*np.eye(len(x))[i],p)-m5.residuals(x-eps*np.eye(len(x))[i],p))/(2*eps) for i in range(len(x))])
            np.testing.assert_allclose(m5.jacobian(x,p),finite,atol=3e-7,rtol=3e-7)

    def test_paired_solvers_and_parameterizations_recover_exact_geometry(self):
        exp=self.experiment(); opts={"mode":"joint","tag_height_model":"fixed","starts":1}
        initial=m5.make_initial_geometries(exp,opts)
        objectives=[]
        for solver in ("trf","lm"):
            for param in ("h","q"):
                run=m5.solve_experiment(exp,{**opts,"solver":solver,"height_parameterization":param},initial)
                start=run["starts"][0]
                self.assertTrue(start["success"])
                self.assertLess(start["diagnostics"]["evaluation"]["raw"]["position_max_error_m"],1e-5)
                self.assertLess(start["diagnostics"]["max_abs_residual_m"],1e-7)
                objectives.append(start["solver"]["initial_objective"])
        np.testing.assert_allclose(objectives,objectives[0],atol=1e-10)

    def test_lm_bound_transform_exact_chain_rule_and_boundary_rejection(self):
        transform=m5.BoundTransform(np.array([0.,-np.inf,-np.inf]),np.array([np.inf,2.,np.inf]))
        x=np.array([.2,1.,-.3]);u=transform.encode(x);back,chain=transform.decode(u)
        np.testing.assert_allclose(x,back)
        eps=1e-6
        finite=np.column_stack([(transform.decode(u+eps*np.eye(3)[i])[0]-transform.decode(u-eps*np.eye(3)[i])[0])/(2*eps) for i in range(3)])
        np.testing.assert_allclose(finite,np.diag(chain),atol=1e-9)
        with self.assertRaises(ValueError):transform.encode(np.array([0.,1.,0.]))

    def test_lm_underflow_and_boundary_rounding_fail_explicitly(self):
        for lower, upper, u in [(np.array([0.]),np.array([np.inf]),np.array([-1000.])),(np.array([1.]),np.array([np.inf]),np.array([-100.])),(np.array([-np.inf]),np.array([1.]),np.array([-100.]))]:
            with self.assertRaises(FloatingPointError): m5.BoundTransform(lower,upper).decode(u)

    def test_invalid_algebraic_initializer_retains_every_attempt(self):
        exp=self.experiment(scenario="straight_line")
        run=m5.solve_experiment(exp,{"initialization":"algebraic","tag_height_model":"fixed","starts":2})
        self.assertEqual(run["status"],"failed")
        self.assertEqual(len(run["starts"]),2)
        for start in run["starts"]:
            self.assertIsNone(start["estimate"])
            self.assertNotEqual(start["diagnostics"]["algebraic_initializer"]["status"],"success")

    def test_algebraic_exact_three_through_eight_and_noisy_invalidity(self):
        for count in range(3,9):
            exp=self.experiment(beacon_layout={"count":count,"geometry":"equal"})
            result=m5_algebraic.propose_initialization(exp["estimator_input"]["observations"],exp["estimator_input"]["times_s"],count)
            self.assertEqual(result["status"],"success",result.get("error"))
            self.assertLess(result["diagnostics"]["proposal_range_rmse_m"],1e-7)
        noisy=self.experiment(noise_std_m=.05)
        result=m5_algebraic.propose_initialization(noisy["estimator_input"]["observations"],noisy["estimator_input"]["times_s"],4)
        self.assertNotEqual(result["status"],"success")
        self.assertIsNone(result["geometry"])

    def test_offline_run_detects_residual_and_parameterization_tampering(self):
        run=m5.solve_experiment(self.experiment(),{"tag_height_model":"fixed","starts":1})
        with patch.object(m5,"solve_experiment",side_effect=AssertionError("offline")),patch.object(m5,"generate_experiment",side_effect=AssertionError("offline")):m5.validate_run(json.loads(json.dumps(run)))
        for field in ["residual","objective","parameters","rank"]:
            bad=copy.deepcopy(run);start=bad["starts"][0]
            if field=="residual":start["diagnostics"]["residuals_m"][0]=99.
            elif field=="objective":start["solver"]["final_objective"]=99.
            elif field=="parameters":start["solver"]["final_parameters"][0]+=1.
            else:start["diagnostics"]["native_jacobian"]["rank"]+=1
            with self.assertRaises(ValueError):m5.validate_run(bad)

    def test_selected_height_branch_projection_is_disclosed_separately(self):
        exp=self.experiment(beacon_layout={"count":4,"geometry":"equal","height_m":-3})
        run=m5.solve_experiment(exp,{"tag_height_model":"fixed","height_parameterization":"q","starts":1})
        self.assertGreater(run["diagnostics"]["native_model_projection"]["map_rmse_m"],2.9)
        self.assertEqual(run["diagnostics"]["truth_model_projection"]["beacon_rmse_m"],0.)

    def test_impossible_truth_near_frame_retains_every_initializer_failure(self):
        exp=self.experiment(beacon_layout={"count":6,"geometry":"collinear"},truth_height={"type":"spatial"})
        run=m5.solve_experiment(exp,{"tag_height_model":"free","beacon_height_model":"independent","initialization":"truth_near","starts":2})
        self.assertEqual(run["status"],"failed");self.assertEqual(len(run["starts"]),2)
        for start in run["starts"]:self.assertIn("Truth-near initialization failed",start["solver"]["message"])

    def test_variant_cannot_silently_change_start_generation_controls(self):
        for key,value in [("initialization_error_m",1.),("algebraic_physical_tolerance",.01)]:
            with self.assertRaises(ValueError): m5_sweeps.validate_sweep_config({"factor":"noise_std_m","values":[0],"seeds":[7],"variants":[{"label":"invalid", "options":{key:value}}]})

    def test_sweep_pairing_persistence_and_tampering(self):
        artifact=m5_sweeps.run_sweep({"base_experiment":{"samples":8},"options":{"starts":1,"max_nfev":100},"factor":"initialization_error_m","values":[0,.1],"seeds":[7]})
        self.assertEqual(len(artifact["start_table"]),8)
        for i in (0,4):
            initials=[start["initial"] for start in artifact["entries"][i]["run"]["starts"]]
            for entry in artifact["entries"][i+1:i+4]:
                self.assertEqual(initials,[start["initial"] for start in entry["run"]["starts"]])
        with patch.object(m5,"solve_experiment",side_effect=AssertionError("offline")),patch.object(m5,"generate_experiment",side_effect=AssertionError("offline")):
            m5_sweeps.validate_artifact(json.loads(json.dumps(artifact)))
        corrupt=copy.deepcopy(artifact);corrupt["start_table"][0]["range_rmse_m"]=999.
        with self.assertRaises(ValueError):m5_sweeps.validate_artifact(corrupt)
