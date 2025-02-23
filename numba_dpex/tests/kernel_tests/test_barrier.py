# SPDX-FileCopyrightText: 2020 - 2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import dpctl
import dpctl.tensor as dpt
import numpy as np
import pytest

import numba_dpex as dpex
from numba_dpex import float32, usm_ndarray, void
from numba_dpex.tests._helper import filter_strings

f32arrty = usm_ndarray(ndim=1, dtype=float32, layout="C")


@pytest.mark.parametrize("filter_str", filter_strings)
def test_proper_lowering(filter_str):
    # This will trigger eager compilation
    @dpex.kernel(void(f32arrty))
    def twice(A):
        i = dpex.get_global_id(0)
        d = A[i]
        dpex.barrier(dpex.LOCAL_MEM_FENCE)  # local mem fence
        A[i] = d * 2

    N = 256
    arr = dpt.arange(N, dtype=dpt.float32)
    orig = dpt.asnumpy(arr)
    global_size = (N,)
    local_size = (N // 2,)
    twice[global_size, local_size](arr)
    after = dpt.asnumpy(arr)
    # The computation is correct?
    np.testing.assert_allclose(orig * 2, after)


@pytest.mark.parametrize("filter_str", filter_strings)
def test_no_arg_barrier_support(filter_str):
    @dpex.kernel(void(f32arrty))
    def twice(A):
        i = dpex.get_global_id(0)
        d = A[i]
        # no argument defaults to global mem fence
        dpex.barrier()
        A[i] = d * 2

    N = 256
    arr = dpt.arange(N, dtype=dpt.float32)
    orig = dpt.asnumpy(arr)
    twice[N](arr)
    after = dpt.asnumpy(arr)
    # The computation is correct?
    np.testing.assert_allclose(orig * 2, after)


@pytest.mark.parametrize("filter_str", filter_strings)
def test_local_memory(filter_str):
    blocksize = 10

    @dpex.kernel(void(f32arrty))
    def reverse_array(A):
        lm = dpex.local.array(shape=10, dtype=np.float32)
        i = dpex.get_global_id(0)

        # preload
        lm[i] = A[i]
        # barrier local or global will both work as we only have one work group
        dpex.barrier(dpex.LOCAL_MEM_FENCE)  # local mem fence
        # write
        A[i] += lm[blocksize - 1 - i]

    arr = dpt.arange(blocksize, dtype=dpt.float32)
    orig = dpt.asnumpy(arr)
    reverse_array[(blocksize,), (blocksize,)](arr)
    after = dpt.asnumpy(arr)
    expected = orig[::-1] + orig
    np.testing.assert_allclose(expected, after)
