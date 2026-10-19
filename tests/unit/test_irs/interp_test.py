import math, QuantLib as ql
exec(open("pillar_test2.py").read().split('# Step 5')[0].replace('print(','(lambda *a,**k:None)('))
xs=[p-ref for p,_ in pill]; zs=[z for _,z in pill]
ts=[x/365 for x in xs]; lnd=[-z*t for z,t in zip(zs,ts)]
def seg(t):
    for i in range(len(ts)-1):
        if ts[i]<=t<=ts[i+1]: return i
def lin_zero(t):
    i=seg(t); w=(t-ts[i])/(ts[i+1]-ts[i]); return math.exp(-(zs[i]+w*(zs[i+1]-zs[i]))*t)
def loglin(t):
    i=seg(t); w=(t-ts[i])/(ts[i+1]-ts[i]); return math.exp(lnd[i]+w*(lnd[i+1]-lnd[i]))
# QuantLib cubic / monotonic on zero
dates=[ref]+[p for p,_ in pill]; zz=[zs[0]]+zs
curves={'QL Linear zero':ql.ZeroCurve(dates,zz,ql.Actual365Fixed(),ql.UnitedStates(ql.UnitedStates.SOFR),ql.Linear(),ql.Continuous),
 'QL Cubic zero':ql.CubicZeroCurve(dates,zz,ql.Actual365Fixed()),
 'QL MonoCubic zero':ql.MonotonicCubicZeroCurve(dates,zz,ql.Actual365Fixed()),
 'QL NaturalCubic zero':ql.NaturalCubicZeroCurve(dates,zz,ql.Actual365Fixed())}
targets=[(ql.Date(28,5,2027),0.958306),(ql.Date(30,11,2027),0.941092)]
for name,f in [('linear zero',lin_zero),('log-linear DF',loglin)]:
    print(f"{name:22}", ['%.6f'%f((d-ref)/365) for d,_ in targets])
for n,c in curves.items():
    c.enableExtrapolation(); print(f"{n:22}",['%.6f'%c.discount(d) for d,_ in targets])
print('BBG                   ',[str(b) for _,b in targets])
