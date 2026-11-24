from flask import Flask, render_template, request, jsonify, session, redirect, url_for, make_response, send_file
import sqlite3, os, csv, io, json, hashlib, secrets
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

BASE=os.path.dirname(__file__); DB=os.path.join(BASE,'smartfactory.db')
app=Flask(__name__); app.secret_key=os.environ.get('SECRET_KEY','local-demo-secret-change-before-deploy')
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')

def money(x): return int((Decimal(str(x))*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def rupees(p): return float((Decimal(int(p or 0))/100).quantize(Decimal('0.01')))
def db():
 c=sqlite3.connect(DB,timeout=15); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA journal_mode=WAL'); return c

def init_db():
 c=db(); c.executescript('''
 CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password TEXT,role TEXT);
 CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY,name TEXT,kind TEXT,state TEXT,gstin TEXT);
 CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY,name TEXT,pack_g INTEGER,selling_paise INTEGER,gst_rate REAL,hsn TEXT);
 CREATE TABLE IF NOT EXISTS materials(id INTEGER PRIMARY KEY,name TEXT,unit TEXT,rate_paise INTEGER,category TEXT,reorder REAL);
 CREATE TABLE IF NOT EXISTS bom(product_id INTEGER,material_id INTEGER,qty REAL,unit TEXT,PRIMARY KEY(product_id,material_id));
 CREATE TABLE IF NOT EXISTS stock_ledger(id INTEGER PRIMARY KEY,item_type TEXT,item_id INTEGER,qty REAL,unit TEXT,movement TEXT,source TEXT,note TEXT,created_at TEXT);
 CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY,customer_id INTEGER,salesman TEXT,status TEXT,total_packets INTEGER,created_at TEXT,note TEXT);
 CREATE TABLE IF NOT EXISTS order_lines(id INTEGER PRIMARY KEY,order_id INTEGER,product_id INTEGER,qty INTEGER,unit_paise INTEGER);
 CREATE TABLE IF NOT EXISTS invoices(id INTEGER PRIMARY KEY,order_id INTEGER,invoice_no TEXT UNIQUE,taxable_paise INTEGER,cgst_paise INTEGER,sgst_paise INTEGER,igst_paise INTEGER,total_paise INTEGER,status TEXT,created_at TEXT);
 CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY,invoice_id INTEGER,amount_paise INTEGER,received_at TEXT,note TEXT);
 CREATE TABLE IF NOT EXISTS production_runs(id INTEGER PRIMARY KEY,product_id INTEGER,batch_count REAL,expected_packets INTEGER,actual_packets INTEGER,damaged_pouches INTEGER,cartons_used INTEGER,labour_paise INTEGER,utilities_paise INTEGER,created_at TEXT,notes TEXT);
 CREATE TABLE IF NOT EXISTS run_materials(run_id INTEGER,material_id INTEGER,planned REAL,actual REAL,unit TEXT,rate_paise INTEGER);
 CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY,actor TEXT,action TEXT,details TEXT,created_at TEXT);
 CREATE TABLE IF NOT EXISTS material_receipts(id INTEGER PRIMARY KEY,material_id INTEGER,qty REAL,rate_paise INTEGER,source TEXT,created_at TEXT);
 CREATE TABLE IF NOT EXISTS order_sync_keys(client_key TEXT PRIMARY KEY,order_id INTEGER);
 ''')
 if not c.execute('SELECT 1 FROM users LIMIT 1').fetchone():
  users=[('admin','admin123','admin'),('salesa','sales123','salesman'),('salesb','sales123','salesman'),('production','prod123','production'),('auditor','audit123','auditor'),('owner','owner123','owner')]
  c.executemany('INSERT INTO users(username,password,role) VALUES(?,?,?)',[(u,generate_password_hash(p),r) for u,p,r in users])
  c.executemany('INSERT INTO customers(name,kind,state,gstin) VALUES(?,?,?,?)',[('Retailer A','Retailer','Tamil Nadu','33ABCDE1234F1Z5'),('Distributor B','Distributor','Karnataka','29ABCDE1234F1Z5')])
  c.execute('INSERT INTO products(name,pack_g,selling_paise,gst_rate,hsn) VALUES(?,?,?,?,?)',('Murukku 200 g',200,5000,5,'210690'))
  mats=[('Flour','kg',4200,'Raw',25),('Cooking oil','litre',14000,'Raw',10),('Salt and spice mix','kg',20000,'Raw',2),('200 g pouch','piece',250,'Packaging',100),('Carton','piece',1500,'Packaging',5)]
  c.executemany('INSERT INTO materials(name,unit,rate_paise,category,reorder) VALUES(?,?,?,?,?)',mats)
  for i,q,u,rate in [(1,100,'kg',4200),(2,30,'litre',14000),(3,5,'kg',20000),(4,500,'piece',250),(5,30,'piece',1500)]:
   c.execute("INSERT INTO stock_ledger(item_type,item_id,qty,unit,movement,source,note,created_at) VALUES('material',?,?,?,?,?,?,?)",(i,q,u,'IN','OPENING','Seed data',datetime.now().isoformat()))
   c.execute('INSERT INTO material_receipts(material_id,qty,rate_paise,source,created_at) VALUES(?,?,?,?,?)',(i,q,rate,'Opening stock',datetime.now().isoformat()))
  c.execute("INSERT INTO stock_ledger(item_type,item_id,qty,unit,movement,source,note,created_at) VALUES('product',1,50,'packet','IN','OPENING','Opening finished goods',?)",(datetime.now().isoformat(),))
  c.executemany('INSERT INTO bom(product_id,material_id,qty,unit) VALUES(1,?,?,?)',[(1,40,'kg'),(2,10,'litre'),(3,1.2,'kg'),(4,200,'piece'),(5,10,'piece')])
 else:
  # Upgrade legacy plaintext demo passwords to salted hashes on first login (login supports both).
  if not c.execute('SELECT 1 FROM material_receipts LIMIT 1').fetchone():
   opening={'Flour':(100,4200),'Cooking oil':(30,14000),'Salt and spice mix':(5,20000),'200 g pouch':(500,250),'Carton':(30,1500)}
   for m in c.execute('SELECT * FROM materials').fetchall():
    if m['name'] in opening:
     q,rate=opening[m['name']]; c.execute('INSERT INTO material_receipts(material_id,qty,rate_paise,source,created_at) VALUES(?,?,?,?,?)',(m['id'],q,rate,'Opening stock (legacy migration)',datetime.now().isoformat()))
 c.commit(); c.close()

def log(actor,action,details):
 c=db(); c.execute('INSERT INTO audit_log(actor,action,details,created_at) VALUES(?,?,?,?)',(actor,action,details,datetime.now().isoformat())); c.commit(); c.close()
def login_required(fn):
 @wraps(fn)
 def w(*a,**k):
  if 'user' not in session:
   if request.path.startswith('/api/'): return jsonify(error='Login required'),401
   return redirect(url_for('login'))
  return fn(*a,**k)
 return w
def roles(*allowed):
 def deco(fn):
  @wraps(fn)
  @login_required
  def w(*a,**k):
   if session.get('role') not in allowed: return jsonify(error='Your role is not allowed to perform this action'),403
   return fn(*a,**k)
  return w
 return deco
def balance(c,typ,item_id):
 r=c.execute("SELECT COALESCE(SUM(CASE WHEN movement='IN' THEN qty ELSE -qty END),0) q FROM stock_ledger WHERE item_type=? AND item_id=?",(typ,item_id)).fetchone(); return float(r['q'])
def add_move(c,typ,item_id,qty,unit,movement,source,note):
 c.execute('INSERT INTO stock_ledger(item_type,item_id,qty,unit,movement,source,note,created_at) VALUES(?,?,?,?,?,?,?,?)',(typ,item_id,qty,unit,movement,source,note,datetime.now().isoformat()))
def weighted_rate(c,mid):
 r=c.execute('SELECT COALESCE(SUM(qty*rate_paise),0) cost,COALESCE(SUM(qty),0) qty FROM material_receipts WHERE material_id=?',(mid,)).fetchone()
 return int((Decimal(str(r['cost']))/Decimal(str(r['qty']))).quantize(Decimal('1'),rounding=ROUND_HALF_UP)) if r['qty'] else c.execute('SELECT rate_paise FROM materials WHERE id=?',(mid,)).fetchone()['rate_paise']

@app.route('/')
@login_required
def home(): return render_template('index.html',user=session['user'],role=session['role'])
@app.route('/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  c=db(); u=c.execute('SELECT * FROM users WHERE username=?',(request.form.get('username',''),)).fetchone(); c.close(); pw=request.form.get('password','')
  valid=False
  if u:
   try: valid=check_password_hash(u['password'],pw)
   except Exception: valid=(u['password']==pw)
  if valid:
   # Upgrade old plaintext passwords; regenerate session to prevent fixation.
   if not u['password'].startswith('pbkdf2:') and not u['password'].startswith('scrypt:'):
    c=db(); c.execute('UPDATE users SET password=? WHERE id=?',(generate_password_hash(pw),u['id'])); c.commit(); c.close()
   session.clear(); session['user']=u['username']; session['role']=u['role']; session['csrf']=secrets.token_urlsafe(24); return redirect('/')
  return render_template('login.html',error='Invalid username or password')
 return render_template('login.html')
@app.route('/logout')
def logout(): session.clear(); return redirect('/login')

@app.route('/api/summary')
@roles('admin','owner','auditor','salesman','production')
def summary():
 c=db(); 
 if session.get('role')=='production':
  sales=0; due=0
 elif session.get('role')=='salesman':
  sales=c.execute("SELECT COALESCE(SUM(i.total_paise),0) v FROM invoices i JOIN orders o ON o.id=i.order_id WHERE i.status='POSTED' AND o.salesman=?",(session['user'],)).fetchone()['v']; due=c.execute("SELECT COALESCE(SUM(i.total_paise),0)-COALESCE((SELECT SUM(p.amount_paise) FROM payments p WHERE p.invoice_id=i.id),0) due FROM invoices i JOIN orders o ON o.id=i.order_id WHERE i.status='POSTED' AND o.salesman=?",(session['user'],)).fetchone()['due']
 else:
  sales=c.execute("SELECT COALESCE(SUM(total_paise),0) v FROM invoices WHERE status='POSTED'").fetchone()['v']; due=c.execute("SELECT COALESCE(SUM(i.total_paise),0)-COALESCE((SELECT SUM(p.amount_paise) FROM payments p WHERE p.invoice_id=i.id),0) due FROM invoices i WHERE i.status='POSTED'").fetchone()['due']
 prod=c.execute('SELECT COUNT(*) n,COALESCE(SUM(actual_packets),0) packets FROM production_runs').fetchone(); finished=[{'name':p['name'],'qty':balance(c,'product',p['id'])} for p in c.execute('SELECT * FROM products')]; low=[]
 for m in c.execute('SELECT * FROM materials'):
  q=balance(c,'material',m['id'])
  if q<=m['reorder']: low.append({'name':m['name'],'qty':q,'unit':m['unit']})
 c.close(); return jsonify(sales=rupees(sales),outstanding=rupees(due),runs=prod['n'],produced=prod['packets'],finished=finished,low_stock=low)
@app.route('/api/masters')
@roles('admin','owner','salesman','production','auditor')
def masters():
 c=db(); customers=[] if session.get('role')=='production' else [dict(x) for x in c.execute('SELECT * FROM customers')]; products=[dict(x) for x in c.execute('SELECT * FROM products')]; materials=[]
 for x in c.execute('SELECT * FROM materials'):
  d=dict(x); d['balance']=balance(c,'material',x['id']); materials.append(d)
 c.close(); return jsonify(customers=customers,products=products,materials=materials)
@app.route('/api/orders',methods=['GET','POST'])
@roles('admin','owner','salesman','auditor')
def orders():
 if request.method=='POST' and session.get('role') not in ('admin','salesman'): return jsonify(error='Only salesmen or admins can create orders'),403
 c=db()
 if request.method=='POST':
  data=request.get_json(silent=True) or {}; lines=data.get('lines',[])
  if not lines: c.close(); return jsonify(error='Add at least one product'),400
  try: cust=int(data['customer_id']); total=sum(int(x['qty']) for x in lines)
  except Exception: c.close(); return jsonify(error='Invalid order data'),400
  if total<1 or total>100000: c.close(); return jsonify(error='Quantity must be between 1 and 100000'),400
  if session['role']=='salesman' and data.get('salesman') not in (None,session['user']): c.close(); return jsonify(error='Cannot submit for another salesman'),403
  key=data.get('client_key')
  if key:
   old=c.execute('SELECT order_id FROM order_sync_keys WHERE client_key=?',(key,)).fetchone()
   if old: c.close(); return jsonify(ok=True,id=old['order_id'],duplicate=True)
  if not c.execute('SELECT 1 FROM customers WHERE id=?',(cust,)).fetchone(): c.close(); return jsonify(error='Customer not found'),404
  cur=c.execute('INSERT INTO orders(customer_id,salesman,status,total_packets,created_at,note) VALUES(?,?,?,?,?,?)',(cust,session['user'],'SUBMITTED',total,datetime.now().isoformat(),str(data.get('note',''))[:500])); oid=cur.lastrowid
  for x in lines:
   p=c.execute('SELECT selling_paise FROM products WHERE id=?',(int(x['product_id']),)).fetchone(); q=int(x['qty'])
   if not p or q<1: c.rollback(); c.close(); return jsonify(error='Invalid product or quantity'),400
   c.execute('INSERT INTO order_lines(order_id,product_id,qty,unit_paise) VALUES(?,?,?,?)',(oid,int(x['product_id']),q,p['selling_paise']))
  if key: c.execute('INSERT OR IGNORE INTO order_sync_keys(client_key,order_id) VALUES(?,?)',(key,oid))
  c.commit(); c.close(); log(session['user'],'ORDER_CREATED',f'Order #{oid}'); return jsonify(ok=True,id=oid)
 query='SELECT o.*,cu.name customer,cu.state,cu.gstin FROM orders o JOIN customers cu ON cu.id=o.customer_id'
 params=()
 if session['role']=='salesman': query+=' WHERE o.salesman=?'; params=(session['user'],)
 rows=c.execute(query+' ORDER BY o.id DESC',params).fetchall(); result=[]
 for o in rows:
  d=dict(o); d['lines']=[dict(x) for x in c.execute('SELECT ol.*,p.name product FROM order_lines ol JOIN products p ON p.id=ol.product_id WHERE order_id=?',(o['id'],))]; d['stock_available']=balance(c,'product',1); result.append(d)
 c.close(); return jsonify(result)
@app.route('/api/orders/<int:oid>/approve',methods=['POST'])
@roles('admin')
def approve(oid):
 c=db(); o=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
 if not o: c.close(); return jsonify(error='Order not found'),404
 if o['status']!='SUBMITTED': c.close(); return jsonify(error='Only submitted orders can be approved'),409
 lines=c.execute('SELECT * FROM order_lines WHERE order_id=?',(oid,)).fetchall(); shortages=[]
 for x in lines:
  avail=balance(c,'product',x['product_id'])
  if avail<x['qty']: shortages.append({'requested':x['qty'],'available':avail,'shortage':x['qty']-avail})
 if shortages: c.close(); return jsonify(error='Insufficient finished-goods stock',shortages=shortages),409
 customer=c.execute('SELECT * FROM customers WHERE id=?',(o['customer_id'],)).fetchone(); taxable=sum(x['qty']*x['unit_paise'] for x in lines); tax=money(Decimal(taxable)/100*Decimal('0.05')); intra=customer['state']=='Tamil Nadu'; cg=tax//2 if intra else 0; sg=tax-cg if intra else 0; ig=0 if intra else tax; total=taxable+tax
 fy_start=date.today().year if date.today().month>=4 else date.today().year-1; fy=f'{fy_start}-{str(fy_start+1)[-2:]}'; invno=f'SF/{fy}/{oid:04d}'
 c.execute('INSERT INTO invoices(order_id,invoice_no,taxable_paise,cgst_paise,sgst_paise,igst_paise,total_paise,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(oid,invno,taxable,cg,sg,ig,total,'POSTED',datetime.now().isoformat())); c.execute("UPDATE orders SET status='INVOICED' WHERE id=?",(oid,)); c.commit(); c.close(); log(session['user'],'INVOICE_POSTED',invno)
 return jsonify(ok=True,invoice=invno,taxable=rupees(taxable),cgst=rupees(cg),sgst=rupees(sg),igst=rupees(ig),total=rupees(total))
@app.route('/api/orders/<int:oid>/dispatch',methods=['POST'])
@roles('admin')
def dispatch(oid):
 c=db(); o=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
 if not o: c.close(); return jsonify(error='Order not found'),404
 if o['status']!='INVOICED': c.close(); return jsonify(error='Invoice the order before dispatch'),400
 lines=c.execute('SELECT * FROM order_lines WHERE order_id=?',(oid,)).fetchall()
 for x in lines:
  if balance(c,'product',x['product_id'])<x['qty']: c.close(); return jsonify(error='Stock changed; insufficient stock'),409
 for x in lines: add_move(c,'product',x['product_id'],x['qty'],'packet','OUT',f'Order #{oid}','Dispatch')
 c.execute("UPDATE orders SET status='DISPATCHED' WHERE id=?",(oid,)); c.commit(); c.close(); log(session['user'],'DISPATCH',f'Order #{oid}'); return jsonify(ok=True)
@app.route('/api/purchase',methods=['POST'])
@roles('admin','production')
def purchase():
 data=request.get_json(silent=True) or {}; c=db(); m=c.execute('SELECT * FROM materials WHERE id=?',(int(data.get('material_id',0)),)).fetchone()
 if not m: c.close(); return jsonify(error='Material not found'),404
 try: qty=Decimal(str(data['qty'])); rate=money(data['rate'])
 except Exception: c.close(); return jsonify(error='Invalid quantity or rate'),400
 if qty<=0 or rate<0: c.close(); return jsonify(error='Quantity must be positive and rate cannot be negative'),400
 c.execute('INSERT INTO material_receipts(material_id,qty,rate_paise,source,created_at) VALUES(?,?,?,?,?)',(m['id'],float(qty),rate,'Purchase '+str(data.get('reference','')),datetime.now().isoformat()))
 add_move(c,'material',m['id'],float(qty),m['unit'],'IN','Purchase '+str(data.get('reference','')),f'Purchase at ₹{data["rate"]}/unit')
 avg=weighted_rate(c,m['id']); c.execute('UPDATE materials SET rate_paise=? WHERE id=?',(avg,m['id'])); c.commit(); c.close(); log(session['user'],'PURCHASE',f'{qty} {m["unit"]} {m["name"]} at ₹{data["rate"]}'); return jsonify(ok=True,weighted_average_rate=rupees(avg))
@app.route('/api/production',methods=['POST'])
@roles('admin','production')
def production():
 data=request.get_json(silent=True) or {}; c=db(); product=c.execute('SELECT * FROM products WHERE id=?',(int(data.get('product_id',1)),)).fetchone()
 if not product: c.close(); return jsonify(error='Product not found'),404
 try: batch=Decimal(str(data.get('batches',1))); actual=int(data['actual_packets']); damaged=int(data.get('damaged_pouches',0)); cartons=int(data.get('cartons_used',10))
 except Exception: c.close(); return jsonify(error='Invalid production values'),400
 if batch<=0 or actual<0 or damaged<0 or cartons<0: c.close(); return jsonify(error='Production quantities must be non-negative and batch count positive'),400
 bom=c.execute('SELECT b.*,m.name,m.rate_paise,m.unit material_unit FROM bom b JOIN materials m ON m.id=b.material_id WHERE b.product_id=?',(product['id'],)).fetchall(); expected=int((Decimal('200')*batch).quantize(Decimal('1'),rounding=ROUND_HALF_UP)); actuals=data.get('actuals',{})
 # Validate all balances before writing any stock or run rows.
 uses=[]
 for b in bom:
  planned=Decimal(str(b['qty']))*batch; default=actual if b['name']=='200 g pouch' else (cartons if b['name']=='Carton' else planned)
  used=Decimal(str(actuals.get(str(b['material_id']),default)))
  if used<0: c.close(); return jsonify(error='Material usage cannot be negative'),400
  if Decimal(str(balance(c,'material',b['material_id'])))<used: c.close(); return jsonify(error=f'Insufficient {b["name"]} stock'),409
  uses.append((b,planned,used,weighted_rate(c,b['material_id'])))
 pouch=next((b for b in bom if b['name']=='200 g pouch'),None)
 if pouch and Decimal(str(balance(c,'material',pouch['material_id'])))<Decimal(str(dict((b['material_id'],u) for b,p,u,r in uses).get(pouch['material_id'],0)))+damaged: c.close(); return jsonify(error='Insufficient pouches for good output and damage'),409
 labour=money(data.get('labour',0)); utilities=money(data.get('utilities',0)); run=c.execute('INSERT INTO production_runs(product_id,batch_count,expected_packets,actual_packets,damaged_pouches,cartons_used,labour_paise,utilities_paise,created_at,notes) VALUES(?,?,?,?,?,?,?,?,?,?)',(product['id'],float(batch),expected,actual,damaged,cartons,labour,utilities,datetime.now().isoformat(),str(data.get('notes','')))).lastrowid
 raw_cost=0; variances=[]; cost_lines=[]
 for b,planned,used,rate in uses:
  # Cost only consumed quantity. Damaged pouches are accounted separately below.
  add_move(c,'material',b['material_id'],float(used),b['unit'],'OUT',f'Production run #{run}',f'Actual consumption; planned {planned}')
  c.execute('INSERT INTO run_materials(run_id,material_id,planned,actual,unit,rate_paise) VALUES(?,?,?,?,?,?)',(run,b['material_id'],float(planned),float(used),b['unit'],rate))
  raw_cost+=money(used*Decimal(rate)/100); cost_lines.append({'material':b['name'],'qty':float(used),'unit':b['unit'],'rate':rupees(rate),'cost':rupees(money(used*Decimal(rate)/100))})
  pct=float((used-planned)/planned*100) if planned else 0
  if abs(pct)>3: variances.append({'material':b['name'],'planned':float(planned),'actual':float(used),'variance_pct':round(pct,2)})
 if damaged and pouch:
  pouch_rate=weighted_rate(c,pouch['material_id']); add_move(c,'material',pouch['material_id'],damaged,'piece','OUT',f'Production run #{run}','Damaged pouches'); c.execute('INSERT INTO run_materials(run_id,material_id,planned,actual,unit,rate_paise) VALUES(?,?,?,?,?,?)',(run,pouch['material_id'],0,damaged,'piece',pouch_rate))
 add_move(c,'product',product['id'],actual,'packet','IN',f'Production run #{run}','Good finished packets')
 damage_cost=money(Decimal(damaged)*Decimal(weighted_rate(c,pouch['material_id']))/100) if pouch else 0
 total_cost=raw_cost+damage_cost+labour+utilities; per_packet=Decimal(total_cost)/Decimal(actual)/100 if actual else Decimal(0)
 c.commit(); yield_pct=float((Decimal(actual)-Decimal(expected))/Decimal(expected)*100) if expected else 0
 if abs(yield_pct)>3: variances.append({'material':'Finished yield','planned':expected,'actual':actual,'variance_pct':round(yield_pct,2)})
 c.close(); log(session['user'],'PRODUCTION_RUN',f'Run #{run}: {actual}/{expected} packets; total cost ₹{rupees(total_cost):.2f}')
 return jsonify(ok=True,run_id=run,expected=expected,actual=actual,yield_variance=round(yield_pct,2),variances=variances,raw_cost=rupees(raw_cost+damage_cost),labour=rupees(labour),utilities=rupees(utilities),total_run_cost=rupees(total_cost),cost_per_packet=round(float(per_packet),2),cost_lines=cost_lines)
@app.route('/api/stock')
@roles('admin','owner','production','auditor')
def stock():
 c=db(); mats=[]
 for m in c.execute('SELECT * FROM materials'): mats.append({'id':m['id'],'name':m['name'],'category':m['category'],'unit':m['unit'],'balance':balance(c,'material',m['id']),'reorder':m['reorder']})
 goods=[{'id':p['id'],'name':p['name'],'balance':balance(c,'product',p['id'])} for p in c.execute('SELECT * FROM products')]; ledger=[dict(x) for x in c.execute('SELECT * FROM stock_ledger ORDER BY id DESC LIMIT 500')]; c.close(); return jsonify(materials=mats,finished=goods,ledger=ledger)
@app.route('/api/reports')
@roles('admin','owner','auditor')
def reports():
 c=db(); invoices=[dict(x) for x in c.execute('SELECT i.*,cu.name customer,cu.state FROM invoices i JOIN orders o ON o.id=i.order_id JOIN customers cu ON cu.id=o.customer_id ORDER BY i.id DESC')]; runs=[dict(x) for x in c.execute('SELECT * FROM production_runs ORDER BY id DESC')]; payments=[dict(x) for x in c.execute('SELECT p.*,i.invoice_no FROM payments p JOIN invoices i ON i.id=p.invoice_id')]; c.close()
 for i in invoices: i['taxable']=rupees(i['taxable_paise']); i['total']=rupees(i['total_paise'])
 return jsonify(invoices=invoices,runs=runs,payments=payments)
@app.route('/api/payment',methods=['POST'])
@roles('admin')
def payment():
 data=request.get_json(silent=True) or {}; c=db(); inv=c.execute('SELECT * FROM invoices WHERE id=? AND status="POSTED"',(int(data.get('invoice_id',0)),)).fetchone()
 if not inv: c.close(); return jsonify(error='Posted invoice not found'),404
 try: amt=money(data['amount'])
 except Exception: c.close(); return jsonify(error='Invalid payment amount'),400
 paid=c.execute('SELECT COALESCE(SUM(amount_paise),0) p FROM payments WHERE invoice_id=?',(inv['id'],)).fetchone()['p']; due=inv['total_paise']-paid
 if amt<=0 or amt>due: c.close(); return jsonify(error=f'Payment must be positive and not exceed outstanding ₹{rupees(due):.2f}'),400
 c.execute('INSERT INTO payments(invoice_id,amount_paise,received_at,note) VALUES(?,?,?,?)',(inv['id'],amt,datetime.now().isoformat(),str(data.get('note','')))); c.commit(); c.close(); log(session['user'],'PAYMENT',f'{rupees(amt)} received for {inv["invoice_no"]}'); return jsonify(ok=True)
@app.route('/api/invoices')
@roles('admin','owner','auditor')
def invoices():
 c=db(); rows=c.execute('SELECT i.*,cu.name customer FROM invoices i JOIN orders o ON o.id=i.order_id JOIN customers cu ON cu.id=o.customer_id ORDER BY i.id DESC').fetchall(); out=[]
 for r in rows:
  paid=c.execute('SELECT COALESCE(SUM(amount_paise),0) p FROM payments WHERE invoice_id=?',(r['id'],)).fetchone()['p']; d=dict(r); d.update(paid=rupees(paid),due=rupees(r['total_paise']-paid),total=rupees(r['total_paise'])); out.append(d)
 c.close(); return jsonify(out)
@app.route('/invoice/<int:iid>.pdf')
@roles('admin','owner','auditor')
def invoice_pdf(iid):
 c=db(); row=c.execute('SELECT i.*,o.customer_id,cu.name customer,cu.state,cu.gstin FROM invoices i JOIN orders o ON o.id=i.order_id JOIN customers cu ON cu.id=o.customer_id WHERE i.id=?',(iid,)).fetchone()
 if not row: c.close(); return 'Invoice not found',404
 lines=c.execute('SELECT ol.*,p.name,p.hsn,p.pack_g FROM order_lines ol JOIN products p ON p.id=ol.product_id WHERE ol.order_id=?',(row['order_id'],)).fetchall(); c.close()
 buf=io.BytesIO(); p=canvas.Canvas(buf,pagesize=A4); W,H=A4; y=H-22*mm
 p.setFont('Helvetica-Bold',18); p.drawString(20*mm,y,'SMARTFACTORY FOODS'); y-=9*mm; p.setFont('Helvetica',9); p.drawString(20*mm,y,'Tamil Nadu, India · GSTIN: 33ABCDE1234F1Z5'); y-=14*mm
 p.setFont('Helvetica-Bold',15); p.drawString(20*mm,y,'TAX INVOICE'); p.setFont('Helvetica',10); p.drawRightString(W-20*mm,y,'Invoice: '+row['invoice_no']); y-=10*mm
 p.drawString(20*mm,y,'Bill To: '+row['customer']); y-=6*mm; p.drawString(20*mm,y,'Place of supply: '+row['state']); y-=6*mm; p.drawString(20*mm,y,'Customer GSTIN: '+(row['gstin'] or 'Unregistered')); y-=12*mm
 p.setFont('Helvetica-Bold',9); p.drawString(20*mm,y,'Description'); p.drawString(95*mm,y,'HSN'); p.drawRightString(130*mm,y,'Qty'); p.drawRightString(160*mm,y,'Rate'); p.drawRightString(W-20*mm,y,'Taxable'); y-=5*mm; p.line(20*mm,y,W-20*mm,y); y-=8*mm; p.setFont('Helvetica',9)
 for x in lines:
  p.drawString(20*mm,y,x['name']); p.drawString(95*mm,y,x['hsn']); p.drawRightString(130*mm,y,str(x['qty'])); p.drawRightString(160*mm,y,f'{rupees(x["unit_paise"]):.2f}'); p.drawRightString(W-20*mm,y,f'{rupees(x["qty"]*x["unit_paise"]):.2f}'); y-=8*mm
 y-=5*mm; p.line(110*mm,y,W-20*mm,y); y-=9*mm
 for label,val in [('Taxable value',row['taxable_paise']),('CGST',row['cgst_paise']),('SGST',row['sgst_paise']),('IGST',row['igst_paise']),('Invoice total',row['total_paise'])]:
  p.setFont('Helvetica-Bold' if label=='Invoice total' else 'Helvetica',10); p.drawString(115*mm,y,label); p.drawRightString(W-20*mm,y,f'INR {rupees(val):,.2f}'); y-=7*mm
 p.setFont('Helvetica',8); p.drawString(20*mm,25*mm,'Computer-generated prototype invoice. Verify statutory details before real-world use.'); p.save(); buf.seek(0); return send_file(buf,mimetype='application/pdf',as_attachment=True,download_name=f'{row["invoice_no"].replace("/","-")}.pdf')
@app.route('/api/costing')
@roles('admin','owner','auditor','production')
def costing():
 c=db(); rows=[]
 for r in c.execute('SELECT * FROM production_runs ORDER BY id DESC'):
  mats=c.execute('SELECT rm.*,m.name FROM run_materials rm JOIN materials m ON m.id=rm.material_id WHERE rm.run_id=?',(r['id'],)).fetchall(); material_cost=sum(money(Decimal(str(x['actual']))*Decimal(x['rate_paise'])/100) for x in mats); total=material_cost+r['labour_paise']+r['utilities_paise']; rows.append({'run_id':r['id'],'product_id':r['product_id'],'actual_packets':r['actual_packets'],'material_cost':rupees(material_cost),'labour':rupees(r['labour_paise']),'utilities':rupees(r['utilities_paise']),'total_cost':rupees(total),'cost_per_packet':round(total/r['actual_packets']/100,2) if r['actual_packets'] else 0,'valuation':'Weighted-average purchase cost; labour and utilities allocated to this run'})
 c.close(); return jsonify(runs=rows)
@app.route('/api/export/<kind>')
@roles('admin','owner','auditor')
def export(kind):
 c=db(); output=io.StringIO(); w=csv.writer(output)
 if kind=='sales':
  w.writerow(['Invoice','Customer','Taxable ₹','CGST ₹','SGST ₹','IGST ₹','Total ₹','Status'])
  for x in c.execute('SELECT i.*,cu.name customer FROM invoices i JOIN orders o ON o.id=i.order_id JOIN customers cu ON cu.id=o.customer_id'): w.writerow([x['invoice_no'],x['customer'],rupees(x['taxable_paise']),rupees(x['cgst_paise']),rupees(x['sgst_paise']),rupees(x['igst_paise']),rupees(x['total_paise']),x['status']])
 elif kind=='stock':
  w.writerow(['Item type','Item ID','Quantity','Unit','Movement','Source','Note','Created'])
  for x in c.execute('SELECT * FROM stock_ledger ORDER BY id'): w.writerow([x['item_type'],x['item_id'],x['qty'],x['unit'],x['movement'],x['source'],x['note'],x['created_at']])
 elif kind=='production':
  w.writerow(['Run','Expected packets','Actual packets','Yield variance %','Labour ₹','Utilities ₹','Date'])
  for x in c.execute('SELECT * FROM production_runs ORDER BY id'): w.writerow([x['id'],x['expected_packets'],x['actual_packets'],round((x['actual_packets']-x['expected_packets'])/x['expected_packets']*100,2) if x['expected_packets'] else 0,rupees(x['labour_paise']),rupees(x['utilities_paise']),x['created_at']])
 elif kind=='collections':
  w.writerow(['Invoice','Customer','Invoice total ₹','Paid ₹','Outstanding ₹'])
  for x in c.execute('SELECT i.*,cu.name customer FROM invoices i JOIN orders o ON o.id=i.order_id JOIN customers cu ON cu.id=o.customer_id'):
   paid=c.execute('SELECT COALESCE(SUM(amount_paise),0) p FROM payments WHERE invoice_id=?',(x['id'],)).fetchone()['p']; w.writerow([x['invoice_no'],x['customer'],rupees(x['total_paise']),rupees(paid),rupees(x['total_paise']-paid)])
 else: c.close(); return jsonify(error='Unknown export type'),404
 c.close(); resp=make_response(output.getvalue()); resp.headers['Content-Type']='text/csv; charset=utf-8'; resp.headers['Content-Disposition']=f'attachment; filename={kind}_report.csv'; return resp
@app.route('/api/ai')
@roles('admin','owner','auditor','production')
def ai():
 c=db(); insights=[]
 for m in c.execute('SELECT * FROM materials'):
  q=balance(c,'material',m['id'])
  if q<=m['reorder']: insights.append({'level':'warning','title':f'Reorder {m["name"]}','body':f'Available balance is {q:g} {m["unit"]}, at or below reorder threshold {m["reorder"]:g}.','action':'Create a purchase order and review the production plan.'})
 for r in c.execute('SELECT * FROM production_runs ORDER BY id DESC LIMIT 5'):
  v=(r['actual_packets']-r['expected_packets'])/r['expected_packets']*100 if r['expected_packets'] else 0
  if abs(v)>3: insights.append({'level':'danger','title':f'Yield variance on run #{r["id"]}','body':f'Actual yield {r["actual_packets"]} vs expected {r["expected_packets"]} ({v:.1f}%).','action':'Review batch weighing, frying loss and packing rejects.'})
 for r in c.execute('SELECT rm.*,m.name FROM run_materials rm JOIN materials m ON m.id=rm.material_id ORDER BY rm.rowid DESC LIMIT 12'):
  v=(r['actual']-r['planned'])/r['planned']*100 if r['planned'] else 0
  if abs(v)>3: insights.append({'level':'warning','title':f'{r["name"]} consumption variance','body':f'Actual {r["actual"]:g} {r["unit"]} vs planned {r["planned"]:g} ({v:+.1f}%).','action':'Check weighing records before changing the recipe.'})
 if not insights: insights=[{'level':'success','title':'Operations look stable','body':'No reorder or production variance alerts in latest records.','action':'Continue daily monitoring.'}]
 c.close(); return jsonify(mode='Explainable rules + live ledger analysis',disclaimer='Decision support only; not a statutory accounting or food-safety opinion.',insights=insights)
@app.route('/api/audit-log')
@roles('admin','auditor','owner')
def audit_log():
 c=db(); rows=[dict(x) for x in c.execute('SELECT * FROM audit_log ORDER BY id DESC LIMIT 100')]; c.close(); return jsonify(rows)
@app.route('/manifest.webmanifest')
def manifest(): return app.send_static_file('manifest.webmanifest')
@app.route('/service-worker.js')
def service_worker(): return send_file(os.path.join(BASE,'static','service-worker.js'),mimetype='application/javascript')
if __name__=='__main__':
 init_db(); app.run(debug=os.environ.get('FLASK_DEBUG')=='1',host='127.0.0.1',port=5000)
