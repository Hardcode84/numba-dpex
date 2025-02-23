# SPDX-FileCopyrightText: 2020 - 2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

from numba import njit


@njit(debug=True)
def foo(arg):
    l1 = arg + 6
    l2 = arg * 5.43
    l3 = (arg, l1, l2, "bar")
    print(arg, l1, l2, l3)


def main():
    result = foo(987)
    print(result)


if __name__ == "__main__":
    main()
    print("Done ...")
