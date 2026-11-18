#!/usr/bin/env python3
"""Independent M1 CSV timestamp continuity audit. Research only."""
import argparse,csv,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
def minute(s):
 s=str(s).strip()
 if s.isdigit():
  n=int(s);d=datetime.fromtimestamp(n/1000 if n>10**12 else n,timezone.utc)
 else:
  d=datetime.fromisoformat(s.replace("Z","+00:00"))
  if d.tzinfo is None:raise ValueError("naive timestamp")
  d=d.astimezone(timezone.utc)
 if d.second or d.microsecond:raise ValueError("not M1 aligned")
 return int(d.timestamp()//60)
def audit(path,column,start,end):
 start,end=minute(start),minute(end)
 if end<start:raise ValueError("end before start")
 digest=hashlib.sha256();count=duplicate=out_of_order=missing=outside=0;first=last=prev=None
 with open(path,"rb") as f:
  for block in iter(lambda:f.read(1048576),b""):digest.update(block)
 with open(path,newline="") as f:
  for row in csv.DictReader(f):
   t=minute(row[column]);count+=1
   if first is None:first=t
   last=t
   if t<start or t>end:outside+=1
   if prev is not None:
    if t==prev:duplicate+=1
    elif t<prev:out_of_order+=1
    else:missing+=max(0,t-prev-1)
   prev=t
 if first is None:missing=end-start+1
 else:missing+=max(0,first-start)+max(0,end-last)
 return dict(file=str(path),sha256=digest.hexdigest(),rows=count,first_minute_utc=first,last_minute_utc=last,missing_minutes=missing,duplicate_minutes=duplicate,out_of_order=out_of_order,outside_window=outside,verified_continuous=bool(count and not any((missing,duplicate,out_of_order,outside)) and first==start and last==end),scope="M1 timestamp continuity only; not proof of provenance, fills, L50 or PnL")
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("csv");p.add_argument("--timestamp-column",default="timestamp");p.add_argument("--start",required=True);p.add_argument("--end",required=True);a=p.parse_args();print(json.dumps(audit(Path(a.csv),a.timestamp_column,a.start,a.end),indent=2))
