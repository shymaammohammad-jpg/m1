import urllib.request,urllib.parse,http.cookiejar as cookiejar,re,secrets,subprocess,json,csv,io,zipfile,os,shutil
from pathlib import Path
base=os.environ.get('MAQAD_TEST_URL','http://127.0.0.1:8095/').rstrip('/')+'/'
if urllib.parse.urlsplit(base).hostname not in ('localhost','127.0.0.1','::1'):raise RuntimeError('Use an isolated loopback test instance.')
DB_NAME=os.environ.get('MAQAD_TEST_DATABASE','')
if not DB_NAME.endswith('_test'):raise RuntimeError('Set MAQAD_TEST_DATABASE to an empty database ending in _test.')
MYSQL_BIN=os.environ.get('MAQAD_MYSQL_BIN','mysql')
PHP_BIN=os.environ.get('MAQAD_PHP_BIN','php')
MYSQL_COMMAND=[MYSQL_BIN,'--no-defaults','--default-character-set=utf8mb4','--host='+os.environ.get('MAQAD_TEST_MYSQL_HOST','127.0.0.1'),'--port='+os.environ.get('MAQAD_TEST_MYSQL_PORT','3306'),'--user='+os.environ.get('MAQAD_TEST_MYSQL_USER','root'),'--batch','--skip-column-names',DB_NAME]
if os.environ.get('MAQAD_TEST_MYSQL_SOCKET'):MYSQL_COMMAND.insert(-1,'--socket='+os.environ['MAQAD_TEST_MYSQL_SOCKET'])
PROJECT_ROOT=Path(__file__).resolve().parent.parent
CHILD_ENV=dict(os.environ,MAQAD_PROJECT_ROOT=str(PROJECT_ROOT))
def client():return urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(cookiejar.CookieJar()))
http=client();count=0
password=secrets.token_urlsafe(20)
def get(path='',op=None,raw=False):
 with (op or http).open(base+path) as r:
  b=r.read();return b if raw else b.decode('utf-8-sig')
def post(data,path='',op=None):
 op=op or http;t=re.search(r'name="csrf" value="([^"]+)"',get(path,op))[1]
 pairs=[('csrf',t)]
 for k,v in data.items():
  if isinstance(v,list):pairs.extend((k,str(x)) for x in v)
  else:pairs.append((k,str(v)))
 with op.open(base+path,urllib.parse.urlencode(pairs).encode()) as r:return r.read().decode('utf-8-sig')
def upload(action,field,filename,blob,path='',extra=None,op=None):
 op=op or http;t=re.search(r'name="csrf" value="([^"]+)"',get(path,op))[1];boundary='----Maqad'+secrets.token_hex(12);parts=[]
 for k,v in {'csrf':t,'action':action,**(extra or {})}.items():parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
 parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()+blob+b'\r\n');parts.append(f'--{boundary}--\r\n'.encode())
 req=urllib.request.Request(base+path,data=b''.join(parts),headers={'Content-Type':'multipart/form-data; boundary='+boundary})
 return op.open(req).read().decode('utf-8-sig')
def sql(q):return subprocess.check_output(MYSQL_COMMAND+['-e',q],text=True,encoding='utf-8').strip()

def check(ok,message):
 global count
 count+=1
 if not ok:raise AssertionError(message)
def eid(table,name):return sql(f"SELECT id FROM {table} WHERE name='{name}' AND institution_id=1")
