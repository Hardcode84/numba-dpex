# SPDX-FileCopyrightText: 2020 - 2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import os

import llvmlite.binding as ll
from numba.np.ufunc.decorators import Vectorize

from numba_dpex.vectorizers import Vectorize as DpexVectorize


def load_dpctl_sycl_interface():
    """Permanently loads the ``DPCTLSyclInterface`` library provided by dpctl.

    The ``DPCTLSyclInterface`` library provides C wrappers over SYCL functions
    that are directly invoked from the LLVM modules generated by numba_dpex.
    We load the library once at the time of initialization using llvmlite's
    load_library_permanently function.

    Raises:
        ImportError: If the ``DPCTLSyclInterface`` library could not be loaded.
    """
    import glob
    import platform as plt

    import dpctl

    platform = plt.system()
    if platform == "Windows":
        paths = glob.glob(
            os.path.join(
                os.path.dirname(dpctl.__file__), "*DPCTLSyclInterface.dll"
            )
        )
    else:
        paths = glob.glob(
            os.path.join(
                os.path.dirname(dpctl.__file__), "*DPCTLSyclInterface.so.0"
            )
        )

    if len(paths) == 1:
        ll.load_library_permanently(paths[0])
    else:
        raise ImportError

    def init_dpex_vectorize():
        return DpexVectorize

    Vectorize.target_registry.ondemand["dpex"] = init_dpex_vectorize
