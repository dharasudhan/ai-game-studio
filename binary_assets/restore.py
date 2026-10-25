import os,base64
root=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src=os.path.join(root,'binary_assets','files')
n=0
for d,_,fs in os.walk(src):
    for f in fs:
        if not f.endswith('.b64'): continue
        rel=os.path.relpath(os.path.join(d,f),src)[:-4]
        out=os.path.join(root,rel); os.makedirs(os.path.dirname(out),exist_ok=True)
        open(out,'wb').write(base64.b64decode(open(os.path.join(d,f)).read())); n+=1
print('restored',n,'files')
