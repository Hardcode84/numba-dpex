# SPDX-FileCopyrightText: 2020 - 2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for dpnp ndarray constructors."""

import dpctl
import dpctl.tensor as dpt
import dpnp
import numpy
import pytest

from numba_dpex import dpjit

shapes = [11, (3, 7)]
dtypes = [dpnp.int32, dpnp.int64, dpnp.float32, dpnp.float64]
usm_types = ["device", "shared", "host"]
devices = ["cpu", "unknown"]


@pytest.mark.parametrize("shape", shapes)
@pytest.mark.parametrize("dtype", dtypes)
@pytest.mark.parametrize("usm_type", usm_types)
@pytest.mark.parametrize("device", devices)
def test_dpnp_ones(shape, dtype, usm_type, device):
    @dpjit
    def func1(shape):
        c = dpnp.ones(
            shape=shape, dtype=dtype, usm_type=usm_type, device=device
        )
        return c

    a = numpy.ones(shape, dtype=dtype)

    try:
        c = func1(shape)
    except Exception:
        pytest.fail("Calling dpnp.empty inside dpjit failed")

    if len(c.shape) == 1:
        assert c.shape[0] == shape
    else:
        assert c.shape == shape

    assert c.dtype == dtype
    assert c.usm_type == usm_type
    if device != "unknown":
        assert (
            c.sycl_device.filter_string
            == dpctl.SyclDevice(device).filter_string
        )
    else:
        c.sycl_device.filter_string == dpctl.SyclDevice().filter_string

    assert numpy.array_equal(dpt.asnumpy(c._array_obj), a)
