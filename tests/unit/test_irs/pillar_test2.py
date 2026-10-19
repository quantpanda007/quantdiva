import math
import QuantLib as ql
#exec(open("/home/claude/pillar_test.py").read().split('print("=== Step 1')[0])
exec(open("pillar_test.py").read().split('print("=== Step 1')[0])

cal = ql.UnitedStates(ql.UnitedStates.SOFR)
ql.Settings.instance().evaluationDate = ref
spot = cal.advance(ref, 2, ql.Days)
tenors = ["1W","2W","3W"] + [f"{n}M" for n in range(1,13)] + ["18M","2Y","3Y","4Y","5Y"]
nominal = {"W":7,"M":30,"Y":365}

print("=== Step 3/4: reconstructed pillars and DF reproduction (ACT/365F, continuous) ===")
print(f"{'Tenor':>5} {'Listed':>11} {'Pillar':>11} {'Days':>5} {'ref+nominal?':>12} {'DF_bbg':>9} {'DF_recalc':>10} {'err':>10} {'rnd_bound':>9}")
pill = []
maxratio = 0
for (d, m, df, z), tn in zip(rows, tenors):
    p = ql.Period(tn)
    pd = cal.advance(spot, p, ql.ModifiedFollowing, False)
    n = int(tn[:-1]); u = tn[-1]
    nom = ref + n * nominal[u]
    t = (pd - ref) / 365.0
    dfr = math.exp(-z * t)
    err = dfr - df
    bound = dfr * t * 0.5e-7 + 0.5e-6  # z rounded to 1e-7 abs; DF to 6dp
    maxratio = max(maxratio, abs(err) / bound)
    pill.append((pd, z))
    print(f"{tn:>5} {d.ISO():>11} {pd.ISO():>11} {pd-ref:>5} {str(nom==d):>12} {df:>9.6f} {dfr:>10.6f} {err:>10.2e} {bound:>9.1e}")
print(f"max |err| / rounding bound = {maxratio:.2f}")

# Step 5: TC1 using linear-in-zero, flat extrapolation before first pillar
def zero_at(dt):
    t = dt - ref
    xs = [p - ref for p, _ in pill]; zs = [z for _, z in pill]
    if t <= xs[0]: return zs[0]
    for i in range(len(xs) - 1):
        if xs[i] <= t <= xs[i+1]:
            return zs[i] + (t - xs[i]) / (xs[i+1] - xs[i]) * (zs[i+1] - zs[i])
    return zs[-1]
def DF(dt): return math.exp(-zero_at(dt) * (dt - ref) / 365.0)

periods = [(ql.Date(31,5,2026), ql.Date(28,5,2027), 530000, 3.78546, 20174.40, 0.958306),
           (ql.Date(28,5,2027), ql.Date(30,11,2027), 265000, 3.64025, 4984.11, 0.941092)]
print("\n=== Step 5: TC1 cross-check ===")
for s, e, N, cb, pb, dfb in periods:
    print(f"DF({s.ISO()}) = {DF(s):.6f}   DF({e.ISO()}) = {DF(e):.6f}  (BBG pay DF {dfb})")

# daily compounding explicitly, with variants of cutoff
def coupon(s, e, cutoff):
    dates = []
    d = s
    while d < e:
        dates.append(d); d = cal.advance(d, 1, ql.Days)
    dates.append(e)
    fwds = []
    for i in range(len(dates) - 1):
        a, b = dates[i], dates[i+1]
        fwds.append((DF(a)/DF(b) - 1) / ((b - a)/360))
    if cutoff:
        # last `cutoff` fixings repeat the rate fixed `cutoff` business days before end
        for k in range(1, cutoff + 1):
            fwds[-k] = fwds[-cutoff - 1]
    g = 1.0
    for i, f in enumerate(fwds):
        g *= 1 + f * (dates[i+1] - dates[i]) / 360
    return (g - 1) / ((e - s) / 360)

fl_pv = 0
for s, e, N, cb, pb, dfb in periods:
    tau = (e - s) / 360
    ratio = (DF(s)/DF(e) - 1) / tau
    c0 = coupon(s, e, 0); c1 = coupon(s, e, 1)
    cpn = c1 + 0.001
    pay = N * cpn * tau
    fl_pv += pay * DF(e)
    print(f"{s.ISO()}->{e.ISO()}: DFratio {100*(ratio+0.001):.5f}%  daily cutoff0 {100*(c0+0.001):.5f}%  cutoff1 {100*cpn:.5f}%  BBG {cb:.5f}%"
          f"  diff(cutoff1) {(cpn*100-cb)*100:+.3f}bp  pay {pay:.2f} vs {pb}")
fx = [(ql.Date(28,5,2027), 26647.22), (ql.Date(30,11,2027), 6845.83)]
fx_pv = sum(c * DF(d) for d, c in fx)
print(f"Float PV {fl_pv:.2f} (BBG 24023.74)   Fixed PV {-fx_pv:.2f} (BBG -31978.74)   NPV {fl_pv-fx_pv:.2f} (BBG -7955.00)")
