import math
import QuantLib as ql

ref = ql.Date(31, 3, 2026)
raw = """07-04-2026 3.6524 0.999088 3.70182
14-04-2026 3.6537 0.998379 3.70182
21-04-2026 3.65405 0.997671 3.70094
30-04-2026 3.66085 0.996554 3.70544
30-05-2026 3.6705 0.993617 3.7097
29-06-2026 3.6768 0.990591 3.71046
29-07-2026 3.67945 0.987384 3.70721
28-08-2026 3.6803 0.984400 3.70252
27-09-2026 3.683 0.981423 3.69965
27-10-2026 3.6875 0.978352 3.69836
26-11-2026 3.69125 0.975394 3.69651
26-12-2026 3.6949 0.972159 3.69401
25-01-2027 3.6975 0.969332 3.69122
24-02-2027 3.6985 0.966628 3.68706
26-03-2027 3.70095 0.963638 3.68376
22-09-2027 3.66 0.946232 3.65444
30-03-2028 3.62105 0.930085 3.60422
30-03-2029 3.57805 0.898410 3.56121
30-03-2030 3.58525 0.866701 3.5692
30-03-2031 3.62155 0.834704 3.60763"""
rows = []
for l in raw.splitlines():
    d, m, df, z = l.split()
    dd, mm, yy = map(int, d.split("-"))
    rows.append((ql.Date(dd, mm, yy), float(m), float(df), float(z) / 100))

print("=== Step 1: implied days under candidate bases ===")
print(f"{'Listed':>11} {'ListDays':>8} {'A365':>9} {'A360':>9}")
for d, m, df, z in rows:
    t = -math.log(df) / z
    print(f"{d.ISO():>11} {d-ref:>8} {t*365:>9.3f} {t*360:>9.3f}")

# Step 2: blind tenor grid
cals = {"SOFR": ql.UnitedStates(ql.UnitedStates.SOFR),
        "GovtBond": ql.UnitedStates(ql.UnitedStates.GovernmentBond)}
tenors = [ql.Period(n, ql.Days) for n in range(1, 8)] + \
         [ql.Period(n, ql.Weeks) for n in range(1, 4)] + \
         [ql.Period(n, ql.Months) for n in range(1, 61)]
convs = {"MF": ql.ModifiedFollowing, "F": ql.Following, "U": ql.Unadjusted}

print("\n=== Step 2: candidate (tenor, spot lag, cal, conv, EOM) matching implied A365 day ===")
summary = []
for d, m, df, z in rows:
    t = -math.log(df) / z
    target = round(t * 365)
    hits = set()
    for cn, cal in cals.items():
        for lag in (0, 1, 2):
            spot = cal.advance(ref, lag, ql.Days)
            for p in tenors:
                for vn, cv in convs.items():
                    for eom in (False, True):
                        if p.units() == ql.Days:
                            pd = cal.advance(spot, p, cv)
                        else:
                            pd = cal.advance(spot, p, cv, eom)
                        if pd - ref == target:
                            hits.add((str(p).replace(" ", ""), lag, cn, vn, eom, pd.ISO()))
    # report compactly: by (tenor, lag)
    by = {}
    for tn, lag, cn, vn, eom, iso in hits:
        by.setdefault((tn, lag, iso), set()).add(f"{cn}/{vn}/{'EOM' if eom else 'noEOM'}")
    summary.append((d, target, by))
    print(f"{d.ISO()} target {target}d:")
    for (tn, lag, iso), s in sorted(by.items(), key=lambda x: x[0][1]):
        print(f"   tenor {tn:>6} T+{lag} -> {iso}   [{', '.join(sorted(s))}]")
    if not by:
        print("   NO MATCH")
