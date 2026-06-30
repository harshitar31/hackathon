import urllib.request
import json

def fetch(url, method='GET', headers=None, data=None):
    req = urllib.request.Request(url, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    if data:
        req.add_header('Content-Type', 'application/json')
        data = json.dumps(data).encode('utf-8')
    resp = urllib.request.urlopen(req, data=data)
    return json.loads(resp.read().decode('utf-8'))

def test():
    # 1. Get documents
    docs = fetch('http://localhost:8000/documents')
    doc_id = docs[0]['doc_id']
    
    headers = {'X-Session-ID': 'test-undo-3'}
    
    # 2. Get initial span
    doc = fetch(f'http://localhost:8000/documents/{doc_id}', headers=headers)
    span_id = doc['redactions'][0]['span_id']
    print(f"Initial status: {doc['redactions'][0]['display_status']}")
    
    # 3. Override
    fetch('http://localhost:8000/override', method='POST', headers=headers, data={'span_id': span_id})
    doc = fetch(f'http://localhost:8000/documents/{doc_id}', headers=headers)
    print(f"After override: {doc['redactions'][0]['display_status']}")
    
    # 4. Undo
    fetch('http://localhost:8000/undo', method='POST', headers=headers)
    doc = fetch(f'http://localhost:8000/documents/{doc_id}', headers=headers)
    print(f"After undo: {doc['redactions'][0]['display_status']}")

test()
