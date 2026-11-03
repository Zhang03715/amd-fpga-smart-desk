"""Reproducible real-driver numerical trials, separate from OCR accuracy.

Call run_trials with a configured hardware VisionAccelerator. The returned data
is not labelled board evidence: the caller must record platform/overlay hashes.
"""
import time
import numpy as np
from .pointwise import pointwise_reference


def run_trials(driver, seed=20261019):
    rng = np.random.default_rng(seed)
    records = []
    start = time.perf_counter()
    for channels in (1, 3, 16, 240, 480):
        for mask in (1, 31, 255):
            weights = rng.integers(-128, 128, (8, channels), dtype=np.int8)
            activations = rng.integers(-128, 128, (3, channels), dtype=np.int8)
            biases = rng.integers(-10000, 10001, 8, dtype=np.int32)
            multipliers = rng.integers(1, 65536, 8, dtype=np.int32)
            shifts = np.full(8, 24, dtype=np.int32)
            # Include the signed -128 extreme through the complete bus path.
            if channels == 480:
                weights[0, :] = -128
                activations[0, :] = -128
            cpu_start = time.perf_counter()
            _, expected = pointwise_reference(activations, weights, biases,
                                               multipliers.tolist(), shifts.tolist())
            expected[:, [lane for lane in range(8) if not mask & (1<<lane)]] = 0
            cpu_seconds = time.perf_counter()-cpu_start
            config_start = time.perf_counter()
            driver.configure(weights, biases, multipliers, shifts, mask)
            config_seconds = time.perf_counter()-config_start
            durations = []
            for position, activation in enumerate(activations):
                transfer_start = time.perf_counter()
                actual = driver.run(activation)
                durations.append(time.perf_counter()-transfer_start)
                if not np.array_equal(actual, expected[position]):
                    raise AssertionError(f'Hardware result mismatch: C={channels}, mask={mask}, position={position}; expected={expected[position].tolist()}, actual={np.asarray(actual).tolist()}')
            records.append(dict(channels=channels, lane_mask=mask, positions=3,
                                cpu_reference_seconds=cpu_seconds,
                                configuration_seconds=config_seconds,
                                allocation_dma_compute_readback_seconds=durations))
    return dict(seed=seed, blocks=15, transactions=45, exact_matches=45,
                elapsed_seconds=time.perf_counter()-start, records=records,
                limitation='Integer protocol fixtures only; no OCR/model accuracy or speedup claim')
