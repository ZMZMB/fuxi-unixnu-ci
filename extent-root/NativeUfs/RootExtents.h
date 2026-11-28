// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
// Fuxi extent root (ported from ios-fuxi 0088-fuxi-extent-root.patch, sweet_ufs.c, to sheng's NativeUfs).
//
// The root image is one preallocated file inside Android's f2fs userdata. The ADT carries, under /chosen:
//   fuxi-root-extents  u64 triples {file block, partition block, blocks} in 4 KiB units, partition-relative
//   fuxi-root-blocks   u64 root size in 4 KiB blocks
// The file's logical blocks become the root device's address space. Reads inside the virtual region
// [kFxVirtualFirst, kFxVirtualFirst + blocks) are translated onto the file's physical blocks, so the parser
// and the window readers see the file as if it were the partition, while Android's own data (everything
// outside those extents) is never read for the root and never written.
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOLib.h>
#include <IOKit/IORegistryEntry.h>

// Upper bound on accepted entries, not on storage: the table is allocated from the IOKit heap when the
// property is read. A static 8192 entry array (196,608 B of __BSS) pushed the native __DATA segment past
// the retained-data window that XNU's prelink layout allows, so the kernel link failed.
#define kFxMaxExtents 8192U
// Virtual 4 KiB LBA base, well above any real partition on this LUN (userdata ends near 0x03a00000).
static constexpr uint64_t kFxVirtualFirst = 0x10000000ULL;

struct FxExtent { uint64_t file, part, count; };
static FxExtent *gFxExtent;
static uint32_t gFxExtentCount;
static uint32_t gFxExtentCapacity;
static bool gFxRootActive;
static uint64_t gFxRootBlocks;

static bool fxReserveExtents (uint32_t count)
{
  if (count <= gFxExtentCapacity) return gFxExtent != nullptr;
  uint32_t bytes = count * static_cast<uint32_t> (sizeof (FxExtent));
  FxExtent *fresh = static_cast<FxExtent *> (IOMalloc (bytes));
  if (!fresh) {
    IOLog ("FUXI ROOT: cannot allocate %u bytes for %u extents\n", bytes, count);
    return false;
  }
  if (gFxExtent) IOFree (gFxExtent, gFxExtentCapacity * static_cast<uint32_t> (sizeof (FxExtent)));
  gFxExtent = fresh;
  gFxExtentCapacity = count;
  return true;
}

// Logical root block -> device LBA plus the blocks left in that extent.
static bool fxMapRoot (uint64_t logical, uint64_t *lba, uint64_t *run)
{
  for (uint32_t i = 0; i < gFxExtentCount; ++i) {
    const FxExtent &e = gFxExtent[i];
    if (logical >= e.file && logical - e.file < e.count) {
      *lba = e.part + (logical - e.file);
      *run = e.count - (logical - e.file);
      return true;
    }
  }
  return false;
}

// Load the table and validate it against the physical userdata bounds the GPT reported.
static bool fxLoadRootExtents (uint64_t partFirst, uint64_t partLast)
{
  gFxExtentCount = 0;
  gFxRootActive = false;
  gFxRootBlocks = 0;
  IORegistryEntry *chosen = IORegistryEntry::fromPath ("/chosen", gIODTPlane);
  OSData *table = chosen ? OSDynamicCast (OSData, chosen->getProperty ("fuxi-root-extents")) : nullptr;
  OSData *blocksData = chosen ? OSDynamicCast (OSData, chosen->getProperty ("fuxi-root-blocks")) : nullptr;
  if (!chosen || !table || !blocksData) {
    IOLog ("FUXI ROOT: no extent table under /chosen (node=%d table=%d blocks=%d)\n",
           chosen != nullptr, table != nullptr, blocksData != nullptr);
    if (chosen) chosen->release ();
    return false;
  }
  uint32_t bytes = table->getLength ();
  uint64_t want = 0;
  if (blocksData->getLength () != sizeof (uint64_t)) {
    IOLog ("FUXI ROOT: fuxi-root-blocks is %u bytes\n", blocksData->getLength ());
    chosen->release ();
    return false;
  }
  memcpy (&want, blocksData->getBytesNoCopy (), sizeof (want));
  if (!want || bytes == 0 || bytes % (3 * sizeof (uint64_t)) || bytes / (3 * sizeof (uint64_t)) > kFxMaxExtents) {
    IOLog ("FUXI ROOT: extent table %u bytes, want 0x%llx blocks\n", bytes, want);
    chosen->release ();
    return false;
  }
  const uint64_t *entry = static_cast<const uint64_t *> (table->getBytesNoCopy ());
  uint32_t count = bytes / (3 * sizeof (uint64_t));
  if (!fxReserveExtents (count)) {
    chosen->release ();
    return false;
  }
  uint64_t partBlocks = partLast - partFirst + 1, covered = 0;
  IOLog ("FUXI ROOT: %u extents, 0x%llx blocks, partition first 0x%llx (%llu blocks)\n",
         count, want, partFirst, partBlocks);
  for (uint32_t i = 0; i < count && covered < want; ++i) {
    uint64_t file = entry[3 * i], part = entry[3 * i + 1], run = entry[3 * i + 2];
    if (i < 8) IOLog ("FUXI ROOT: ext[%u] file=0x%llx part=0x%llx count=0x%llx\n", i, file, part, run);
    if (file != covered || !run || part >= partBlocks || run > partBlocks - part) {
      IOLog ("FUXI ROOT: extent %u invalid (file 0x%llx want 0x%llx)\n", i, file, covered);
      chosen->release ();
      return false;
    }
    if (run > want - covered) run = want - covered;
    for (uint32_t j = 0; j < i; ++j) {
      if (part < gFxExtent[j].part + gFxExtent[j].count && gFxExtent[j].part < part + run) {
        IOLog ("FUXI ROOT: extents %u and %u overlap\n", j, i);
        chosen->release ();
        return false;
      }
    }
    gFxExtent[i].file = file;
    gFxExtent[i].part = part;
    gFxExtent[i].count = run;
    gFxExtentCount = i + 1;
    covered += run;
  }
  chosen->release ();
  if (covered != want) {
    IOLog ("FUXI ROOT: extents cover 0x%llx of 0x%llx blocks\n", covered, want);
    gFxExtentCount = 0;
    return false;
  }
  gFxRootBlocks = want;
  gFxRootActive = true;
  IOLog ("FUXI ROOT: root file in userdata, %u extents, 0x%llx blocks at virtual 0x%llx\n",
         gFxExtentCount, gFxRootBlocks, kFxVirtualFirst);
  return true;
}
