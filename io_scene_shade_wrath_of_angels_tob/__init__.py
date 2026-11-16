bl_info = {
    "name": "Shade: Wrath of Angels .tob Importer",
    "author": "DeepSeek & Choozhik",
    "version": (1, 0),
    "blender": (3, 0, 0),
    "location": "File > Import > Shade: Wrath of Angels (.tob)",
    "description": "Model importer .tob from game Shade: Wrath of Angels",
    "category": "Import-Export",
}

import bpy
import struct
import math
import os
import bmesh
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty, FloatProperty

# ==========================================
# TRANSLATIONS (EN / RU)
# ==========================================
translations = {
    "en": {
        "scale": "Scale",
        "scale_desc": "Apply scale to imported models",
        "imported": "Imported: {}",
        "error_bvrt": "Chunk BVRT not found in {}",
        "error_indx": "Chunk INDX not found in {}",
        "error_file": "File not found: {}",
    },
    "ru": {
        "scale": "Масштаб",
        "scale_desc": "Применить масштаб к импортируемым моделям",
        "imported": "Импортировано: {}",
        "error_bvrt": "Чанк BVRT не найден в {}",
        "error_indx": "Чанк INDX не найден в {}",
        "error_file": "Файл не найден: {}",
    }
}

def get_text(key):
    """Returns translation based on Blender UI language."""
    try:
        lang = bpy.context.preferences.view.language
        if lang.startswith('ru'):
            return translations['ru'].get(key, translations['en'].get(key, key))
    except:
        pass
    return translations['en'].get(key, key)


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def attach_texture(obj, model_path):
    """Creates material and looks for .dds or .tga texture near the model."""
    base_name = os.path.splitext(os.path.basename(model_path))[0]
    folder = os.path.dirname(model_path)

    texture_path = None
    for ext in ['.dds', '.tga']:
        candidate = os.path.join(folder, base_name + ext)
        if os.path.exists(candidate):
            texture_path = candidate
            break

    mat = bpy.data.materials.new(name=f"{base_name}_Material")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    principled = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)

    if texture_path:
        print(f"[.tob] Found texture: {texture_path}")
        img = bpy.data.images.load(texture_path)

        tex_node = nodes.new(type='ShaderNodeTexImage')
        tex_node.image = img
        tex_node.location = (-400, 0)

        # Connect only the color. Alpha channel is ignored.
        links.new(tex_node.outputs['Color'], principled.inputs['Base Color'])
        
        # Set blend method to OPAQUE just in case
        mat.blend_method = 'OPAQUE'
    else:
        print(f"[.tob] WARNING: Texture {base_name}.dds/.tga not found in {folder}")
        principled.inputs['Base Color'].default_value = (0.5, 0.5, 0.5, 1.0)

    obj.data.materials.clear()
    obj.data.materials.append(mat)


def clean_mesh_api(mesh):
    """Removes doubles and recalculates normals without bpy.ops."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()


def process_tob_file(filepath, scale):
    """Parses a .tob file and creates an object. Returns True on success."""
    try:
        with open(filepath, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        print(get_text("error_file").format(filepath))
        return False

    vertices = []
    uvs = []
    faces = []

    # 1. Read vertices (BVRT)
    bvrt_offset = data.find(b'BVRT')
    if bvrt_offset == -1:
        print(get_text("error_bvrt").format(filepath))
        return False

    bvrt_size = struct.unpack('>I', data[bvrt_offset+4:bvrt_offset+8])[0]
    vert_data = data[bvrt_offset+8 : bvrt_offset+8+bvrt_size]

    num_verts = bvrt_size // 32
    print(f"[.tob] {os.path.basename(filepath)} -> Vertices: {num_verts}")

    for i in range(num_verts):
        offset = i * 32
        x, y, z, nx, ny, nz, u, v = struct.unpack('<8f', vert_data[offset:offset+32])
        vertices.append((x * scale, -z * scale, y * scale))
        uvs.append((u, 1.0 - v)) 

    # 2. Read indices (INDX)
    indx_offset = data.find(b'INDX')
    if indx_offset == -1:
        print(get_text("error_indx").format(filepath))
        return False

    indx_size = struct.unpack('>I', data[indx_offset+4:indx_offset+8])[0]
    idx_data = data[indx_offset+8 : indx_offset+8+indx_size]

    num_indices = indx_size // 2
    indices = struct.unpack(f'<{num_indices}H', idx_data)

    for i in range(0, num_indices, 3):
        if i+2 < num_indices:
            faces.append((indices[i], indices[i+1], indices[i+2]))

    # 3. Create mesh
    obj_name = os.path.splitext(os.path.basename(filepath))[0]
    mesh = bpy.data.meshes.new(f"{obj_name}_Mesh")
    obj = bpy.data.objects.new(obj_name, mesh)
    
    bpy.context.collection.objects.link(obj)

    # Always rotate -90 degrees on X
    obj.rotation_euler[0] = math.radians(-90)

    mesh.from_pydata(vertices, [], faces)
    mesh.update()

    # 4. UV Layout
    if mesh.uv_layers:
        uv_layer = mesh.uv_layers.active.data
    else:
        uv_layer = mesh.uv_layers.new(name="UVMap").data
        
    for poly in mesh.polygons:
        for loop_index in poly.loop_indices:
            vert_index = mesh.loops[loop_index].vertex_index
            uv_layer[loop_index].uv = uvs[vert_index]

    # 5. Texture
    attach_texture(obj, filepath)

    # 6. Cleanup
    clean_mesh_api(mesh)

    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    print(get_text("imported").format(obj_name))
    return True


# ==========================================
# OPERATOR (SINGLE & MULTIPLE FILES)
# ==========================================
class IMPORT_OT_tob(bpy.types.Operator, ImportHelper):
    """Import one or multiple .tob files"""
    bl_idname = "import_scene.tob"
    bl_label = "Import .tob"
    bl_options = {'REGISTER', 'UNDO'}

    # Allow selecting multiple files
    filename_ext = ".tob"
    filter_glob: StringProperty(
        default="*.tob",
        options={'HIDDEN'},
        maxlen=255,
    )
    files: bpy.props.CollectionProperty(
        name="File Path",
        type=bpy.types.OperatorFileListElement,
    )
    directory: StringProperty(
        subtype='DIR_PATH',
    )

    scale: FloatProperty(
        name="Scale",
        description="Apply scale to imported models",
        default=1.0,
        min=0.001,
        max=1000.0
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "scale")

    def execute(self, context):
        # If files are not passed via multi-select, use filepath
        if not self.files:
            self.files.append(bpy.types.OperatorFileListElement(filepath=self.filepath))
        
        count = 0
        for file_elem in self.files:
            # Build full path: folder + filename
            if self.directory:
                full_path = os.path.join(self.directory, file_elem.name)
            else:
                full_path = file_elem.name

            if process_tob_file(full_path, self.scale):
                count += 1

        self.report({'INFO'}, f"Imported {count} file(s)")
        return {'FINISHED'}


# ==========================================
# MENU FUNCTION
# ==========================================
def menu_func_import(self, context):
    self.layout.operator(IMPORT_OT_tob.bl_idname, text="Shade: Wrath of Angels (.tob)")


# ==========================================
# REGISTRATION
# ==========================================
classes = (
    IMPORT_OT_tob,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
