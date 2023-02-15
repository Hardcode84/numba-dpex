# SPDX-FileCopyrightText: 2022 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

"""_summary_
"""

import hashlib

from numba.core import sigutils, types
from numba.core.serialize import dumps
from numba.core.typing.templates import AbstractTemplate, ConcreteTemplate

from numba_dpex import config
from numba_dpex.core.caching import LRUCache, NullCache, build_key
from numba_dpex.core.compiler import compile_with_dpex
from numba_dpex.core.descriptor import dpex_kernel_target
from numba_dpex.core.types import USMNdArray
from numba_dpex.utils import npytypes_array_to_dpex_array


class DpexFunction(object):
    """Class to materialize dpex function

    Helper class to eager compile a specialized `numba_dpex.func`
    decorated Python function into a LLVM function with `spir_func`
    calling convention.

    A specialized `numba_dpex.func` decorated Python function is one
    where the user has specified a signature or a list of signatures
    for the function. The function gets compiled as soon as the Python
    program is loaded, i.e., eagerly, instead of JIT compilation once
    the function is invoked.
    """

    def __init__(self, pyfunc, debug=False):
        """Constructor for `DpexFunction`

        Args:
            pyfunc (`function`): A python function to be compiled.
            debug (`bool`, optional): Debug option for compilation.
                Defaults to `False`.
        """
        self._pyfunc = pyfunc
        self._debug = debug

    def compile(self, arg_types, return_types):
        """The actual compilation function.

        Args:
            arg_types (`tuple`): Function argument types in a tuple.
            return_types (`numba.core.types.scalars.Integer`):
                An integer value to specify the return type.

        Returns:
            `numba.core.compiler.CompileResult`: The compiled result
        """

        cres = compile_with_dpex(
            pyfunc=self._pyfunc,
            pyfunc_name=self._pyfunc.__name__,
            return_type=return_types,
            target_context=dpex_kernel_target.target_context,
            typing_context=dpex_kernel_target.typing_context,
            args=arg_types,
            is_kernel=False,
            debug=self._debug,
        )
        func = cres.library.get_function(cres.fndesc.llvm_func_name)
        cres.target_context.mark_ocl_device(func)

        return cres


class DpexFunctionTemplate(object):
    """Helper class to compile an unspecialized `numba_dpex.func`

    A helper class to JIT compile an unspecialized `numba_dpex.func`
    decorated Python function into an LLVM function with `spir_func`
    calling convention.
    """

    def __init__(self, pyfunc, debug=False, enable_cache=True):
        """Constructor for `DpexFunctionTemplate`

        Args:
            pyfunc (function): A python function to be compiled.
            debug (bool, optional): Debug option for compilation.
                Defaults to `False`.
            enable_cache (bool, optional): Flag to turn on/off caching.
                Defaults to `True`.
        """
        self._pyfunc = pyfunc
        self._debug = debug
        self._enable_cache = enable_cache

        self._func_hash = self._create_func_hash()

        if not config.ENABLE_CACHE:
            self._cache = NullCache()
        elif self._enable_cache:
            self._cache = LRUCache(
                name="DpexFunctionTemplateCache",
                capacity=config.CACHE_SIZE,
                pyfunc=self._pyfunc,
            )
        else:
            self._cache = NullCache()
        self._cache_hits = 0

    def _create_func_hash(self):
        """Creates a tuple of sha256 hashes out of code and variable bytes extracted from the compiled funtion."""

        codebytes = self._pyfunc.__code__.co_code
        if self._pyfunc.__closure__ is not None:
            try:
                cvars = tuple(
                    [x.cell_contents for x in self._pyfunc.__closure__]
                )
                # Note: cloudpickle serializes a function differently depending
                #       on how the process is launched; e.g. multiprocessing.Process
                cvarbytes = dumps(cvars)
            except:
                cvarbytes = b""  # a temporary solution for function template
        else:
            cvarbytes = b""

        return (
            hashlib.sha256(codebytes).hexdigest(),
            hashlib.sha256(cvarbytes).hexdigest(),
        )

    @property
    def cache(self):
        """Cache accessor"""
        return self._cache

    @property
    def cache_hits(self):
        """Cache hit count accessor"""
        return self._cache_hits

    def _strip_usm_metadata(self, argtypes):
        stripped_argtypes = []
        for argty in argtypes:
            if isinstance(argty, USMNdArray):
                # Convert the USMNdArray to an abridged type that disregards the
                # usm_type, device, queue, address space attributes.
                stripped_argtypes.append(
                    (argty.ndim, argty.dtype, argty.layout)
                )
            else:
                stripped_argtypes.append(argty)

        return tuple(stripped_argtypes)

    def compile(self, args):
        """Compile a `numba_dpex.func` decorated function

        Compile a `numba_dpex.func` decorated Python function with the
        given argument types. Each signature is compiled once by caching
        the compiled function inside this object.

        Args:
            args (`tuple`): Function argument types in a tuple.

        Returns:
            `numba.core.typing.templates.Signature`: Signature of the
                compiled result.
        """

        argtypes = [
            dpex_kernel_target.typing_context.resolve_argument_type(arg)
            for arg in args
        ]

        # Generate key used for cache lookup
        stripped_argtypes = self._strip_usm_metadata(argtypes)
        codegen_magic_tuple = (
            dpex_kernel_target.target_context.codegen().magic_tuple()
        )
        key = build_key(stripped_argtypes, codegen_magic_tuple, self._func_hash)

        cres = self._cache.get(key)
        if cres is None:
            self._cache_hits += 1
            cres = compile_with_dpex(
                pyfunc=self._pyfunc,
                pyfunc_name=self._pyfunc.__name__,
                return_type=None,
                target_context=dpex_kernel_target.target_context,
                typing_context=dpex_kernel_target.typing_context,
                args=args,
                is_kernel=False,
                debug=self._debug,
            )
            func = cres.library.get_function(cres.fndesc.llvm_func_name)
            cres.target_context.mark_ocl_device(func)
            libs = [cres.library]

            cres.target_context.insert_user_function(self, cres.fndesc, libs)
            self._cache.put(key, cres)
        return cres.signature


def compile_func(pyfunc, signature, debug=False):
    """Compiles a specialized `numba_dpex.func`

    Compiles a specialized `numba_dpex.func` decorated function to native
    binary library function and returns the library wrapped inside a
    `numba_dpex.core.kernel_interface.func.DpexFunction` object.

    Args:
        pyfunc (`function`): A python function to be compiled.
        signature (`list`): A list of `numba.core.typing.templates.Signature`'s
        debug (`bool`, optional): Debug options. Defaults to `False`.

    Returns:
        `numba_dpex.core.kernel_interface.func.DpexFunction`: A `DpexFunction` object
    """

    devfn = DpexFunction(pyfunc, debug=debug)

    cres = []
    for sig in signature:
        arg_types, return_types = sigutils.normalize_signature(sig)
        arg_types = tuple(
            [
                npytypes_array_to_dpex_array(ty)
                if isinstance(ty, types.npytypes.Array)
                else ty
                for ty in arg_types
            ]
        )
        c = devfn.compile(arg_types, return_types)
        cres.append(c)

    class _function_template(ConcreteTemplate):
        unsafe_casting = False
        exact_match_required = True
        key = devfn
        cases = [c.signature for c in cres]

    cres[0].typing_context.insert_user_function(devfn, _function_template)

    for c in cres:
        c.target_context.insert_user_function(devfn, c.fndesc, [c.library])

    return devfn


def compile_func_template(pyfunc, debug=False, enable_cache=True):
    """Converts a `numba_dpex.func` function to an `AbstractTemplate`

    Converts a `numba_dpex.func` decorated function to a Numba
    `AbstractTemplate` and returns the object wrapped inside a
    `numba_dpex.core.kernel_interface.func.DpexFunctionTemplate`
    object.

    A `DpexFunctionTemplate` object is an abstract representation for
    a native function with `spir_func` calling convention that is to be
    JIT compiled once the argument types are resolved.

    Args:
        pyfunc (`function`): A python function to be compiled.
        debug (`bool`, optional): Debug options. Defaults to `False`.

    Raises:
        `AssertionError`: Raised if keyword arguments are supplied in
            the inner generic function.

    Returns:
        `numba_dpex.core.kernel_interface.func.DpexFunctionTemplate`:
            A `DpexFunctionTemplate` object.
    """

    dft = DpexFunctionTemplate(pyfunc, debug=debug, enable_cache=enable_cache)

    class _function_template(AbstractTemplate):
        unsafe_casting = False
        exact_match_required = True
        key = dft

        def generic(self, args, kws):
            if kws:
                raise AssertionError("No keyword arguments allowed.")
            return dft.compile(args)

    dpex_kernel_target.typing_context.insert_user_function(
        dft, _function_template
    )

    return dft
