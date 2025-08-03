from libc.math cimport hypot
cimport cython

@cython.boundscheck(False)
@cython.wraparound(False)
def update_weights(
    samples,
    double cursor_x,
    double cursor_y,
    double velocity,
    path_history,
    tuning,
    int own_pid,
    weights,
    pid_history,
    heatmap,
    active_pid,
):
    cdef double power = 1.0
    cdef double vel_factor, w
    cdef double cx, cy, dist, diag
    cdef double left, top, right, bottom, near_x, near_y, val
    cdef double area_f, heat
    cdef int area, inside
    cdef object info
    cdef object px, py
    cdef tuple rect

    for info in samples[::-1]:
        if info.pid == own_pid or info.pid is None:
            continue
        vel_factor = 1.0 / (1.0 + velocity * tuning.velocity_scale)
        w = tuning.sample_weight * power * vel_factor
        if active_pid is not None and info.pid == active_pid:
            w *= tuning.active_bonus
        rect = info.rect
        if rect is not None and tuning.area_weight:
            area = rect[2] * rect[3]
            if area:
                w += tuning.area_weight / area
        if rect is not None and tuning.center_weight:
            cx = rect[0] + rect[2] / 2.0
            cy = rect[1] + rect[3] / 2.0
            dist = hypot(cx - cursor_x, cy - cursor_y)
            diag = hypot(rect[2], rect[3])
            if diag != 0:
                dist = dist / diag
                if dist > 1.0:
                    dist = 1.0
                w += tuning.center_weight * (1.0 - dist)
        if rect is not None and tuning.edge_penalty:
            left = rect[0]
            top = rect[1]
            right = left + rect[2]
            bottom = top + rect[3]
            near_x = cursor_x - left
            if near_x < 0:
                near_x = -near_x
            val = cursor_x - right
            if val < 0:
                val = -val
            if val < near_x:
                near_x = val
            near_y = cursor_y - top
            if near_y < 0:
                near_y = -near_y
            val = cursor_y - bottom
            if val < 0:
                val = -val
            if val < near_y:
                near_y = val
            if near_x <= tuning.edge_buffer or near_y <= tuning.edge_buffer:
                val = 1.0 - tuning.edge_penalty
                if val < 0.0:
                    val = 0.0
                w *= val
        if rect is not None and tuning.path_weight and path_history:
            inside = 0
            for px, py in path_history:
                if rect[0] <= px <= rect[0] + rect[2] and rect[1] <= py <= rect[1] + rect[3]:
                    inside += 1
            w += tuning.path_weight * inside / len(path_history)
        if tuning.heatmap_weight and rect is not None:
            heat = heatmap.region_score(rect)
            area_f = rect[2] * rect[3]
            if area_f == 0:
                area_f = 1.0
            w += tuning.heatmap_weight * heat / area_f
        weights[info.pid] = weights.get(info.pid, 0.0) + w
        power *= tuning.sample_decay

    power = 1.0
    for pid in pid_history[::-1]:
        vel_factor = 1.0 / (1.0 + velocity * tuning.velocity_scale)
        w = tuning.history_weight * power * vel_factor
        if active_pid is not None and pid == active_pid:
            w *= tuning.active_bonus
        weights[pid] = weights.get(pid, 0.0) + w
        power *= tuning.history_decay

    return weights
