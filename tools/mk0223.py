import subprocess
import sys

# ---------- SweetSurface.h: give the pool allocators C linkage ----------
p = 'artifacts/patchgen/SweetSurface_0223_after.h'
s = open(p, encoding='utf-8').read()
old = """#if defined(ARM64_BOARD_CONFIG_VINCE)
/* Physically contiguous pixel/BO memory from the pool reserved at VM init. */
uint64_t sweet_pixels_alloc(vm_size_t size);
void sweet_pixels_free(uint64_t pa, vm_size_t size);
#endif
"""
new = """#if defined(ARM64_BOARD_CONFIG_VINCE)
/* Physically contiguous pixel/BO memory from the pool reserved at VM init.
 * C linkage: vince_adreno.c reserves the GPU shadow buffer with these. */
#ifdef __cplusplus
extern "C" {
#endif
uint64_t sweet_pixels_alloc(vm_size_t size);
void sweet_pixels_free(uint64_t pa, vm_size_t size);
#ifdef __cplusplus
}
#endif
#endif
"""
assert s.count(old) == 1, s.count(old)
open(p, 'w', encoding='utf-8').write(s.replace(old, new))

# ---------- vince_adreno.c: shadow copies of the submitted IBs ----------
p = 'artifacts/patchgen/vince_adreno_0223_after.c'
s = open(p, encoding='utf-8').read()


def rep(old, new):
    global s
    c = s.count(old)
    if c != 1:
        raise SystemExit('replacement count %d for:\n%s' % (c, old[:200]))
    s = s.replace(old, new)


rep("""extern vm_offset_t kvtophys(vm_offset_t va);
""",
"""extern vm_offset_t kvtophys(vm_offset_t va);
extern uint64_t sweet_pixels_alloc(vm_size_t size);   /* SweetSurface.cpp */
""")

shadow = r'''
/*
 * Client command buffers are CPU-written and reused by Mesa, while the CP
 * reads them asynchronously.  Copy the outer IB and every IB it chains into
 * a kernel-owned slot, patching the indirect-buffer addresses in the copy,
 * so a later userspace write can never change what the CP is executing.
 */
#define GPU_SHADOW_SIZE   (1u << 20)
#define GPU_SHADOW_SLOT   (64u << 10)
#define GPU_SHADOW_SLOTS  (GPU_SHADOW_SIZE / GPU_SHADOW_SLOT)

static uint64_t gpu_shadow_pa;
static uint32_t gpu_shadow_fence[GPU_SHADOW_SLOTS];
static uint32_t gpu_shadow_next;

static uint64_t
shadow_copy_ib(vm_offset_t slot_va, uint64_t slot_pa, uint32_t *used,
    uint64_t pa, uint32_t dwords, int depth)
{
	uint32_t at = (*used + 63u) & ~63u;
	vm_size_t bytes = (vm_size_t)((pa & 0xfffu) + (uint64_t)dwords * 4u);
	vm_offset_t va = ml_io_map((vm_offset_t)(pa & ~0xfffull),
	    (bytes + 0xfffu) & ~(vm_size_t)0xfffu);
	uint32_t off = (uint32_t)(pa & 0xfffu);
	uint64_t new_pa = slot_pa + at;

	if (va == 0 || dwords == 0 || at + dwords * 4u > GPU_SHADOW_SLOT) {
		return 0;
	}
	for (uint32_t j = 0; j < dwords; j++) {
		reg_write(slot_va, at + j * 4u, reg_read(va, off + j * 4u));
	}

	if (depth < 2) {
		for (uint32_t j = 0; j + 4 <= dwords; j++) {
			uint32_t h = reg_read(slot_va, at + j * 4u);

			if ((h & 0x7f000000u) == 0x70000000u &&
			    ((h >> 16) & 0x7fu) == CP_INDIRECT_BUFFER_PFE &&
			    (h & 0x3fffu) == 3u) {
				uint64_t np = reg_read(slot_va, at + (j + 1) * 4u) |
				    ((uint64_t)reg_read(slot_va, at + (j + 2) * 4u) << 32);
				uint32_t nw = reg_read(slot_va, at + (j + 3) * 4u);

				if ((np >> 32) == 0 && np >= 0x40000000ull &&
				    nw >= 4 && nw <= 65535u) {
					uint64_t npa = shadow_copy_ib(slot_va, slot_pa,
					    used, np, nw, depth + 1);

					if (npa != 0) {
						reg_write(slot_va, at + (j + 1) * 4u, (uint32_t)npa);
						reg_write(slot_va, at + (j + 2) * 4u, (uint32_t)(npa >> 32));
					}
				}
			}
		}
	}
	*used = at + dwords * 4u;
	return new_pa;
}

static bool
shadow_prepare(const uint64_t *addresses, const uint32_t *words, uint32_t count,
    uint64_t *copy_pa, uint32_t *out_slot)
{
	uint32_t slot = 0, used = 0;
	bool found = false;
	vm_offset_t va;
	uint64_t slot_pa;

	if (gpu_shadow_pa == 0) {
		gpu_shadow_pa = sweet_pixels_alloc(GPU_SHADOW_SIZE);
		printf("adreno: gpu shadow %s at %#llx\n",
		    gpu_shadow_pa ? "ready" : "unavailable",
		    (unsigned long long)gpu_shadow_pa);
	}
	if (gpu_shadow_pa == 0 || count > IB_TRACK) {
		return false;
	}
	for (uint32_t s = 0; s < GPU_SHADOW_SLOTS; s++) {
		uint32_t cand = (gpu_shadow_next + s) % GPU_SHADOW_SLOTS;

		if (gpu_shadow_fence[cand] == 0 ||
		    vince_gpu_done(gpu_shadow_fence[cand])) {
			slot = cand;
			found = true;
			break;
		}
	}
	if (!found) {
		return false;
	}
	slot_pa = gpu_shadow_pa + (uint64_t)slot * GPU_SHADOW_SLOT;
	va = ml_io_map((vm_offset_t)slot_pa, GPU_SHADOW_SLOT);
	if (va == 0) {
		return false;
	}
	for (uint32_t i = 0; i < count; i++) {
		uint64_t npa = shadow_copy_ib(va, slot_pa, &used, addresses[i], words[i], 0);

		if (npa == 0) {
			return false;
		}
		copy_pa[i] = npa;
	}
	flush_dcache64((addr64_t)slot_pa, GPU_SHADOW_SLOT, TRUE);
	gpu_shadow_next = (slot + 1) % GPU_SHADOW_SLOTS;
	*out_slot = slot;
	return true;
}

'''
anchor = 'uint32_t\nvince_gpu_submit(const uint64_t *addresses'
rep(anchor, shadow + anchor)

rep("""	uint32_t needed = count * 4 + 16;
	uint32_t i;
""",
"""	uint32_t needed = count * 4 + 16;
	uint64_t copy_pa[IB_TRACK];
	uint32_t shadow_slot = 0;
	bool use_copy = false;
	uint32_t i;
""")

rep("""	for (i = 0; i < count; i++) {
		rb_emit(pkt7(CP_INDIRECT_BUFFER_PFE, 3));
		rb_emit((uint32_t)addresses[i]);
		rb_emit(0);
		rb_emit(words[i]);
	}
""",
"""	use_copy = shadow_prepare(addresses, words, count, copy_pa, &shadow_slot);

	for (i = 0; i < count; i++) {
		uint64_t addr = use_copy ? copy_pa[i] : addresses[i];

		rb_emit(pkt7(CP_INDIRECT_BUFFER_PFE, 3));
		rb_emit((uint32_t)addr);
		rb_emit((uint32_t)(addr >> 32));
		rb_emit(words[i]);
	}
""")

rep("""		printf("adreno: submit %d: %u IBs fence %u RPTR=%u WPTR=%u\\n",
			submits_logged, count, gpu_fence, gr(A5_CP_RB_RPTR), rb_wptr);
		for (uint32_t k = 0; k < count && k < 8; k++) {
			printf("adreno:  ib %u pa %#llx dwords %u\\n", k,
				(unsigned long long)addresses[k], words[k]);
			dump_ib(addresses[k], words[k]);
		}
""",
"""		printf("adreno: submit %d: %u IBs fence %u shadow %d RPTR=%u WPTR=%u\\n",
			submits_logged, count, gpu_fence, use_copy ? (int)shadow_slot : -1,
			gr(A5_CP_RB_RPTR), rb_wptr);
		for (uint32_t k = 0; k < count && k < 8; k++) {
			printf("adreno:  ib %u pa %#llx dwords %u copy %#llx\\n", k,
				(unsigned long long)addresses[k], words[k],
				(unsigned long long)(use_copy ? copy_pa[k] : 0));
			dump_ib(addresses[k], words[k]);
		}
""")

rep("""	__asm__ volatile("dsb sy" ::: "memory");
	gw(A5_CP_RB_WPTR, rb_wptr);

	return gpu_fence;
}
""",
"""	__asm__ volatile("dsb sy" ::: "memory");
	gw(A5_CP_RB_WPTR, rb_wptr);
	if (use_copy) {
		gpu_shadow_fence[shadow_slot] = gpu_fence;
	}

	return gpu_fence;
}
""")

open(p, 'w', encoding='utf-8').write(s)


def make_diff(before, after, path):
    d = subprocess.run(['git', 'diff', '--no-index', '--no-color', before, after],
                       capture_output=True, text=True).stdout
    fixed = []
    for l in d.splitlines():
        if l.startswith('diff --git '):
            fixed.append('diff --git a/%s b/%s' % (path, path))
        elif l.startswith('--- '):
            fixed.append('--- a/%s' % path)
        elif l.startswith('+++ '):
            fixed.append('+++ b/%s' % path)
        else:
            fixed.append(l)
    return '\n'.join(fixed) + '\n'


data = make_diff('artifacts/patchgen/vince_adreno_0223_before.c',
                 'artifacts/patchgen/vince_adreno_0223_after.c', 'bsd/dev/vince_adreno.c')
data += make_diff('artifacts/patchgen/SweetSurface_0223_before.h',
                  'artifacts/patchgen/SweetSurface_0223_after.h',
                  'iokit/Kernel/arm/SweetSurface.h')
open('xnu/patches/0223-vince-gpu-shadow-ib.patch', 'w', newline='\n').write(
    data.replace('\r\n', '\n'))
print('written')
