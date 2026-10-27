"""
Unit tests for _allocate_nodes_to_batches in provision.py and instantiate.py.

provision._allocate_nodes_to_batches(
    max_batch_size, initial_nodes, min_nodes, max_nodes
)
  - Batch count is ceil(max_nodes / max_batch_size)
  - Distributes initial_nodes, min_nodes, and max_nodes evenly; remainders
    spread one-per-batch across the first N batches

instantiate._allocate_nodes_to_batches(max_batch_size, initial_nodes)
  - Batch count is ceil(initial_nodes / max_batch_size)
  - initial_nodes=0 returns a single zero-instance batch (ZeroDivisionError catch)
  - Remainder spread across first N batches
"""

from math import ceil

import yellowdog_cli.instantiate as instantiate_module
import yellowdog_cli.provision as provision_module
from yellowdog_cli.instantiate import CRBatch
from yellowdog_cli.provision import WPBatch

_wp_alloc = provision_module._allocate_nodes_to_batches
_cr_alloc = instantiate_module._allocate_nodes_to_batches


# ---------------------------------------------------------------------------
# provision._allocate_nodes_to_batches
# ---------------------------------------------------------------------------


class TestProvisionAllocateNodesToBatches:
    # ------------------------------------------------------------------
    # Batch count
    # ------------------------------------------------------------------

    def test_single_batch_when_max_nodes_fits_in_batch_size(self):
        batches = _wp_alloc(
            max_batch_size=10000, initial_nodes=3, min_nodes=0, max_nodes=3
        )
        assert len(batches) == 1

    def test_batch_count_is_ceil_of_max_nodes_over_batch_size(self):
        # max_nodes=10, batch_size=3 → ceil(10/3) = 4
        batches = _wp_alloc(
            max_batch_size=3, initial_nodes=10, min_nodes=0, max_nodes=10
        )
        assert len(batches) == ceil(10 / 3)

    def test_exact_division_produces_correct_batch_count(self):
        # max_nodes=9, batch_size=3 → 3 batches
        batches = _wp_alloc(max_batch_size=3, initial_nodes=9, min_nodes=3, max_nodes=9)
        assert len(batches) == 3

    # ------------------------------------------------------------------
    # Totals preserved
    # ------------------------------------------------------------------

    def test_sum_of_initial_nodes_equals_input(self):
        batches = _wp_alloc(max_batch_size=3, initial_nodes=7, min_nodes=2, max_nodes=9)
        assert sum(b.initial_nodes for b in batches) == 7

    def test_sum_of_min_nodes_equals_input(self):
        batches = _wp_alloc(max_batch_size=3, initial_nodes=7, min_nodes=2, max_nodes=9)
        assert sum(b.min_nodes for b in batches) == 2

    def test_sum_of_max_nodes_equals_input(self):
        batches = _wp_alloc(max_batch_size=3, initial_nodes=7, min_nodes=2, max_nodes=9)
        assert sum(b.max_nodes for b in batches) == 9

    # ------------------------------------------------------------------
    # Even distribution (no remainder)
    # ------------------------------------------------------------------

    def test_exact_division_distributes_evenly(self):
        # 9 max_nodes, batch_size=3 → 3 batches of 3
        batches = _wp_alloc(max_batch_size=3, initial_nodes=9, min_nodes=3, max_nodes=9)
        assert all(b.initial_nodes == 3 for b in batches)
        assert all(b.min_nodes == 1 for b in batches)
        assert all(b.max_nodes == 3 for b in batches)

    # ------------------------------------------------------------------
    # Remainder distribution
    # ------------------------------------------------------------------

    def test_remainder_initial_nodes_spread_to_first_batches(self):
        # initial_nodes=10, 4 batches → floor(10/4)=2 each, remainder 2
        # first 2 batches get 3, last 2 get 2
        batches = _wp_alloc(
            max_batch_size=3, initial_nodes=10, min_nodes=0, max_nodes=10
        )
        initial = [b.initial_nodes for b in batches]
        assert initial == sorted(initial, reverse=True)  # descending (extras at front)
        assert max(initial) - min(initial) <= 1

    def test_remainder_max_nodes_spread_to_first_batches(self):
        # max_nodes=10, batch_size=3 → 4 batches, floor(10/4)=2 each, remainder 2
        batches = _wp_alloc(
            max_batch_size=3, initial_nodes=10, min_nodes=0, max_nodes=10
        )
        max_vals = [b.max_nodes for b in batches]
        assert max(max_vals) - min(max_vals) <= 1

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_min_nodes_zero_across_all_batches(self):
        batches = _wp_alloc(max_batch_size=3, initial_nodes=9, min_nodes=0, max_nodes=9)
        assert all(b.min_nodes == 0 for b in batches)

    def test_initial_nodes_zero_all_batches_have_zero_initial(self):
        batches = _wp_alloc(max_batch_size=3, initial_nodes=0, min_nodes=0, max_nodes=9)
        assert all(b.initial_nodes == 0 for b in batches)

    def test_returns_list_of_wp_batch_instances(self):
        batches = _wp_alloc(
            max_batch_size=10000, initial_nodes=5, min_nodes=0, max_nodes=5
        )
        assert all(isinstance(b, WPBatch) for b in batches)

    def test_single_node_single_batch(self):
        batches = _wp_alloc(
            max_batch_size=10000, initial_nodes=1, min_nodes=0, max_nodes=1
        )
        assert len(batches) == 1
        assert batches[0].initial_nodes == 1
        assert batches[0].max_nodes == 1


# ---------------------------------------------------------------------------
# instantiate._allocate_nodes_to_batches
# ---------------------------------------------------------------------------


class TestInstantiateAllocateNodesToBatches:
    # ------------------------------------------------------------------
    # Batch count
    # ------------------------------------------------------------------

    def test_single_batch_when_initial_nodes_fits_in_batch_size(self):
        batches = _cr_alloc(max_batch_size=10000, initial_nodes=5)
        assert len(batches) == 1

    def test_batch_count_is_ceil_of_initial_nodes_over_batch_size(self):
        # initial_nodes=10, batch_size=3 → ceil(10/3) = 4
        batches = _cr_alloc(max_batch_size=3, initial_nodes=10)
        assert len(batches) == ceil(10 / 3)

    def test_exact_division_produces_correct_batch_count(self):
        batches = _cr_alloc(max_batch_size=3, initial_nodes=9)
        assert len(batches) == 3

    # ------------------------------------------------------------------
    # Totals preserved
    # ------------------------------------------------------------------

    def test_sum_of_target_instances_equals_input(self):
        batches = _cr_alloc(max_batch_size=3, initial_nodes=10)
        assert sum(b.target_instances for b in batches) == 10

    def test_sum_preserved_for_exact_division(self):
        batches = _cr_alloc(max_batch_size=3, initial_nodes=9)
        assert sum(b.target_instances for b in batches) == 9

    # ------------------------------------------------------------------
    # Even distribution (no remainder)
    # ------------------------------------------------------------------

    def test_exact_division_distributes_evenly(self):
        batches = _cr_alloc(max_batch_size=3, initial_nodes=9)
        assert all(b.target_instances == 3 for b in batches)

    # ------------------------------------------------------------------
    # Remainder distribution
    # ------------------------------------------------------------------

    def test_remainder_spread_to_first_batches(self):
        # initial_nodes=10, batch_size=3 → 4 batches: [3, 3, 2, 2]
        batches = _cr_alloc(max_batch_size=3, initial_nodes=10)
        counts = [b.target_instances for b in batches]
        assert counts == sorted(counts, reverse=True)  # extras at front
        assert max(counts) - min(counts) <= 1

    # ------------------------------------------------------------------
    # Zero instances
    # ------------------------------------------------------------------

    def test_zero_initial_nodes_returns_single_zero_batch(self):
        batches = _cr_alloc(max_batch_size=10000, initial_nodes=0)
        assert len(batches) == 1
        assert batches[0].target_instances == 0

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_returns_list_of_cr_batch_instances(self):
        batches = _cr_alloc(max_batch_size=10000, initial_nodes=5)
        assert all(isinstance(b, CRBatch) for b in batches)

    def test_single_node_single_batch(self):
        batches = _cr_alloc(max_batch_size=10000, initial_nodes=1)
        assert len(batches) == 1
        assert batches[0].target_instances == 1

    def test_batch_size_of_one_gives_one_batch_per_node(self):
        batches = _cr_alloc(max_batch_size=1, initial_nodes=5)
        assert len(batches) == 5
        assert all(b.target_instances == 1 for b in batches)
