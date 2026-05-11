import sys, warnings, logging
sys.path.insert(0, r'd:\3D\styleforge')
warnings.filterwarnings('ignore')
logging.disable(logging.WARNING)
import numpy as np
from app.core.pipeline import Avatar3DPipeline

pipeline = Avatar3DPipeline()
result = pipeline.run_from_ply(
    ply_path=r'd:\3D\styleforge\temp\f223402baff148c9\lhm_output\lhm_output.ply',
    job_id='test_color_fix3'
)
print('Status:', result.status)
print('Error:', result.error)
print('GLB:', result.glb_path)

import struct, json
with open(result.glb_path, 'rb') as f:
    f.read(12)
    c, _ = struct.unpack('<II', f.read(8))
    gltf = json.loads(f.read(c))
attrs = gltf['meshes'][0]['primitives'][0]['attributes']
mat = gltf['materials'][0]
print('COLOR_0:', 'COLOR_0' in attrs)
print('NORMAL:', 'NORMAL' in attrs)
print('doubleSided:', mat.get('doubleSided'))

# Read vertex colors directly from GLB binary buffer via GLTF accessor
with open(result.glb_path, 'rb') as f:
    raw = f.read()
# GLB: 12-byte header, chunk0=JSON, chunk1=BIN
chunk0_len, _ = struct.unpack('<II', raw[12:20])
json_end = 20 + chunk0_len
bin_start = json_end + 8  # skip chunk1 header
# Find COLOR_0 accessor
color_accessor_idx = attrs['COLOR_0']
accessor = gltf['accessors'][color_accessor_idx]
bv = gltf['bufferViews'][accessor['bufferView']]
byte_offset = bin_start + bv.get('byteOffset', 0) + accessor.get('byteOffset', 0)
count = accessor['count']
# VEC4 UNSIGNED_BYTE (5121) or FLOAT (5126)
comp_type = accessor['componentType']
if comp_type == 5121:  # UNSIGNED_BYTE
    raw_colors = np.frombuffer(raw[byte_offset:byte_offset + count*4], dtype=np.uint8).reshape(count, 4)
    vc = raw_colors[:, :3].astype(float) / 255.0
elif comp_type == 5123:  # UNSIGNED_SHORT
    raw_colors = np.frombuffer(raw[byte_offset:byte_offset + count*8], dtype=np.uint16).reshape(count, 4)
    vc = raw_colors[:, :3].astype(float) / 65535.0
else:  # FLOAT
    raw_colors = np.frombuffer(raw[byte_offset:byte_offset + count*16], dtype=np.float32).reshape(count, 4)
    vc = raw_colors[:, :3].astype(float)
r, gr, b = vc[:,0], vc[:,1], vc[:,2]
if True:
    red = ((r > 0.45) & (r > gr*1.4) & (r > b*1.4)).mean()*100
    dark = ((r < 0.28) & (gr < 0.28) & (b < 0.28)).mean()*100
    skin = ((r > 0.35) & (r > gr) & (gr > b) & ~((r > 0.45) & (r > gr*1.4))).mean()*100
    sat = (np.max(vc, axis=1) - np.min(vc, axis=1)).mean()
    print()
    print(f"=== Color accuracy vs source image ===")
    print(f"Red (jacket):  {red:.1f}%   [source: 39.7%]  {'OK' if abs(red-39.7)<15 else 'POOR'}")
    print(f"Dark (jeans):  {dark:.1f}%   [source: 28.1%]  {'OK' if dark>15 else 'POOR (still blurred)'}")
    print(f"Skin tones:    {skin:.1f}%   [source: 13.7%]  {'OK' if abs(skin-13.7)<10 else 'POOR'}")
    print(f"Mean saturation: {sat:.3f}  (was ~0.25 before fix, higher=more vivid)")
    print(f"RGB means: R={r.mean():.3f} G={gr.mean():.3f} B={b.mean():.3f}")
