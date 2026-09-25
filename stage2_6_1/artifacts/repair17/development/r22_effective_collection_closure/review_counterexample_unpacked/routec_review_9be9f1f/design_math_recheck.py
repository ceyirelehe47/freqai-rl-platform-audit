"""Independent design-only arithmetic check; no project data generation.
Source constants and claimed rule: repo ceyirelehe47/freqai-rl-platform-audit
ref 9be9f1f61075936a20d27254e4cff6462959e3f6,
stage2_6_1/report/r20_research_design_calc.py and research_design_v2.md.
Normal known-SE scenario only, not an empirically validated project model.
"""
from __future__ import annotations
import json, math
from pathlib import Path
from statistics import NormalDist

N = NormalDist()
SE = 0.0019410552950364546
MARGIN = 0.003
Z = N.inv_cdf(.95)

def power(delta: float, margin: float, k: int, actual_se: float,
          analysis_se: float | None = None) -> float:
    """Probability of a 90% z CI falling strictly in (-margin,margin)."""
    if analysis_se is None:
        analysis_se = actual_se
    half = Z * analysis_se / math.sqrt(k)
    lo, hi = -margin + half, margin - half
    if lo >= hi:
        return 0.0
    s = actual_se / math.sqrt(k)
    return N.cdf((hi-delta)/s)-N.cdf((lo-delta)/s)

def min_k(se: float, margin: float) -> int:
    return next(k for k in range(1,10000) if power(0.,margin,k,se)>=.9)

def main() -> None:
    rows=[]
    for margin in (.002,.003):
        for rho in (1.,1.25,1.5):
            claimed_k=math.ceil(((Z+N.inv_cdf(.90))*SE*rho/margin)**2)
            correct=min_k(SE*rho,margin)
            rows.append(dict(margin=margin,rho=rho,
              claimed_min_K_using_z90=claimed_k,
              achieved_power_at_claimed_K=power(0.,margin,claimed_k,SE*rho),
              correct_min_K=correct,
              achieved_power_at_correct_K=power(0.,margin,correct,SE*rho),
              power_K8=power(0.,margin,8,SE*rho)))
    boundary=[]
    for rho in (1.,1.25,1.5):
        boundary.append(dict(rho=rho,
          actual_SE=SE*rho,analysis_SE=SE,K=8,
          false_equivalence_at_true_positive_margin=power(MARGIN,MARGIN,8,SE*rho,SE)))
    old_vote=[]
    z95=N.inv_cdf(.975)
    for delta in (0.,.001,.0015,.002,.003,.004):
        pv=N.cdf(z95-delta/SE)-N.cdf(-z95-delta/SE)
        pj=.95*pv
        old_vote.append(dict(delta=delta,joint_pass_probability=pj,
              vote_ge4_of5=5*pj**4*(1-pj)+pj**5))
    half=Z*SE/math.sqrt(8)
    mean=.0015
    lower,upper=mean-half,mean+half
    result=dict(
      scope='Independent normal-model design arithmetic, not project sampling.',
      inputs=dict(SE=SE,alpha=.05,target_power=.9),
      zero_bias_formula='power = max(0, 2*Phi(margin*sqrt(K)/SE-z_0.95)-1)',
      required_margin_ratio_for_power90=Z+N.inv_cdf(.95),
      agent_used_ratio=Z+N.inv_cdf(.90),
      actual_power_at_agent_ratio=2*N.cdf(N.inv_cdf(.90))-1,
      sample_size_rows=rows,unadjusted_SE_typeI_rows=boundary,
      old_vote_rows=old_vote,
      decision_overlap_example=dict(K=8,mean=mean,lower90=lower,upper90=upper,
          equivalence=(lower>-MARGIN and upper<MARGIN),
          report_directional_calibration_rule=(lower>0)),
      limitations=['Normal known-variance model assumed for the sample-size table.',
                  'Inflation type-I rows keep the analysis SE fixed while true SE increases.',
                  'The substantive equivalence margin itself is not approved by this calculation.'])
    out=Path(__file__).with_name('design_math_recheck.json')
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
