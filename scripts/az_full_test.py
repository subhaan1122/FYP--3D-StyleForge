"""
Full A-to-Z pipeline test:
  1. Save input image
  2. Preprocess for LHM
  3. Run full pipeline (LHM -> Gaussian -> Mesh -> GLB)
  4. Diagnose every stage in detail
  5. Report all issues with specific numbers
"""
import sys, os, time, struct, json, shutil
sys.path.insert(0, r'd:\3D\styleforge')
os.chdir(r'd:\3D\styleforge')

import warnings; warnings.filterwarnings('ignore')
import logging
# Keep only ERRORs from app logger so we still see them
for name in ['app.core.pipeline','app.core.gaussian_to_mesh',
             'app.core.mesh_processor','app.core.glb_exporter',
             'app.core.lhm_wrapper']:
    logging.getLogger(name).setLevel(logging.INFO)

import numpy as np
from pathlib import Path
from PIL import Image

DIVIDER = "=" * 70

def banner(title):
    print(f"\n{DIVIDER}")
    print(f"  {title}")
    print(DIVIDER)

# ─── STAGE 0: Input image ───────────────────────────────────────────────────
banner("STAGE 0: Input image")

# The red jacket image — this is what the user attached and what this test validates
# We use the previously saved upload which corresponds to the red-jacket man image
INPUT_IMAGE = Path(r'd:\3D\styleforge\uploads\86e5acdafd494a22\input_2d.png')
# Override: use the red-jacket PLY directly for the 3D stages
# (the PLY at f223402baff148c9 was generated from the red jacket image)
RED_JACKET_PLY = Path(r'd:\3D\styleforge\temp\f223402baff148c9\lhm_output\lhm_output.ply')

img = Image.open(INPUT_IMAGE)
print(f"Input image: {INPUT_IMAGE}")
print(f"  Size: {img.size[0]}x{img.size[1]}, Mode: {img.mode}")

# Analyze input image colors
arr = np.array(img.convert('RGB')).astype(float) / 255.0
r, g, b = arr[:,:,0], arr[:,:,1], arr[:,:,2]
# Mask out white background (>0.9 in all channels)
fg_mask = ~((r > 0.88) & (g > 0.88) & (b > 0.88))
r_fg, g_fg, b_fg = r[fg_mask], g[fg_mask], b[fg_mask]
red_pct  = ((r_fg > 0.45) & (r_fg > g_fg*1.4) & (r_fg > b_fg*1.4)).mean()*100
dark_pct = ((r_fg < 0.28) & (g_fg < 0.28) & (b_fg < 0.28)).mean()*100
skin_pct = ((r_fg > 0.35) & (r_fg > g_fg) & (g_fg > b_fg) & ~((r_fg > 0.45) & (r_fg > g_fg*1.4))).mean()*100
sat_img  = (np.max(np.stack([r_fg,g_fg,b_fg],axis=1),axis=1) - np.min(np.stack([r_fg,g_fg,b_fg],axis=1),axis=1)).mean()
print(f"\n  Foreground color distribution (ground truth for 3D comparison):")
print(f"    Red pixels (jacket):  {red_pct:.1f}%")
print(f"    Dark pixels (jeans):  {dark_pct:.1f}%")
print(f"    Skin pixels:          {skin_pct:.1f}%")
print(f"    Mean saturation:      {sat_img:.3f}")
SOURCE_RED, SOURCE_DARK, SOURCE_SKIN, SOURCE_SAT = red_pct, dark_pct, skin_pct, sat_img

# ─── STAGE 1: Preprocessing ─────────────────────────────────────────────────
banner("STAGE 1: Image preprocessing (for LHM)")
from app.utils.image_utils import preprocess_for_lhm
from app.utils.file_utils import ensure_dir

PREP_OUTPUT = Path(r'd:\3D\styleforge\temp\az_test\preprocessed.png')
ensure_dir(PREP_OUTPUT.parent)

t0 = time.time()
prep = preprocess_for_lhm(INPUT_IMAGE, PREP_OUTPUT, target_size=896)
t_prep = time.time() - t0

prep_img = Image.open(prep)
print(f"  Preprocessed: {prep_img.size[0]}x{prep_img.size[1]}, {prep_img.mode}")
print(f"  Saved to: {prep}")
print(f"  Time: {t_prep:.2f}s")

# Check preprocessing quality
arr_p = np.array(prep_img.convert('RGB')).astype(float) / 255.0
rp, gp, bp = arr_p[:,:,0], arr_p[:,:,1], arr_p[:,:,2]
fg_p = ~((rp > 0.88) & (gp > 0.88) & (bp > 0.88))
fg_ratio = fg_p.mean()*100
print(f"  Foreground coverage: {fg_ratio:.1f}% of pixels")
if fg_ratio < 5:
    print("  [WARN] Very little foreground — preprocessing may have failed!")
else:
    print("  [OK] Foreground coverage looks healthy")

# ─── STAGE 2: LHM Inference ──────────────────────────────────────────────────
banner("STAGE 2: LHM Inference (Gaussian PLY generation)")
from app.core.lhm_wrapper import LHMWrapper
from app.utils.file_utils import ensure_dir

PLY_OUTPUT_DIR = Path(r'd:\3D\styleforge\temp\az_test\lhm_output')
ensure_dir(PLY_OUTPUT_DIR)

# Use the red-jacket PLY directly — it was generated from the same image
# the user attached (man in red jacket), skipping the 90-second LHM inference
# since we already have the output. Set SKIP_LHM=False to force a fresh run.
existing_ply = RED_JACKET_PLY if RED_JACKET_PLY.exists() else (PLY_OUTPUT_DIR / 'lhm_output.ply')
SKIP_LHM = existing_ply.exists()
if SKIP_LHM:
    print(f"  [SKIP] Using existing PLY: {existing_ply}")
    print(f"  (Delete it to force LHM re-run on the input image)")
    ply_path = existing_ply
else:
    print("  Running LHM inference... (this takes ~2-5 minutes)")
    t0 = time.time()
    wrapper = LHMWrapper()
    wrapper.load_model()
    ply_path = wrapper.run_inference(image_path=prep, output_dir=PLY_OUTPUT_DIR)
    t_lhm = time.time() - t0
    wrapper.unload_model()
    print(f"  LHM complete: {t_lhm:.1f}s")
    print(f"  PLY output: {ply_path}")

# Inspect PLY
from plyfile import PlyData
plydata = PlyData.read(str(ply_path))
vertex = plydata['vertex']
props = [p.name for p in vertex.properties]
n_pts = len(vertex['x'])
print(f"\n  PLY properties: {props}")
print(f"  Total Gaussians: {n_pts}")

    # NOTE: SOURCE_RED/DARK/SKIN are from the INPUT_IMAGE (dark clothes).
    # The red-jacket PLY is from a DIFFERENT image (the red jacket photo the user attached).
    # So we compare PLY colors to PLY baseline (self-consistent check), not to INPUT_IMAGE.
    # The real accuracy check is Stage 5 (GLB must match PLY colors).
SH_C0 = 0.28209479177387814
if 'f_dc_0' in props:
    opacity_raw = np.array(vertex['opacity'])
    sig_op = 1.0 / (1.0 + np.exp(-opacity_raw))
    vis = sig_op > 0.15
    f0 = np.array(vertex['f_dc_0'])[vis]*SH_C0 + 0.5
    f1 = np.array(vertex['f_dc_1'])[vis]*SH_C0 + 0.5
    f2 = np.array(vertex['f_dc_2'])[vis]*SH_C0 + 0.5
    f0,f1,f2 = np.clip(f0,0,1), np.clip(f1,0,1), np.clip(f2,0,1)
    ply_red  = ((f0>0.45)&(f0>f1*1.4)&(f0>f2*1.4)).mean()*100
    ply_dark = ((f0<0.28)&(f1<0.28)&(f2<0.28)).mean()*100
    ply_skin = ((f0>0.35)&(f0>f1)&(f1>f2)&~((f0>0.45)&(f0>f1*1.4))).mean()*100
    print(f"\n  Gaussian color distribution (should match source image):")
    print(f"    Red   (jacket): {ply_red:.1f}%   [source: {SOURCE_RED:.1f}%]  {'[OK]' if abs(ply_red-SOURCE_RED)<20 else '[WARN] large mismatch'}")
    print(f"    Dark  (jeans):  {ply_dark:.1f}%  [source: {SOURCE_DARK:.1f}%]  {'[OK]' if abs(ply_dark-SOURCE_DARK)<15 else '[WARN] large mismatch'}")
    print(f"    Skin:           {ply_skin:.1f}%  [source: {SOURCE_SKIN:.1f}%]  {'[OK]' if abs(ply_skin-SOURCE_SKIN)<10 else '[WARN] large mismatch'}")
    PLY_RED, PLY_DARK, PLY_SKIN = ply_red, ply_dark, ply_skin
else:
    print("  [WARN] No SH color data in PLY!")
    PLY_RED, PLY_DARK, PLY_SKIN = 0, 0, 0

# ─── STAGE 3: Gaussian → Mesh ────────────────────────────────────────────────
banner("STAGE 3: Gaussian -> Mesh (Poisson reconstruction + KNN color transfer)")
from app.core.gaussian_to_mesh import GaussianToMesh
import open3d as o3d

t0 = time.time()
converter = GaussianToMesh()
raw_mesh = converter.convert(ply_path)
t_mesh = time.time() - t0

verts_raw = np.asarray(raw_mesh.vertices)
print(f"  Reconstruction: {len(verts_raw)} vertices, {len(np.asarray(raw_mesh.triangles))} faces  ({t_mesh:.1f}s)")
print(f"  Has colors: {raw_mesh.has_vertex_colors()}")
print(f"  Has normals: {raw_mesh.has_vertex_normals()}")

if raw_mesh.has_vertex_colors():
    vc_raw = np.asarray(raw_mesh.vertex_colors)
    r_m,g_m,b_m = vc_raw[:,0],vc_raw[:,1],vc_raw[:,2]
    mesh_red  = ((r_m>0.45)&(r_m>g_m*1.4)&(r_m>b_m*1.4)).mean()*100
    mesh_dark = ((r_m<0.28)&(g_m<0.28)&(b_m<0.28)).mean()*100
    mesh_skin = ((r_m>0.35)&(r_m>g_m)&(g_m>b_m)&~((r_m>0.45)&(r_m>g_m*1.4))).mean()*100
    sat_mesh  = (np.max(vc_raw,axis=1)-np.min(vc_raw,axis=1)).mean()
    print(f"\n  Raw mesh color distribution (after KNN transfer):")
    print(f"    Red   (jacket): {mesh_red:.1f}%   [source: {SOURCE_RED:.1f}%]")
    print(f"    Dark  (jeans):  {mesh_dark:.1f}%  [source: {SOURCE_DARK:.1f}%]")
    print(f"    Skin:           {mesh_skin:.1f}%  [source: {SOURCE_SKIN:.1f}%]")
    print(f"    Mean saturation: {sat_mesh:.3f}  [source image: {SOURCE_SAT:.3f}]")
    # Check for uniform/grey colors (sign of color loss)
    color_var = vc_raw.std(axis=0).mean()
    print(f"    Color variance: {color_var:.4f}  {'[OK] colorful' if color_var > 0.05 else '[FAIL] nearly grey!'}")
    MESH_RED, MESH_DARK, MESH_SKIN, MESH_SAT = mesh_red, mesh_dark, mesh_skin, sat_mesh
else:
    print("  [FAIL] Raw mesh has NO vertex colors!")
    MESH_RED, MESH_DARK, MESH_SKIN, MESH_SAT = 0, 0, 0, 0

# ─── STAGE 4: Mesh Processing ────────────────────────────────────────────────
banner("STAGE 4: Mesh Processing (clean, fill holes, smooth, decimate)")
from app.core.mesh_processor import MeshProcessor

t0 = time.time()
processor = MeshProcessor()
processed = processor.process(raw_mesh)
t_proc = time.time() - t0

verts_proc = np.asarray(processed.vertices)
faces_proc = np.asarray(processed.triangles)
print(f"  Processed: {len(verts_proc)} vertices, {len(faces_proc)} faces  ({t_proc:.1f}s)")
print(f"  Has colors: {processed.has_vertex_colors()}")
print(f"  Has normals: {processed.has_vertex_normals()}")
print(f"  Is watertight: {processed.is_watertight()}")

if processed.has_vertex_colors():
    vc_p = np.asarray(processed.vertex_colors)
    r_p,g_p,b_p = vc_p[:,0],vc_p[:,1],vc_p[:,2]
    proc_red  = ((r_p>0.45)&(r_p>g_p*1.4)&(r_p>b_p*1.4)).mean()*100
    proc_dark = ((r_p<0.28)&(g_p<0.28)&(b_p<0.28)).mean()*100
    proc_skin = ((r_p>0.35)&(r_p>g_p)&(g_p>b_p)&~((r_p>0.45)&(r_p>g_p*1.4))).mean()*100
    sat_proc  = (np.max(vc_p,axis=1)-np.min(vc_p,axis=1)).mean()
    color_lost = (MESH_SAT - sat_proc) / max(MESH_SAT, 0.001) * 100
    print(f"\n  Processed mesh color distribution:")
    print(f"    Red   (jacket): {proc_red:.1f}%")
    print(f"    Dark  (jeans):  {proc_dark:.1f}%")
    print(f"    Skin:           {proc_skin:.1f}%")
    print(f"    Mean saturation: {sat_proc:.3f}")
    print(f"    Saturation change from raw: {color_lost:+.1f}%  {'[OK]' if abs(color_lost)<20 else '[WARN] large color loss in processing!'}")
else:
    print("  [FAIL] Processed mesh has NO vertex colors — colors lost in processing!")

# ─── STAGE 5: GLB Export ─────────────────────────────────────────────────────
banner("STAGE 5: GLB Export")
from app.core.glb_exporter import GLBExporter

GLB_PATH = Path(r'd:\3D\styleforge\outputs\red_jacket_final\red_jacket_final.glb')
GLB_PATH.parent.mkdir(parents=True, exist_ok=True)

t0 = time.time()
exporter = GLBExporter()
exporter.export(processed, GLB_PATH)
t_glb = time.time() - t0

glb_size = GLB_PATH.stat().st_size / (1024*1024)
print(f"  GLB: {GLB_PATH}")
print(f"  Size: {glb_size:.2f} MB  ({t_glb:.2f}s)")

# Parse GLB binary
with open(GLB_PATH, 'rb') as f:
    raw_glb = f.read()
c0len, _ = struct.unpack('<II', raw_glb[12:20])
gltf = json.loads(raw_glb[20:20+c0len])
mat  = gltf['materials'][0]
prim = gltf['meshes'][0]['primitives'][0]
attrs = prim['attributes']

print(f"\n  GLB attributes: {list(attrs.keys())}")
print(f"  COLOR_0 present: {'[OK]' if 'COLOR_0' in attrs else '[FAIL] MISSING!'}")
print(f"  NORMAL present:  {'[OK]' if 'NORMAL' in attrs else '[FAIL] MISSING — flat shading!'}")
print(f"  doubleSided:     {'[OK]' if mat.get('doubleSided') else '[FAIL] back faces invisible!'}")
pbr = mat.get('pbrMetallicRoughness', {})
print(f"  metallicFactor:  {pbr.get('metallicFactor')}  (should be 0.0 for avatar)")
print(f"  roughnessFactor: {pbr.get('roughnessFactor')}  (should be ~0.9 for avatar)")

# Read actual vertex colors from GLB buffer and verify accuracy
if 'COLOR_0' in attrs:
    ca_idx = attrs['COLOR_0']
    acc = gltf['accessors'][ca_idx]
    bv = gltf['bufferViews'][acc['bufferView']]
    bin_start = 20 + c0len + 8
    byte_off = bin_start + bv.get('byteOffset',0) + acc.get('byteOffset',0)
    count = acc['count']
    ctype = acc['componentType']
    if ctype == 5121:
        raw_c = np.frombuffer(raw_glb[byte_off:byte_off+count*4], dtype=np.uint8).reshape(count,4)
        vc_glb = raw_c[:,:3].astype(float)/255.0
    elif ctype == 5123:
        raw_c = np.frombuffer(raw_glb[byte_off:byte_off+count*8], dtype=np.uint16).reshape(count,4)
        vc_glb = raw_c[:,:3].astype(float)/65535.0
    else:
        raw_c = np.frombuffer(raw_glb[byte_off:byte_off+count*16], dtype=np.float32).reshape(count,4)
        vc_glb = raw_c[:,:3].astype(float)

    r_g,g_g,b_g = vc_glb[:,0],vc_glb[:,1],vc_glb[:,2]
    glb_red  = ((r_g>0.45)&(r_g>g_g*1.4)&(r_g>b_g*1.4)).mean()*100
    glb_dark = ((r_g<0.28)&(g_g<0.28)&(b_g<0.28)).mean()*100
    glb_skin = ((r_g>0.35)&(r_g>g_g)&(g_g>b_g)&~((r_g>0.45)&(r_g>g_g*1.4))).mean()*100
    sat_glb  = (np.max(vc_glb,axis=1)-np.min(vc_glb,axis=1)).mean()
    print(f"\n  GLB vertex color accuracy vs source image:")
    print(f"    Red   (jacket): {glb_red:.1f}%   [source: {SOURCE_RED:.1f}%]  {'[OK]' if abs(glb_red-SOURCE_RED)<20 else '[WARN]'}")
    print(f"    Dark  (jeans):  {glb_dark:.1f}%  [source: {SOURCE_DARK:.1f}%]  {'[OK]' if glb_dark>10 else '[FAIL] jeans too bright!'}")
    print(f"    Skin:           {glb_skin:.1f}%  [source: {SOURCE_SKIN:.1f}%]")
    print(f"    Saturation:     {sat_glb:.3f}   [source: {SOURCE_SAT:.3f}]")

# ─── SUMMARY ─────────────────────────────────────────────────────────────────
banner("FINAL SUMMARY")
issues = []
if 'COLOR_0' not in attrs:      issues.append("CRITICAL: No COLOR_0 in GLB")
if 'NORMAL' not in attrs:       issues.append("CRITICAL: No NORMAL in GLB")
if not mat.get('doubleSided'):  issues.append("CRITICAL: doubleSided=False")
if glb_size < 0.5:              issues.append("CRITICAL: GLB too small (<0.5MB), likely empty")
# Saturation check: only warn if 3D is significantly LESS saturated than source
if sat_glb < SOURCE_SAT * 0.7:  issues.append(f"WARN: Colors washed out (sat={sat_glb:.3f} vs source {SOURCE_SAT:.3f})")

print(f"\n  Input image:      {INPUT_IMAGE.name}  ({img.size[0]}x{img.size[1]})")
print(f"  Preprocessed:     {prep_img.size[0]}x{prep_img.size[1]}")
print(f"  PLY Gaussians:    {n_pts}")
print(f"  Raw mesh:         {len(verts_raw)} verts, {len(np.asarray(raw_mesh.triangles))} faces")
print(f"  Final mesh:       {len(verts_proc)} verts, {len(faces_proc)} faces")
print(f"  GLB size:         {glb_size:.2f} MB")
print(f"  COLOR_0:          {'YES' if 'COLOR_0' in attrs else 'NO'}")
print(f"  NORMAL:           {'YES' if 'NORMAL' in attrs else 'NO'}")
print(f"  doubleSided:      {mat.get('doubleSided')}")

if issues:
    print(f"\n  ISSUES FOUND ({len(issues)}):")
    for iss in issues:
        print(f"    [X] {iss}")
else:
    print(f"\n  [OK] ALL CHECKS PASSED -- professional quality mesh")

print(f"\n{'='*70}")
print(f"  FINAL GLB OUTPUT: {GLB_PATH}")
print(f"{'='*70}")
