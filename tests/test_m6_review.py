"""Independent equations test objective/derivatives rather than implementation form."""
import unittest

import numpy as np

from scripts.review_m6 import independent_loss, _check_losses, _check_objectives, _check_information_accounting, _check_support_failures


class IndependentM6Tests(unittest.TestCase):
    def test_scalar_loss_objectives_derivatives_weights_curvature(self):
        evidence = _check_losses()
        self.assertEqual(len(evidence["cases"]), 12)

    def test_only_range_objective_is_robust_with_physical_coordinate_chain(self):
        evidence = _check_objectives()
        self.assertEqual(len(evidence["cases"]), 12)
        self.assertTrue(all(row["prior_objective"] > 0 for row in evidence["cases"]))

    def test_reference_cauchy_curvature_can_be_negative(self):
        costs, gradients, weights, curvature = independent_loss(np.array([0., 1., 3.]), "cauchy", 2.)
        self.assertEqual(costs[0], 0.)
        self.assertEqual(gradients[0], 0.)
        self.assertEqual(weights[0], 1.)
        self.assertGreater(curvature[1], 0.)
        self.assertLess(curvature[2], 0.)

    def test_information_and_confusion_accounting_from_independent_rows(self):
        evidence = _check_information_accounting()
        self.assertEqual(len(evidence["cases"]), 10)
        self.assertEqual(evidence["confusion_matrix"]["dropped_count_excluded"], 1)

    def test_model_support_and_rejected_lm_rows(self):
        evidence = _check_support_failures()
        self.assertEqual(evidence["invalid_physical_starts_retained"], 2)
        self.assertTrue(evidence["lm_rejected_zero_rows_excluded"])


if __name__ == "__main__":
    unittest.main()
