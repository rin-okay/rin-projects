import pathlib
import sys
import random
import unittest

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from seed_core import parse_seed, get_map_seeds, temporary_preprocessor_seed


class SeedLogicTests(unittest.TestCase):
    def test_native_selected_only_on_default_options(self):
        self.assertEqual(parse_seed(-1), -1)
        self.assertEqual(get_map_seeds([100, 101, 102, 103], 4, 0, False, -1), [100])

    def test_per_image_uses_incremented_image_seeds(self):
        self.assertEqual(get_map_seeds([100, 101, 102, 103], 4, 0, True, -1), [100, 101, 102, 103])

    def test_next_iteration_uses_next_image_seeds(self):
        self.assertEqual(get_map_seeds(list(range(100, 112)), 4, 1, True, -1), [104, 105, 106, 107])

    def test_independent_static_and_incremented_seed(self):
        self.assertEqual(get_map_seeds(list(range(100, 112)), 4, 2, False, 700), [700])
        self.assertEqual(get_map_seeds(list(range(100, 112)), 4, 2, True, 700), [708, 709, 710, 711])

    def test_rollover(self):
        self.assertEqual(get_map_seeds([1, 2], 2, 0, True, 0xFFFFFFFF), [0xFFFFFFFF, 0])

    def test_reproducible_and_random_state_restored(self):
        np.random.seed(910)
        random.seed(400)
        numpy_before = np.random.get_state()
        python_before = random.getstate()
        with temporary_preprocessor_seed(505):
            a = np.random.uniform(size=(4, 4))
            x = random.random()
        self.assertEqual(random.getstate(), python_before)
        self.assertEqual(np.random.get_state()[1].tolist(), numpy_before[1].tolist())
        with temporary_preprocessor_seed(505):
            b = np.random.uniform(size=(4, 4))
            y = random.random()
        self.assertTrue(np.array_equal(a, b))
        self.assertEqual(x, y)


if __name__ == "__main__":
    unittest.main()
