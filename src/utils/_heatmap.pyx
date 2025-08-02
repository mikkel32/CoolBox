# cython: boundscheck=False
# cython: wraparound=False
# Optional heatmap helpers implemented in Cython

import cython

@cython.boundscheck(False)
@cython.wraparound(False)
cpdef double decay_and_bump(double[:, :] grid,
                            double decay,
                            double global_decay,
                            int gx,
                            int gy):
    cdef Py_ssize_t h = grid.shape[0]
    cdef Py_ssize_t w = grid.shape[1]
    cdef Py_ssize_t y, x
    global_decay *= decay
    if global_decay < 1e-6:
        for y in range(h):
            for x in range(w):
                grid[y, x] *= global_decay
        global_decay = 1.0
    grid[gy, gx] += 1.0 / global_decay
    return global_decay
