#!/usr/bin/env python3
"""Quick diagnostic check of health.json"""
import json
import sys

try:
    with open('workspace/health.json') as f:
        d = json.load(f)
    
    pi = d.get('pi', {})
    cov = d.get('cov', {})
    sens = d.get('sensory', {})
    
    print('🔍 DIAGNOSTIC ANALYSIS:')
    print(f'  Fill: {d.get("fill_pct", 0):.1f}% (target: {pi.get("target_fill", 0):.0f}%)')
    print(f'  PI Error: {pi.get("e_fill", 0):+.3f} (should be negative when fill < target)')
    print(f'  PI Integ Fill: {pi.get("integ_fill", 0):.2f} (clamped at ±2.0)')
    esn_lambda = d.get("lambda1_esn")
    if esn_lambda is None:
        print(f'  λ₁ ESN: N/A (ESN not initialized yet)')
    else:
        print(f'  λ₁ ESN: {esn_lambda:.3f} (comfort: 1.0-1.6)')
    print(f'  Gate: {d.get("gate", 0):.3f} (PI raw: {d.get("gate_raw", 0):.3f})')
    print(f'  Cov Keep: {cov.get("keep", 0):.3f} (target: {cov.get("target_keep", 0):.3f}, floor: {cov.get("keep_floor", 0):.3f})')
    print(f'  Backlog: {sens.get("backlog", 0)} (fill: {sens.get("backlog_fill_pct", 0):.1f}%)')
    print(f'  CALM: {d.get("calm", False)}')
    print('')
    print('💡 KEY INSIGHTS:')
    
    e_fill = pi.get('e_fill', 0)
    if e_fill < -0.05:
        print('  ✅ PI wants to raise fill (negative error = below target)')
    else:
        print('  ⚠️  PI error suggests fill should be higher')
    
    keep = cov.get('keep', 0)
    if keep < 0.15:
        print('  ⚠️  Covariance decay is very aggressive (keep < 0.15)')
    elif keep < 0.30:
        print('  🟡 Covariance decay is aggressive (keep < 0.30)')
    else:
        print('  ✅ Covariance decay is moderate')
    
    if sens.get('backlog', 0) == 0:
        print('  ⚠️  No sensory input in backlog (gate may be blocking everything)')
    else:
        print('  ✅ Sensory input is flowing')
        
except FileNotFoundError:
    print('❌ health.json not found - minime may not be running')
    sys.exit(1)
except Exception as e:
    print(f'❌ Error: {e}')
    sys.exit(1)

