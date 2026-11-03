#!/bin/bash
# Build sweetgl.dylib on a macOS runner: Mesa (freedreno + GLES, static) plus
# the libdrm/msm emulation and the EAGL shim.  Mesa is expected in
# $MESA_SRC (default research/mesa); the build tree is $MESA_BUILD.
set -euo pipefail
H=$(cd "$(dirname "$0")" && pwd)
R=$(cd "$H/../.." && pwd)
M=${MESA_SRC:-$R/research/mesa}
B=${MESA_BUILD:-$R/research/mesa-ios}
SDK=${IOS_SDK:-$(xcrun --sdk iphoneos --show-sdk-path)}
CC=${IOS_CC:-$(xcrun --sdk iphoneos --find clang)}
CXX=${IOS_CXX:-$(xcrun --sdk iphoneos --find clang++)}
AR=${IOS_AR:-$(xcrun --sdk iphoneos --find ar)}
STRIP=${IOS_STRIP:-$(xcrun --sdk iphoneos --find strip)}
NM=${IOS_NM:-$(xcrun --sdk iphoneos --find nm)}
IOSFLAGS=(-arch arm64 -isysroot "$SDK" -miphoneos-version-min=16.0)

[ -f "$M/meson.build" ] || { echo "no Mesa source at $M" >&2; exit 1; }
if ! grep -q sweet_drm_bo_map "$M/src/freedreno/drm/freedreno_bo.c"; then
    patch -p1 -d "$M" --forward < "$H/mesa.patch"
fi

cat > "$H/ios-cross-ci.txt" <<EOF
[binaries]
c = ['$CC', '-arch', 'arm64', '-isysroot', '$SDK', '-miphoneos-version-min=16.0']
cpp = ['$CXX', '-arch', 'arm64', '-isysroot', '$SDK', '-miphoneos-version-min=16.0']
objc = ['$CC', '-arch', 'arm64', '-isysroot', '$SDK', '-miphoneos-version-min=16.0']
ar = '$AR'
strip = '$STRIP'
pkg-config = 'false'

[built-in options]
c_args = ['-I$H/include']
cpp_args = ['-I$H/include']

[host_machine]
system = 'darwin'
subsystem = 'ios'
cpu_family = 'aarch64'
cpu = 'arm64'
endian = 'little'
EOF

rm -rf "$B"
meson setup "$B" "$M" --cross-file "$H/ios-cross-ci.txt" \
    --buildtype=release -Db_ndebug=true -Ddefault_library=static \
    -Dplatforms= -Degl=disabled -Dglx=disabled -Dgbm=disabled \
    -Dgallium-drivers=freedreno -Dvulkan-drivers= -Dfreedreno-kmds=msm \
    -Dllvm=disabled -Dgles1=disabled -Dgles2=enabled -Dopengl=true \
    -Dzstd=disabled -Dzlib=disabled -Dexpat=disabled -Dxmlconfig=disabled \
    -Dvalgrind=disabled -Dlibunwind=disabled -Dlmsensors=disabled \
    -Dbuild-tests=false -Dshader-cache=disabled -Dperfetto=false \
    -Dgallium-va=disabled -Dgallium-rusticl=false -Dtools= \
    -Dhtml-docs=disabled -Ddisplay-info=disabled -Dteflon=false

LIBS="src/mesa/libmesa.a src/gallium/auxiliary/libgallium.a
	src/gallium/drivers/freedreno/libfreedreno.a
	src/gallium/winsys/freedreno/drm/libfreedrenowinsys.a
	src/freedreno/drm/libfreedreno_drm.a src/freedreno/ir3/libfreedreno_ir3.a
	src/freedreno/ir2/libfreedreno_ir2.a src/freedreno/fdl/libfreedreno_layout.a
	src/freedreno/common/libfreedreno_common.a src/freedreno/isa/libir3encode.a
	src/freedreno/isa/libir3decode.a src/compiler/isaspec/libisaspec.a
	src/freedreno/perfcntrs/libfreedreno_perfcntrs.a
	src/compiler/glsl/libglsl.a src/compiler/glsl/glcpp/libglcpp.a src/compiler/nir/libnir.a
	src/compiler/spirv/libvtn.a src/compiler/libcompiler.a
	src/mesa/glapi/glapi/libglapi_bridge.a src/mesa/glapi/shared-glapi/libglapi.a
	src/util/libxmlconfig.a src/util/libmesa_util.a src/util/libmesa_util_simd.a src/util/blake3/libblake3.a
	src/c11/impl/libmesa_util_c11.a"
(cd "$B" && ninja $LIBS)

O=$H/out
mkdir -p "$O"
"$NM" -g "$B/src/mesa/glapi/glapi/libglapi_bridge.a" > "$O/bridge.nm"
python3 -I -c '
import json, shlex, sys
cc = json.load(open(sys.argv[1]))
e = [x for x in cc if x["file"].endswith("state_tracker/st_manager.c")][0]
print("\n".join(shlex.quote(a) for a in shlex.split(e["command"]) if a.startswith("-D")))
' "$B/compile_commands.json" > "$O/mesa-defines.rsp"
python3 -I "$H/gen-dispatch.py" "$H/ios-dispatch.txt" "$M/include" "$O/bridge.nm" "$O/dispatch.c"

INC=(-I"$H/include" -I"$M/include" -I"$M/src" -I"$M/src/mesa" -I"$M/src/mapi"
	-I"$M/src/gallium/include" -I"$M/src/gallium/auxiliary" -I"$M/src/gallium/drivers"
	-I"$M/src/gallium/winsys" -I"$B/src" -I"$B/src/mesa" -I"$B/src/mapi" -I"$H")
for f in sweetgl sweet_drm eagl layerdump "$O/dispatch"; do
	case $f in /*) src=$f.c ;; *) src=$H/$f.c ;; esac
	"$CC" -O2 -Wall -fvisibility=hidden "${IOSFLAGS[@]}" @"$O/mesa-defines.rsp" \
	    "${INC[@]}" -c "$src" -o "$O/$(basename "$f").o"
done
printf '_sweetgl_init\n_sweetgl_create\n_sweetgl_make_current\n_sweetgl_destroy\n_sweetgl_selftest\n' > "$O/exports.txt"
"$CXX" "${IOSFLAGS[@]}" -dynamiclib -dead_strip -install_name /usr/lib/sweetgl.dylib \
    -exported_symbols_list "$O/exports.txt" -o "$O/sweetgl.dylib" \
    "$O/sweetgl.o" "$O/sweet_drm.o" "$O/eagl.o" "$O/layerdump.o" "$O/dispatch.o" \
    $(for l in $LIBS; do echo "$B/$l"; done) \
    -framework IOKit -framework CoreFoundation -framework IOSurface \
    -framework OpenGLES -framework CoreGraphics -framework Foundation \
    -lobjc -lc++ -lz
codesign -f -s - "$O/sweetgl.dylib"
echo "built $O/sweetgl.dylib ($(stat -f %z "$O/sweetgl.dylib") bytes)"
