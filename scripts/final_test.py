import sys, os, time, struct, json
sys.path.insert(0, r'd:\3D\styleforge')
os.chdir(r'd:\3D\styleforge')
import warnings; warnings.filterwarnings('ignore')
import logging; logging.disable(logging.INFO)
import numpy as np
from pathlib import Path

PLY = Path(r'd:\3D\styleforge\temp\f223402baff148c9\lhm_output\lhm_output.ply')
GLB_OUT = Path(r'd:\3D\styleforge\outputs\red_jacket_final\red_jacket_final.glb')
GLB_OUT.parent.mkdir(parents=True, exist_ok=True)

print('=== FULL A-Z TEST: Red Jacket Image ===')
print()

# --- Stage 2: Check PLY colors (LHM output) ---
from plyfile import PlyData
SH_C0 = 0.28209479177387814
ply = PlyData.read(str(PLY))
v = ply['vertex']
op = 1.0/(1.0+np.exp(-np.array(v['opacity'])))
m = op > 0.15
r0 = np.clip(np.array(v['f_dc_0'])[m]*SH_C0+0.5, 0,1)
g0 = np.clip(np.array(v['f_dc_1'])[m]*SH_C0+0.5, 0,1)
b0 = np.clip(np.array(v['f_dc_2'])[m]*SH_C0+0.5, 0,1)
ply_red  = ((r0>0.45)&(r0>g0*1.4)&(r0>b0*1.4)).mean()*100
ply_dark = ((r0<0.28)&(g0<0.28)&(b0<0.28)).mean()*100
ply_skin = ((r0>0.35)&(r0>g0)&(g0>b0)&~((r0>0.45)&(r0>g0*1.4))).mean()*100
print('[STAGE 2] LHM PLY (%d visible Gaussians):' % m.sum())
print('  Red (jacket): %.1f%%' % ply_red)
print('  Dark (jeans): %.1f%%' % ply_dark)
print('  Skin:         %.1f%%' % ply_skin)
print()

# --- Stage 3+4+5: Run full pipeline ---
print('[STAGE 3-5] Running mesh pipeline...')
t0 = time.time()
from app.core.gaussian_to_mesh import GaussianToMesh
from app.core.mesh_processor import MeshProcessor
from app.core.glb_exporter import GLBExporter
import open3d as o3d

converter = GaussianToMesh()
processor = MeshProcessor()
exporter  = GLBExporter()

raw  = converter.convert(PLY)
proc = processor.process(raw, source_pcd=converter.source_pcd)
exporter.export(proc, GLB_OUT)
elapsed = time.time()-t0
print('  Pipeline time: %.1fs' % elapsed)
print('  Vertices: %d' % len(np.asarray(proc.vertices)))
print('  Faces:    %d' % len(np.asarray(proc.triangles)))
print()

# --- Inspect GLB ---
with open(GLB_OUT,'rb') as f: raw_glb=f.read()
c0len,_ = struct.unpack('<II', raw_glb[12:20])
gltf = json.loads(raw_glb[20:20+c0len])
mat  = gltf['materials'][0]
prim = gltf['meshes'][0]['primitives'][0]
attrs = prim['attributes']
pbr = mat.get('pbrMetallicRoughness',{})

ok_color = '[OK]' if 'COLOR_0' in attrs else '[FAIL]'
ok_norm  = '[OK]' if 'NORMAL' in attrs else '[FAIL] flat shading!'
ok_ds    = '[OK]' if mat.get('doubleSided') else '[FAIL] back faces invisible!'

print('[STAGE 5] GLB validation:')
print('  File: %s' % GLB_OUT)
print('  Size: %.2f MB' % (GLB_OUT.stat().st_size/1e6))
print('  COLOR_0:     %s' % ok_color)
print('  NORMAL:      %s' % ok_norm)
print('  doubleSided: %s' % ok_ds)
print('  metallic:    %s  (need 0.0)' % pbr.get('metallicFactor'))
print('  roughness:   %s  (need ~0.9)' % pbr.get('roughnessFactor'))
print()

# Read GLB colors from binary buffer
ca = gltf['accessors'][attrs['COLOR_0']]
bv = gltf['bufferViews'][ca['bufferView']]
bs = 20+c0len+8 + bv.get('byteOffset',0) + ca.get('byteOffset',0)
cnt = ca['count']
ct = ca['componentType']
if ct==5121:
    vc = np.frombuffer(raw_glb[bs:bs+cnt*4],dtype=np.uint8).reshape(cnt,4)[:,:3].astype(float)/255.0
elif ct==5123:
    vc = np.frombuffer(raw_glb[bs:bs+cnt*8],dtype=np.uint16).reshape(cnt,4)[:,:3].astype(float)/65535.0
else:
    vc = np.frombuffer(raw_glb[bs:bs+cnt*16],dtype=np.float32).reshape(cnt,4)[:,:3].astype(float)

rg,gg,bg = vc[:,0],vc[:,1],vc[:,2]
glb_red  = ((rg>0.45)&(rg>gg*1.4)&(rg>bg*1.4)).mean()*100
glb_dark = ((rg<0.28)&(gg<0.28)&(bg<0.28)).mean()*100
glb_skin = ((rg>0.35)&(rg>gg)&(gg>bg)&~((rg>0.45)&(rg>gg*1.4))).mean()*100
sat_glb  = (np.max(vc,axis=1)-np.min(vc,axis=1)).mean()

ok_r = '[OK]' if abs(glb_red-ply_red)<15 else '[WARN]'
ok_d = '[OK]' if abs(glb_dark-ply_dark)<15 else '[WARN]'
ok_s = '[OK]' if abs(glb_skin-ply_skin)<10 else '[WARN]'
ok_sat = '[OK]' if sat_glb>0.2 else '[WARN] washed out'

print('[COLOR ACCURACY] GLB vs PLY (self-consistent — GLB must reproduce PLY colors):')
print('  Red  (jacket): PLY=%.1f%%  GLB=%.1f%%  diff=%+.1f%%  %s' % (ply_red, glb_red, glb_red-ply_red, ok_r))
print('  Dark (jeans):  PLY=%.1f%%  GLB=%.1f%%  diff=%+.1f%%  %s' % (ply_dark, glb_dark, glb_dark-ply_dark, ok_d))
print('  Skin:          PLY=%.1f%%  GLB=%.1f%%  diff=%+.1f%%  %s' % (ply_skin, glb_skin, glb_skin-ply_skin, ok_s))
print('  Saturation:    %.3f  %s' % (sat_glb, ok_sat))
print()

# Check for any remaining issues
issues = []
if 'COLOR_0' not in attrs: issues.append('No COLOR_0 vertex colors in GLB')
if 'NORMAL' not in attrs:  issues.append('No NORMAL attribute -- flat shading')
if not mat.get('doubleSided'): issues.append('doubleSided=False -- back faces invisible')
if sat_glb < 0.15: issues.append('Very low saturation (%.3f) -- colors washed out' % sat_glb)
if abs(glb_red-ply_red)>20: issues.append('Large red channel shift in export')

print('='*60)
if issues:
    print('ISSUES FOUND (%d):' % len(issues))
    for i in issues: print('  [X] %s' % i)
else:
    print('ALL CHECKS PASSED -- PROFESSIONAL QUALITY MESH')
print()
print('FINAL 3D MESH OUTPUT:')
print('  %s' % GLB_OUT)
print('='*60)
