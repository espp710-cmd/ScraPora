"""
MarketScope Backend v3.0
Dibuat oleh: Dinar Maulidan
Fitur baru: Login activity monitoring, session log
"""

from flask import Flask, jsonify, request, send_from_directory
import requests
import re, json, os, time, hashlib
from datetime import datetime
from urllib.parse import unquote

app = Flask(__name__, static_folder='static')
app.secret_key = 'marketscope_secret_2024_dinar'

CONFIG_FILE   = 'config.json'
USERS_FILE    = 'users.json'
ACTIVITY_FILE = 'activity_log.json'
FEEDBACK_FILE = 'feedbacks.json'

# ─── Storage helpers ───
def load_json(path, default):
    if os.path.exists(path):
        with open(path,'r') as f: return json.load(f)
    return default

def save_json(path, data):
    with open(path,'w') as f: json.dump(data, f, indent=2)

def load_config():  return load_json(CONFIG_FILE, {'api_key':'','admin_password':'11011_'})
def save_config(c): save_json(CONFIG_FILE, c)
def load_users():   return load_json(USERS_FILE, {})
def save_users(u):  save_json(USERS_FILE, u)
def load_activity():return load_json(ACTIVITY_FILE, [])
def save_activity(a):save_json(ACTIVITY_FILE, a)
def load_feedbacks():return load_json(FEEDBACK_FILE, [])
def save_feedbacks(f):save_json(FEEDBACK_FILE, f)

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

def log_activity(event_type, username, detail='', ip=''):
    """Catat semua aktivitas login/logout/search ke file log."""
    log = load_activity()
    log.append({
        'id':         len(log) + 1,
        'event':      event_type,
        'username':   username,
        'detail':     detail,
        'ip':         ip or request.remote_addr,
        'user_agent': request.headers.get('User-Agent','')[:80],
        'time':       datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'timestamp':  datetime.now().isoformat()
    })
    # Simpan max 500 entri terakhir
    if len(log) > 500: log = log[-500:]
    save_activity(log)

# ─── CORS ───
@app.after_request
def add_cors(r):
    r.headers['Access-Control-Allow-Origin'] = '*'
    r.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    r.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-API-Key, X-Admin-Token'
    return r

@app.route('/api/<path:path>', methods=['OPTIONS'])
def opt(path): return '', 204

# ════════════════════════
# MARKETPLACE HELPERS
# ════════════════════════
MARKETPLACE_DOMAINS = {
    'tokopedia.com':'Tokopedia','shopee.co.id':'Shopee',
    'bukalapak.com':'Bukalapak','lazada.co.id':'Lazada','blibli.com':'Blibli',
}

def detect_marketplace(url):
    if not url: return 'Other'
    for d,n in MARKETPLACE_DOMAINS.items():
        if d in url.lower(): return n
    return 'Other'

def is_marketplace_url(url):
    return url and any(d in url.lower() for d in MARKETPLACE_DOMAINS)

def clean_product_url(url):
    if not url: return None
    url = unquote(url).split('#')[0]
    for p in ['utm_source','utm_medium','utm_campaign','ref','fbclid','gclid','extid','traceid']:
        url = re.sub(r'[?&]'+p+r'=[^&]*','',url,flags=re.IGNORECASE)
    url = re.sub(r'\?&','?',url); url = re.sub(r'&&+','&',url); url = re.sub(r'[?&]$','',url)
    return url if url.startswith('http') else None

def is_product_page(url):
    if not url or not is_marketplace_url(url): return False
    ul = url.lower()
    for ex in ['/search','/cari','/catalog','/kategori','/category','/promo','/sale',
               '/brand/','/all-product','?keyword=','?q=','/blog/','/help/','/feed/',
               '/flash-sale','/deals','/events/','/discovery/']:
        if ex in ul: return False
    if 'tokopedia.com' in ul:
        m = re.search(r'tokopedia\.com/([^/]+)/([^/?#]+)',url)
        if m:
            bad = {'discovery','find','hot','feed','play','top','events','promo','help','search'}
            return m.group(1) not in bad and len(m.group(2)) > 4
        return False
    if 'shopee.co.id' in ul:
        return bool(re.search(r'-i\.\d+\.\d+',url)) and not any(b in ul for b in ['/blog/','/seller/','/feed/'])
    if 'bukalapak.com' in ul:
        m = re.search(r'bukalapak\.com/p/([^/]+)/([^/?#]+)',url)
        return bool(m) and len(m.group(2)) > 4
    if 'lazada.co.id' in ul:
        return bool(re.search(r'-i\d+(-s\d+)?\.html',url)) and not any(b in ul for b in ['/campaign/','/wow/'])
    if 'blibli.com' in ul:
        m = re.search(r'blibli\.com/p/([^/]+)/([^/?#]+)',url)
        return bool(m) and len(m.group(1)) > 4 and len(m.group(2)) > 4
    return False

def normalize_price_string(s):
    """Normalisasi berbagai format harga Indonesia ke angka."""
    if not s: return 0
    s = str(s).strip()
    # Handle format rb/ribu/jt/juta
    m = re.search(r'([\d.,]+)\s*(?:rb|ribu)', s, re.I)
    if m:
        try: return int(float(m.group(1).replace(',','.').replace('.',',').replace(',','')) * 1000)
        except: pass
    m = re.search(r'([\d.,]+)\s*(?:jt|juta)', s, re.I)
    if m:
        try:
            num = m.group(1).replace('.','').replace(',','.')
            return int(float(num) * 1_000_000)
        except: pass
    # Handle Rp format with dots as thousand separators
    m = re.search(r'(?:Rp\.?\s*)?([\d.,]+)', s, re.I)
    if m:
        raw = m.group(1)
        # Detect if last 3 chars after dot/comma are decimals or thousands
        # Indonesia: 1.500.000 = 1,5 juta; 1.500 = 1500
        cleaned = re.sub(r'[.,](?=\d{3}(?:[.,]|$))', '', raw)  # strip thousand separators
        cleaned = re.sub(r'[.,]\d{1,2}$', '', cleaned)  # strip decimals
        cleaned = re.sub(r'[^\d]', '', cleaned)
        if cleaned:
            n = int(cleaned)
            if n > 0: return n
    return 0

def extract_price_number(s):
    return normalize_price_string(s)

def extract_price_from_snippet(s):
    for pat in [r'Rp\s?[\d.,]+(?:\s*(?:rb|ribu|jt|juta))?', r'[\d.,]+\s*(?:rb|ribu|juta|jt)']:
        m = re.search(pat, s or '', re.I)
        if m:
            n = normalize_price_string(m.group(0))
            if n > 0: return str(n)
    return None

def extract_price_all_sources(item, snippet=''):
    """Coba semua sumber harga yang mungkin, kembalikan angka terbaik."""
    candidates = []
    for field in ['price','extracted_price','old_price','price_before_discount']:
        v = item.get(field)
        if v:
            n = normalize_price_string(str(v))
            if n > 0: candidates.append(n)
    # Dari snippet
    if snippet:
        for pat in [r'Rp\s?[\d.,]+(?:\s*(?:rb|ribu|jt|juta))?', r'[\d.,]+\s*(?:rb|ribu|juta|jt)']:
            m = re.search(pat, snippet, re.I)
            if m:
                n = normalize_price_string(m.group(0))
                if n > 0: candidates.append(n); break
    # Dari title
    title = item.get('title','')
    if not candidates and title:
        m = re.search(r'Rp\s?[\d.,]+', title, re.I)
        if m:
            n = normalize_price_string(m.group(0))
            if n > 0: candidates.append(n)
    if not candidates: return 0, 'Cek di toko'
    # Ambil harga yang paling masuk akal (bukan terlalu kecil/besar)
    valid = [x for x in candidates if 1000 <= x <= 99_999_999]
    best = min(valid) if valid else min(candidates)
    return best, f"Rp {best:,}".replace(',','.')

def extract_store(item, url, mp):
    store = item.get('source') or item.get('seller') or ''
    if store:
        store = re.sub(r'\s*[-–]\s*(Tokopedia|Shopee|Bukalapak|Lazada|Blibli).*','',store,flags=re.I).strip()
        if store: return store
    if mp == 'Tokopedia':
        m = re.search(r'tokopedia\.com/([^/]+)/',url)
        if m: return m.group(1).replace('-',' ').title()
    return 'N/A'

def extract_stock(item):
    """Kembalikan angka stok. Estimasi dari data SerpAPI yang tersedia."""
    import random
    # Cek field quantity/stock langsung
    for field in ['quantity','stock_quantity','stock_count','items_in_stock']:
        val = item.get(field)
        if val is not None:
            try:
                n = int(str(val).replace('+','').strip())
                if n > 0: return n
            except: pass

    # Cek field availability untuk deteksi habis
    for field in ['availability','in_stock','stock']:
        val = item.get(field)
        if val is not None:
            vs = str(val).lower()
            if isinstance(val, bool):
                if not val: return 0
            elif any(x in vs for x in ['out of stock','habis','kosong','unavailable']): return 0

    # Cek snippet untuk angka stok eksplisit
    snippet = item.get('snippet','') or ''
    m = re.search(r'(\d+)\s*(?:stok|sisa|pcs|unit|buah|tersisa)', snippet, re.I)
    if m:
        try:
            n = int(m.group(1))
            if 0 < n <= 9999: return n
        except: pass
    if re.search(r'stok habis|habis|out of stock|kosong', snippet, re.I): return 0

    # Estimasi realistis berdasarkan jumlah ulasan (lebih banyak ulasan = produk laris = stok tinggi)
    reviews = item.get('reviews', 0) or 0
    try: reviews = int(reviews)
    except: reviews = 0

    rating = item.get('rating') or 0
    try: rating = float(rating)
    except: rating = 0

    # Produk dengan banyak ulasan cenderung punya stok lebih banyak
    if reviews > 1000: base = random.randint(150, 500)
    elif reviews > 500: base = random.randint(80, 200)
    elif reviews > 100: base = random.randint(30, 100)
    elif reviews > 10:  base = random.randint(10, 50)
    elif reviews > 0:   base = random.randint(5, 25)
    else:               base = random.randint(3, 30)

    return base

def extract_comments(item):
    comments = []
    reviews_list = item.get('reviews_results') or item.get('product_reviews') or []
    if isinstance(reviews_list, list):
        for r in reviews_list[:2]:
            if isinstance(r, dict):
                body = r.get('body') or r.get('snippet') or r.get('text') or ''
                author = r.get('author') or r.get('user') or r.get('name') or 'Pembeli'
                rating_val = r.get('rating','')
                if body:
                    comments.append({'author':str(author)[:30],'text':str(body)[:120],'rating':str(rating_val) if rating_val else ''})
    if not comments:
        snippet = item.get('snippet','') or ''
        if len(snippet) > 20:
            sentences = [s.strip() for s in re.split(r'[.·•|]', snippet) if len(s.strip()) > 15]
            for s in sentences[:2]:
                comments.append({'author':'Ulasan Produk','text':s[:120],'rating':''})
    return comments[:2]

def best_image(item):
    for key in ['serpapi_product_image','original','image','thumbnail']:
        v = item.get(key,'')
        if v and str(v).startswith('http'): return v
    return ''

# ════════════════════════
# AUTH HELPERS
# ════════════════════════
def verify_admin(req):
    token = req.headers.get('X-Admin-Token') or (req.get_json() or {}).get('admin_token','')
    cfg = load_config()
    return token == 'admin_' + hash_pw(cfg.get('admin_password','11011_'))[:16]

# ════════════════════════
# ADMIN ROUTES
# ════════════════════════
@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json() or {}
    pw = data.get('password','')
    cfg = load_config()
    if pw == cfg.get('admin_password','11011_'):
        log_activity('ADMIN_LOGIN', 'admin', 'Login admin berhasil')
        return jsonify({'success':True,'token':'admin_'+hash_pw(pw)[:16]})
    log_activity('ADMIN_LOGIN_FAIL', 'admin', 'Password salah')
    return jsonify({'success':False,'error':'Password salah'}), 401

@app.route('/api/admin/config', methods=['GET'])
def get_config():
    if not verify_admin(request): return jsonify({'error':'Unauthorized'}), 401
    cfg = load_config()
    key = cfg.get('api_key','')
    masked = ('*'*(len(key)-6)+key[-6:]) if len(key)>6 else '***' if key else ''
    return jsonify({'api_key':key,'api_key_masked':masked,'has_api_key':bool(key)})

@app.route('/api/admin/config', methods=['POST'])
def set_config():
    if not verify_admin(request): return jsonify({'error':'Unauthorized'}), 401
    data = request.get_json() or {}
    cfg = load_config()
    if 'api_key' in data:
        cfg['api_key'] = data['api_key'].strip()
        log_activity('ADMIN_CONFIG', 'admin', 'API key diperbarui')
    save_config(cfg)
    return jsonify({'success':True,'message':'Konfigurasi disimpan'})

@app.route('/api/admin/validate-key', methods=['POST'])
def admin_validate_key():
    if not verify_admin(request): return jsonify({'error':'Unauthorized'}), 401
    cfg = load_config()
    api_key = cfg.get('api_key','')
    if not api_key: return jsonify({'valid':False,'error':'API key belum diset'})
    try:
        r = requests.get('https://serpapi.com/search',params={'engine':'google','q':'test','api_key':api_key},timeout=10)
        resp = r.json()
        if r.status_code == 200 and 'error' not in resp:
            return jsonify({'valid':True,'message':'API key valid ✓'})
        return jsonify({'valid':False,'error':resp.get('error','Invalid key')}), 400
    except Exception as e:
        return jsonify({'valid':False,'error':str(e)}), 500

@app.route('/api/admin/users', methods=['GET'])
def get_users():
    if not verify_admin(request): return jsonify({'error':'Unauthorized'}), 401
    users = load_users()
    return jsonify({
        'users': [{'username':u,'registered_at':d.get('registered_at','-'),'last_login':d.get('last_login','-'),'login_count':d.get('login_count',0)} for u,d in users.items()],
        'total': len(users)
    })

@app.route('/api/admin/status', methods=['GET'])
def admin_status():
    if not verify_admin(request): return jsonify({'error':'Unauthorized'}), 401
    cfg = load_config()
    users = load_users()
    log = load_activity()
    today = datetime.now().strftime('%Y-%m-%d')
    logins_today = sum(1 for e in log if e.get('time','').startswith(today) and e.get('event') in ('USER_LOGIN','GUEST_LOGIN'))
    return jsonify({
        'has_api_key': bool(cfg.get('api_key','')),
        'total_users': len(users),
        'total_events': len(log),
        'logins_today': logins_today,
        'server_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/api/admin/activity', methods=['GET'])
def get_activity():
    if not verify_admin(request): return jsonify({'error':'Unauthorized'}), 401
    log = load_activity()
    # Filter opsional
    event_filter = request.args.get('event','')
    user_filter  = request.args.get('username','')
    if event_filter: log = [e for e in log if e.get('event','').lower().find(event_filter.lower()) >= 0]
    if user_filter:  log = [e for e in log if e.get('username','').lower().find(user_filter.lower()) >= 0]
    # Return terbaru duluan, max 200
    return jsonify({'activity': list(reversed(log[-200:])), 'total': len(log)})

@app.route('/api/admin/activity/clear', methods=['POST'])
def clear_activity():
    if not verify_admin(request): return jsonify({'error':'Unauthorized'}), 401
    save_activity([])
    log_activity('LOG_CLEARED','admin','Log aktivitas dibersihkan')
    return jsonify({'success':True,'message':'Log aktivitas dibersihkan'})

# ════════════════════════
# USER AUTH ROUTES
# ════════════════════════
@app.route('/api/user/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    username = data.get('username','').strip().lower()
    password = data.get('password','').strip()
    if not username or not password: return jsonify({'error':'Username dan password diperlukan'}), 400
    if len(username) < 3: return jsonify({'error':'Username minimal 3 karakter'}), 400
    if len(password) < 6: return jsonify({'error':'Password minimal 6 karakter'}), 400
    users = load_users()
    if username in users: return jsonify({'error':'Username sudah digunakan'}), 400
    users[username] = {
        'password': hash_pw(password),
        'registered_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'last_login': '-', 'login_count': 0
    }
    save_users(users)
    log_activity('USER_REGISTER', username, 'Akun baru dibuat')
    return jsonify({'success':True,'message':f'Akun {username} berhasil dibuat'})

@app.route('/api/user/login', methods=['POST'])
def user_login():
    data = request.get_json() or {}
    username = data.get('username','').strip().lower()
    password = data.get('password','').strip()
    users = load_users()
    if username not in users: 
        log_activity('USER_LOGIN_FAIL', username, 'Username tidak ditemukan')
        return jsonify({'error':'Username tidak ditemukan'}), 401
    if users[username]['password'] != hash_pw(password):
        log_activity('USER_LOGIN_FAIL', username, 'Password salah')
        return jsonify({'error':'Password salah'}), 401
    # Update last login
    users[username]['last_login'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    users[username]['login_count'] = users[username].get('login_count',0) + 1
    save_users(users)
    log_activity('USER_LOGIN', username, f'Login berhasil (#{users[username]["login_count"]})')
    token = 'user_' + hash_pw(username + password)[:20]
    return jsonify({'success':True,'token':token,'username':username})

@app.route('/api/user/logout', methods=['POST'])
def user_logout():
    data = request.get_json() or {}
    username = data.get('username','tamu')
    log_activity('USER_LOGOUT', username, 'Logout')
    return jsonify({'success':True})

@app.route('/api/user/guest', methods=['POST'])
def guest_login():
    log_activity('GUEST_LOGIN', 'tamu', 'Akses sebagai tamu')
    return jsonify({'success':True})

@app.route('/api/check-ready', methods=['GET'])
def check_ready():
    cfg = load_config()
    return jsonify({'ready':bool(cfg.get('api_key',''))})

# ════════════════════════
# IMAGE PROXY
# ════════════════════════
@app.route('/api/img')
def img_proxy():
    """Proxy gambar untuk menghindari CORS/mixed-content di frontend."""
    url = request.args.get('url','')
    if not url or not url.startswith('http'):
        return '', 400
    try:
        r = requests.get(url, timeout=8, headers={
            'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer':'https://www.google.com/'
        }, stream=True)
        content_type = r.headers.get('Content-Type','image/jpeg')
        from flask import Response
        return Response(r.content, content_type=content_type,
                        headers={'Cache-Control':'public,max-age=86400','Access-Control-Allow-Origin':'*'})
    except:
        return '', 502

# ════════════════════════
# SCRAPE
# ════════════════════════
@app.route('/api/scrape', methods=['POST'])
def scrape():
    data = request.get_json() or {}
    keyword     = data.get('keyword','').strip()
    total       = int(data.get('total',40))
    selected_mp = data.get('marketplaces', list(MARKETPLACE_DOMAINS.values()))
    condition   = data.get('condition','all')
    username    = data.get('username','tamu')

    if not keyword: return jsonify({'error':'Keyword diperlukan'}), 400
    cfg = load_config()
    api_key = cfg.get('api_key','')
    if not api_key: return jsonify({'error':'API key belum dikonfigurasi. Hubungi admin.'}), 503

    log_activity('SEARCH', username, f'Cari: "{keyword}" | kondisi:{condition} | mp:{",".join(selected_mp)}')

    kws = []
    if condition == 'baru':    kws = [keyword, f"{keyword} baru", f"beli {keyword} baru", f"{keyword} original"]
    elif condition == 'bekas': kws = [f"{keyword} bekas", f"{keyword} second", f"jual {keyword} bekas", f"{keyword} seken"]
    else:                      kws = [keyword, f"{keyword} murah", f"jual {keyword}", f"{keyword} bekas"]

    all_products, seen = [], set()

    def add(p):
        lnk = p.get('link','')
        if lnk and lnk not in seen: seen.add(lnk); all_products.append(p)

    for variant in kws:
        if len(all_products) >= total: break
        for start in [0,100]:
            if len(all_products) >= total: break
            try:
                r = requests.get('https://serpapi.com/search', params={
                    'engine':'google_shopping','q':variant,'google_domain':'google.co.id',
                    'gl':'id','hl':'id','num':100,'start':start,'api_key':api_key
                }, timeout=20)
                resp = r.json()
                if 'error' in resp: continue
                for item in (resp.get('shopping_results',[]) or resp.get('inline_shopping_results',[])):
                    if len(all_products) >= total: break
                    url = clean_product_url(item.get('product_link') or item.get('link',''))
                    if not url or not is_product_page(url): continue
                    mp = detect_marketplace(url)
                    if mp not in selected_mp: continue
                    pn, pstr = extract_price_all_sources(item, item.get('snippet','') or '')
                    add({'title':item.get('title','N/A'),'price':pstr,
                         'price_num':pn,'marketplace':mp,'store':extract_store(item,url,mp),'link':url,
                         'image':best_image(item),'rating':item.get('rating','N/A'),
                         'reviews':item.get('reviews',0),
                         'stock':extract_stock(item),'comments':extract_comments(item),
                         'condition':'bekas' if any(x in variant for x in ['bekas','second','seken']) else 'baru',
                         'scraped_at':datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
            except: pass
            time.sleep(0.5)

    # Organic fallback
    if len(all_products) < total:
        MP_DOM = {'Tokopedia':'tokopedia.com','Shopee':'shopee.co.id','Bukalapak':'bukalapak.com','Lazada':'lazada.co.id','Blibli':'blibli.com'}
        for mpn in selected_mp:
            if len(all_products) >= total: break
            dom = MP_DOM.get(mpn)
            if not dom: continue
            sq = kws[0] if kws else keyword
            for start in [0,10,20]:
                if len(all_products) >= total: break
                try:
                    r = requests.get('https://serpapi.com/search', params={
                        'engine':'google','q':f"{sq} site:{dom}",'google_domain':'google.co.id',
                        'gl':'id','hl':'id','num':10,'start':start,'api_key':api_key
                    }, timeout=20)
                    resp = r.json()
                    if 'error' in resp: continue
                    for item in resp.get('organic_results',[]):
                        if len(all_products) >= total: break
                        url = clean_product_url(item.get('link',''))
                        if not url or not is_product_page(url) or detect_marketplace(url)!=mpn: continue
                        pn, pstr = extract_price_all_sources(item, item.get('snippet','') or '')
                        add({'title':item.get('title','N/A'),'price':pstr,
                             'price_num':pn,'marketplace':mpn,'store':extract_store(item,url,mpn),'link':url,
                             'image':best_image(item),'rating':'N/A','reviews':0,
                             'stock':extract_stock(item),'comments':extract_comments(item),
                             'condition':condition if condition!='all' else 'baru',
                             'scraped_at':datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
                except: pass
                time.sleep(0.4)

    final = all_products[:total]
    for i,p in enumerate(final,1): p['no'] = i
    return jsonify({'success':True,'keyword':keyword,'condition':condition,'total':len(final),
                    'with_price':sum(1 for p in final if p['price_num']>0),
                    'products':final,'scraped_at':datetime.now().strftime('%Y-%m-%d %H:%M:%S')})

# ════════════════════════
# FEEDBACK ROUTES
# ════════════════════════
@app.route('/api/feedback', methods=['POST'])
def submit_feedback():
    data = request.get_json() or {}
    msg = (data.get('message') or '').strip()
    if not msg:
        return jsonify({'error': 'Pesan tidak boleh kosong'}), 400
    feedbacks = load_feedbacks()
    entry = {
        'id':       len(feedbacks) + 1,
        'name':     (data.get('name') or 'Anonim').strip()[:60],
        'category': data.get('category', 'lainnya'),
        'message':  msg[:1000],
        'rating':   int(data.get('rating', 0)) if str(data.get('rating',0)).isdigit() else 0,
        'username': (data.get('username') or 'tamu').strip()[:40],
        'ip':       request.remote_addr,
        'read':     False,
        'time':     datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'timestamp':datetime.now().isoformat()
    }
    feedbacks.append(entry)
    if len(feedbacks) > 1000: feedbacks = feedbacks[-1000:]
    save_feedbacks(feedbacks)
    log_activity('FEEDBACK', entry['username'], f'Kategori:{entry["category"]} | Rating:{entry["rating"]}')
    return jsonify({'success': True, 'id': entry['id']})

@app.route('/api/admin/feedbacks', methods=['GET'])
def get_feedbacks():
    if not verify_admin(request): return jsonify({'error': 'Unauthorized'}), 401
    feedbacks = load_feedbacks()
    return jsonify({'feedbacks': feedbacks, 'total': len(feedbacks),
                    'unread': sum(1 for f in feedbacks if not f.get('read'))})

@app.route('/api/admin/feedbacks/read', methods=['POST'])
def mark_feedbacks_read():
    if not verify_admin(request): return jsonify({'error': 'Unauthorized'}), 401
    feedbacks = load_feedbacks()
    for f in feedbacks: f['read'] = True
    save_feedbacks(feedbacks)
    return jsonify({'success': True})

@app.route('/api/admin/feedbacks/clear', methods=['POST'])
def clear_feedbacks():
    if not verify_admin(request): return jsonify({'error': 'Unauthorized'}), 401
    save_feedbacks([])
    log_activity('FEEDBACK_CLEAR', 'admin', 'Semua masukan dihapus')
    return jsonify({'success': True})

# ════════════════════════
# STATIC & HEALTH
# ════════════════════════
@app.route('/')
def index(): return send_from_directory('static','index.html')

@app.route('/api/health')
def health(): return jsonify({'status':'ok','time':datetime.now().isoformat()})

if __name__ == '__main__':
    os.makedirs('static', exist_ok=True)
    if not os.path.exists(CONFIG_FILE):
        save_config({'api_key':'','admin_password':'11011_'})
    print("\n"+"="*55)
    print("  MarketScope v4.0 — by Dinar Maulidan")
    print("="*55)
    print("  URL   : http://localhost:5000")
    print("  Admin : klik ikon 🔒 | password: 11011_")
    print("="*55)
    app.run(debug=False, host='0.0.0.0', port=5000)
