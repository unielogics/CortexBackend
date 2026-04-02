#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, json, random, sys
from datetime import date, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from unie_cortex.spine.fixture_warehouse_baseline import AUDIT_BASELINE_ORIGIN_ZIP5

RNG = random.Random(42)
CARRIERS, CW = ["UPS","FedEx","USPS","DHL"], [0.42,0.32,0.18,0.08]
DEST_ZIPS = ["10001","90210","33101","60601","75201","98101","85001","30309","02108","80202","94103","37203","78701","19103","20001"]
ZONES, ZW = ["A","B","C","D"], [0.48,0.28,0.14,0.10]
TASK_TYPES = ["pick","pack","receive","replenish"]
OPS = [f"op{i:03d}" for i in range(1,25)]
def pw(it, w):
    r = RNG.random(); a = 0.0
    for x, wt in zip(it, w, strict=True):
        a += wt
        if r <= a: return x
    return it[-1]
def rd(y):
    s, e = date(y,1,1), date(y,11,30)
    return s + timedelta(days=RNG.randint(0,(e-s).days))
def wl(p, n):
    f = open(p,"w",newline="",encoding="utf-8"); w = csv.writer(f)
    w.writerow(["TrackId","Carrier","LabelChargeUsd","WeightLb","OriginZip","DestZip","ShipDate","Sku","Qty"])
    for i in range(n):
        c = pw(CARRIERS, CW); dest = RNG.choice(DEST_ZIPS); wt = round(RNG.uniform(0.4,22.0),2)
        b = 3.8 + wt*0.55 + RNG.uniform(0,6.5)
        if c=="UPS": b *= 1.08
        if dest in ("90210","98101","33101"): b += RNG.uniform(0.8,3.2)
        d = rd(2024)
        w.writerow([f"TRK{i+1:07d}",c,round(b,2),wt,AUDIT_BASELINE_ORIGIN_ZIP5,dest,d.isoformat(),f"SKU-{RNG.randint(1000,9999)}",RNG.randint(1,4)])
    f.close()
def wt(p, n):
    f = open(p,"w",newline="",encoding="utf-8"); w = csv.writer(f)
    w.writerow(["CompletedAt","ZoneCode","WorkerId","TaskType","DurationSec","Sku"])
    for i in range(n):
        z = pw(ZONES, ZW); dur = 40 + RNG.randint(0,220)
        if z=="A": dur += RNG.randint(5,45)
        d = rd(2024); ts = f"{d.isoformat()}T{9+RNG.randint(0,9):02d}:{RNG.randint(0,59):02d}:00Z"
        w.writerow([ts,z,RNG.choice(OPS),RNG.choice(TASK_TYPES),dur,f"SKU-{RNG.randint(1000,9999)}"])
    f.close()
def wo(p, n):
    f = open(p,"w",newline="",encoding="utf-8"); w = csv.writer(f)
    w.writerow(["amazon_order_id","purchasedate","seller_sku","item_price","referral_fee","cogs","order_profit","qty_shipped","dest_zip"])
    for i in range(n):
        q = RNG.randint(1,5); lp = round(RNG.uniform(12,240),2); rev = round(lp*q,2)
        fees = round(rev*RNG.uniform(0.12,0.19),2); cogs = round(rev*RNG.uniform(0.32,0.52),2)
        prof = round(rev - fees - cogs - RNG.uniform(0.5,4.0),2); d = rd(2024)
        w.writerow([f"AMZ-{i+1:08d}",d.isoformat(),f"SKU-{RNG.randint(1000,9999)}",rev,fees,cogs,prof,q,RNG.choice(DEST_ZIPS)])
    f.close()
def wa(p, n):
    f = open(p,"w",newline="",encoding="utf-8"); w = csv.writer(f)
    w.writerow(["AsnLineId","PoId","Sku","QtyExpected","QtyReceived","ExpectedAt","ReceivedAt","SupplierId","DockZone"])
    for i in range(n):
        d = rd(2024); qe = float(RNG.randint(5, 500)); qr = qe - RNG.randint(0, min(3, int(qe)))
        recv = f"{d.isoformat()}T{10+RNG.randint(0,7):02d}:{RNG.randint(0,59):02d}:00Z"
        w.writerow([f"ASN-{i+1:07d}",f"PO-{RNG.randint(10000,99999)}",f"SKU-{RNG.randint(1000,9999)}",qe,qr,d.isoformat(),recv,f"S{RNG.randint(1,9)}",pw(ZONES,ZW)])
    f.close()
def wol(p, n):
    f = open(p,"w",newline="",encoding="utf-8"); w = csv.writer(f)
    w.writerow(["OrderId","LineId","Sku","Qty","OrderedAt","ShippedAt","DestZip","Channel"])
    for i in range(n):
        d = rd(2024); ship = f"{d.isoformat()}T{11+RNG.randint(0,6):02d}:{RNG.randint(0,59):02d}:00Z"
        w.writerow([f"ORD-{i+1:08d}",f"L{i+1}",f"SKU-{RNG.randint(1000,9999)}",RNG.randint(1,6),d.isoformat(),ship,RNG.choice(DEST_ZIPS),pw(["AMZ","DTC","B2B"],[0.55,0.35,0.1])])
    f.close()
def wb(p, n):
    f = open(p,"w",newline="",encoding="utf-8"); w = csv.writer(f)
    w.writerow(["InvoiceId","LineId","FeeCode","ServiceStart","ServiceEnd","AmountUsd","Currency"])
    for i in range(n):
        d = rd(2024); end = d + timedelta(days=RNG.randint(1, 28))
        w.writerow([f"INV-{i+1:07d}",f"BL{i+1}",pw(["WH_RENT","LABOR","FUEL","TECH"],[0.35,0.35,0.2,0.1]),d.isoformat(),end.isoformat(),round(RNG.uniform(120, 9500),2),"USD"])
    f.close()
def we(p, n):
    f = open(p,"w",newline="",encoding="utf-8"); w = csv.writer(f)
    w.writerow(["EmployeeId","Role","HireDate","ShiftName","HourlyRateUsd"])
    for i in range(n):
        hd = rd(2022)
        w.writerow([f"E{i+1:05d}",pw(["picker","packer","receiver","lead"],[0.45,0.3,0.15,0.1]),hd.isoformat(),pw(["day","swing","night"],[0.5,0.35,0.15]),round(RNG.uniform(18.5, 32.0),2)])
    f.close()
def wm(p):
    m = {
        "labels":{"TrackId":"tracking_number","Carrier":"carrier","LabelChargeUsd":"label_amount_usd","WeightLb":"weight_lb","OriginZip":"origin_postal","DestZip":"dest_postal","ShipDate":"ship_date","Sku":"sku","Qty":"qty"},
        "tasks":{"CompletedAt":"completed_at","ZoneCode":"zone","WorkerId":"operator_id","TaskType":"task_type","DurationSec":"duration_sec","Sku":"sku"},
        "order_financials":{"amazon_order_id":"order_external_id","purchasedate":"order_date","seller_sku":"sku","item_price":"revenue_usd","referral_fee":"marketplace_fees_usd","cogs":"product_cogs_usd","order_profit":"profit_usd","qty_shipped":"quantity","dest_zip":"ship_to_postal"},
        "asn":{"AsnLineId":"asn_line_id","PoId":"po_id","Sku":"sku","QtyExpected":"qty_expected","QtyReceived":"qty_received","ExpectedAt":"expected_at_iso","ReceivedAt":"received_at_iso","SupplierId":"supplier_id","DockZone":"dock_zone"},
        "order_lines":{"OrderId":"order_external_id","LineId":"line_id","Sku":"sku","Qty":"quantity","OrderedAt":"ordered_at_iso","ShippedAt":"shipped_at_iso","DestZip":"ship_to_postal","Channel":"channel"},
        "billing":{"InvoiceId":"invoice_id","LineId":"line_id","FeeCode":"fee_code","ServiceStart":"service_start_iso","ServiceEnd":"service_end_iso","AmountUsd":"amount_usd","Currency":"currency"},
        "employees":{"EmployeeId":"employee_id","Role":"role","HireDate":"hire_date_iso","ShiftName":"shift_name","HourlyRateUsd":"hourly_rate_usd"},
    }
    open(p,"w",encoding="utf-8").write(json.dumps(m,indent=2))
def main():
    _root = Path(__file__).resolve().parent.parent
    _def_out = _root / "tests" / "fixtures" / "audit"
    ap = argparse.ArgumentParser(description="Generate mock assessment CSVs + column_mapping.json.")
    ap.add_argument("--rows", type=int, default=500)
    ap.add_argument("--out", type=Path, default=_def_out)
    a = ap.parse_args()
    o = a.out
    o.mkdir(parents=True, exist_ok=True)
    n = max(1, a.rows)
    wl(o/"labels.csv",n); wt(o/"tasks.csv",n); wo(o/"order_financials.csv",n)
    wa(o/"asn.csv",n); wol(o/"order_lines.csv",n); wb(o/"billing.csv",n); we(o/"employees.csv",n)
    wm(o/"column_mapping.json")
    print(f"Wrote {n} rows each -> {o.resolve()}")
if __name__=="__main__": main()
