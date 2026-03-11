/**
 * ╔══════════════════════════════════════════════════════════════════╗
 * ║              OPTIMA — INSTRUMENT REGISTRY LOADER                 ║
 * ║                                                                  ║
 * ║  Loads all instrument module files. Each file registers itself   ║
 * ║  into INSTRUMENT_REGISTRY with fieldGroups, mapPayload, etc.    ║
 * ║                                                                  ║
 * ║  To add a new instrument:                                        ║
 * ║  1. Create instruments/<asset>/<name>.js                         ║
 * ║  2. Add a <script> tag below                                     ║
 * ║  That's it — the core picks it up automatically.                ║
 * ╚══════════════════════════════════════════════════════════════════╝
 *
 * Load order:
 *   1. schema_master.js     → SCHEMA, INSTRUMENT_REGISTRY = {}
 *   2. instruments/_base.js → shared field blocks
 *   3. This file            → loads all instrument modules
 *   4. optima_core.js       → uses INSTRUMENT_REGISTRY
 */

// Registry is already created by schema_master.js
// Each instrument file below adds itself:
//   INSTRUMENT_REGISTRY['fx_forward'] = { fieldGroups, mapPayload, ... }

// Verification — run after all scripts loaded
function verifyRegistry() {
  const registered = Object.keys(INSTRUMENT_REGISTRY);
  const schemaKeys = Object.keys(SCHEMA);
  const missing = schemaKeys.filter(k => !INSTRUMENT_REGISTRY[k]);
  if (missing.length) {
    console.warn('[Registry] Instruments in SCHEMA but not registered:', missing);
  }
  console.log(`[Registry] ${registered.length} instruments registered`);
}

// Run verification after page load
window.addEventListener('load', verifyRegistry);
