"""Seed scheduling and isolated RNG helpers for ControlNet preprocessing.

Does not import Forge, making the scheduling contract independently testable.
"""
from __future__ import annotations

from contextlib import contextmanager
import random


def parse_seed(value) -> int:
    """-1 means follow the diffusion seed; otherwise accept unsigned 32-bit seed."""
    try:
        value = int(value)
    except (TypeError, ValueError, OverflowError):
        return -1
    return -1 if value < 0 else value & 0xFFFFFFFF


def get_map_seeds(all_seeds, batch_size: int, iteration: int, per_image: bool, control_seed: int):
    """Return seed for each *different map* needed by this sampling batch.

    A fixed map uses one seed and is broadcast across batch_size.  A per-image
    map uses global image offsets (iteration * batch_size + slot).  This avoids
    repeating a sequence when Forge generates subsequent batches.
    """
    control_seed = parse_seed(control_seed)
    count = batch_size if per_image else 1
    seeds = list(all_seeds or [])
    if not seeds and control_seed == -1:
        raise ValueError("The diffusion seed list is unavailable")
    result = []
    for i in range(count):
        offset = iteration * batch_size + i if per_image else 0
        if control_seed != -1:
            result.append((control_seed + offset) & 0xFFFFFFFF)
        elif offset < len(seeds):
            result.append(int(seeds[offset]) & 0xFFFFFFFF)
        else:
            raise ValueError(f"Diffusion seed for image {offset} is unavailable")
    return result


@contextmanager
def temporary_preprocessor_seed(seed):
    """Seed NumPy, Python and PyTorch CPU RNGs; restore previous states.

    CUDA preprocessors using GPU randomness are not guaranteed isolated here.
    All built-in Shuffle randomness is NumPy based.
    """
    import numpy as np

    seed = int(seed) & 0xFFFFFFFF
    np_state = np.random.get_state()
    py_state = random.getstate()
    # Do not import CUDA or initialize GPU state for Shuffle's CPU preprocessor.
    try:
        import torch
        cpu_state = torch.random.get_rng_state()
    except ImportError:
        torch = None
        cpu_state = None
    try:
        np.random.seed(seed)
        random.seed(seed)
        if torch is not None:
            # Set CPU only. torch.manual_seed() also seeds CUDA, which would
            # interfere with diffusion and may initialize a device.
            torch.random.default_generator.manual_seed(seed)
        yield
    finally:
        np.random.set_state(np_state)
        random.setstate(py_state)
        if torch is not None and cpu_state is not None:
            torch.random.set_rng_state(cpu_state)
