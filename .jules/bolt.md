# Bolt's Journal - Critical Learnings Only

## 2026-07-20 - Exact Spherical Cosine Nearest Neighbor
**Learning:** To find the nearest geographic point from a static set of coordinates, we can optimize the Haversine formula check inside the loop. Since `cos(d)` is strictly decreasing on $[0, \pi]$, maximizing the spherical law of cosines expression `cos(d) = sin_la1 * sin_la2_i + cos_la1 * cos_la2_i * cos(lo1 - lo2_i)` is mathematically identical to minimizing the geodistance `d`. By pre-computing the sine/cosine of latitudes and longitudes in radians during module load, we can avoid executing any trigonometric functions, square roots, or divisions in the hot loop, leaving only 6 multiplications and 2 additions per hub.
**Action:** Always pre-compute static location coordinate trig values (sin/cos of radians) and maximize the cosine expression directly instead of calculating the full Haversine/great-circle distance inside search loops.
