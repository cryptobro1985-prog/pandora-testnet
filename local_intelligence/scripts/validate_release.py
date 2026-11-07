#!/usr/bin/env python3
"""Run offline software, provenance and compatibility validation; no deployment."""
from __future__ import annotations
import argparse,hashlib,json,os,subprocess,sys,time,xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,default=ROOT/'validation/current')
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'src')
    env.update(OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2',
               CORTEX_BACKEND='disabled',LOCAL_ONLY_MONITOR_URL='',GITHUB_TOKEN='',GH_TOKEN='')
    commands=[
        ('dependencies',[sys.executable,'-m','pip','check']),
        ('software_tests',[sys.executable,'-m','pytest','-q','tests',
           'src/research/hype_local_v5/tests','src/research/hype_history_backfill/test_integrity.py',
           'src/research/hype_local_only/tests',
           '--junitxml='+str(out/'software.xml')]),
        ('quantum_self',[sys.executable,'-m','research.hype_quant.test_self']),
        ('features_116',[sys.executable,'-m','research.hype_quant.test_116_features']),
        ('legacy_cortex_self',[sys.executable,'-m','research.hype_quant.test_astra_cortex']),
        ('compact_roundtrip',[sys.executable,'src/research/hype_local_v5/test_compact_smoke.py']),
    ]
    checks=[]
    for name,cmd in commands:
        start=time.monotonic()
        with (out/(name+'.log')).open('w') as log:
            run=subprocess.run(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        entry={'name':name,'command':cmd,'exit_code':run.returncode,
               'seconds':round(time.monotonic()-start,3),'log':name+'.log'}
        if name=='software_tests' and (out/'software.xml').exists():
            xml=ET.parse(out/'software.xml').getroot()
            suites=[xml] if xml.tag=='testsuite' else list(xml)
            entry['counts']={k:sum(int(s.attrib.get(k,0)) for s in suites)
                             for k in ['tests','failures','errors','skipped']}
        checks.append(entry);print(json.dumps(entry),flush=True)
    original=json.loads((ROOT/'docs/ORIGINAL_INPUT_HASHES.json').read_text())
    protected=[n for n in original if n.startswith(('src/research/hype_caterpillar_monitor/',
                                                  'src/research/hype_rest_relay/'))]
    changed=[n for n in protected if not (ROOT/n).exists() or
             hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=original[n]]
    report={'checks':checks,'monitor_unchanged':not changed,'protected_changes':changed,
            'offline_software_passed':all(x['exit_code']==0 for x in checks) and not changed,
            'live_exchange_verified':False,'external_llm_verified':False,
            'note':'Offline fixtures are software validation, not evidence of live market quality.'}
    (out/'REPORT.json').write_text(json.dumps(report,indent=2)+'\n')
    return int(not report['offline_software_passed'])

if __name__=='__main__':raise SystemExit(main())
